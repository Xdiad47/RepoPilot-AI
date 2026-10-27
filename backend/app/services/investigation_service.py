"""Investigation lifecycle: queueing, concurrency limit, event log, SSE fan-out, persistence, cleanup.

Each investigation gets its own unguessable id and its own workspace. Results are kept in memory and mirrored to
JSON files so they survive a restart; expired ones are purged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from pathlib import Path

from app.core.config import Settings
from app.core.errors import AppError, InvestigationNotFound, LLMNotConfigured
from app.core.security import is_valid_investigation_id
from app.schemas.models import (
    ErrorInfo,
    Investigation,
    InvestigationEvent,
    InvestigationStatus,
    RepairRequest,
    RepairResult,
    RepositoryInfo,
    utcnow,
)
from app.services.repair_agent import EventDetail, RepairAgent
from app.services.repository_service import Workspace

logger = logging.getLogger(__name__)

_TERMINAL = {InvestigationStatus.COMPLETED, InvestigationStatus.FAILED}
_MAX_EVENTS = 200


class _Record:
    """In-memory state for one investigation plus the primitive used to wake SSE listeners."""

    def __init__(self, investigation: Investigation) -> None:
        self.investigation = investigation
        self.changed = asyncio.Event()
        self.task: asyncio.Task | None = None

    def notify(self) -> None:
        self.investigation.updated_at = utcnow()
        self.changed.set()
        self.changed = asyncio.Event()


class _Handle:
    """The Progress implementation handed to the agent; every call mutates the investigation for real."""

    def __init__(self, record: _Record) -> None:
        self._r = record

    def emit(self, stage: str, status: str, message: str, detail: EventDetail | None = None) -> None:
        events = self._r.investigation.events
        if len(events) >= _MAX_EVENTS:
            return
        events.append(
            InvestigationEvent(
                seq=len(events) + 1, timestamp=utcnow(), stage=stage, status=status,  # type: ignore[arg-type]
                message=message[:500], detail=detail,
            )
        )
        self._r.notify()

    def set_repository(self, info: RepositoryInfo) -> None:
        self._r.investigation.repository = info
        self._r.notify()

    def set_result(self, result: RepairResult) -> None:
        self._r.investigation.result = result
        self._r.notify()


class InvestigationManager:
    def __init__(self, settings: Settings, agent_factory: Callable[[], RepairAgent]) -> None:
        self._s = settings
        self._agent_factory = agent_factory
        self._records: dict[str, _Record] = {}
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_investigations)
        self._store = settings.data_dir / "investigations"
        self._waiting = 0  # accepted, waiting for a free slot
        self._running = 0  # currently executing
        self._load_persisted()

    # --- submission -------------------------------------------------------------------------------------
    def submit(self, request: RepairRequest) -> Investigation:
        if not self._s.llm_configured:
            raise LLMNotConfigured()
        self._purge_expired()
        investigation_id = uuid.uuid4().hex
        now = utcnow()
        investigation = Investigation(
            id=investigation_id, status=InvestigationStatus.QUEUED, created_at=now, updated_at=now,
            repository_url=request.repository_url, bug_description=request.bug_description,
            stack_trace=request.stack_trace,
        )
        record = _Record(investigation)
        self._records[investigation_id] = record
        _Handle(record).emit("queued", "info", self._queue_message())
        self._waiting += 1  # counted at submit time so the next caller sees an accurate queue
        record.task = asyncio.create_task(self._run(record, request), name=f"investigation-{investigation_id}")
        return investigation

    def _queue_message(self) -> str:
        ahead = self._waiting + self._running
        free = ahead < self._s.max_concurrent_investigations
        return "Investigation accepted" if free else f"Investigation queued ({ahead} ahead of it)"

    async def _run(self, record: _Record, request: RepairRequest) -> None:
        inv = record.investigation
        handle = _Handle(record)
        workspace = Workspace(self._s.workspace_root, inv.id)
        try:
            async with self._semaphore:
                self._waiting -= 1
                self._running += 1
                try:
                    inv.status = InvestigationStatus.RUNNING
                    record.notify()
                    workspace.create()
                    agent = self._agent_factory()
                    await asyncio.wait_for(
                        agent.run(request, workspace, handle), timeout=self._s.investigation_timeout_seconds
                    )
                    inv.status = InvestigationStatus.COMPLETED
                finally:
                    self._running -= 1
        except TimeoutError:
            self._fail(record, "timeout", f"The investigation exceeded the {self._s.investigation_timeout_seconds}s time limit.")
        except asyncio.CancelledError:
            self._fail(record, "cancelled", "The investigation was cancelled because the server is shutting down.")
            raise
        except AppError as exc:
            self._fail(record, exc.code, exc.message)
        except Exception:  # noqa: BLE001 - never leak internals to the client
            logger.exception("Unhandled error in investigation %s", inv.id)
            self._fail(record, "internal_error", "An unexpected error occurred while investigating this repository.")
        finally:
            workspace.cleanup()
            record.notify()
            self._persist(record)

    def _fail(self, record: _Record, code: str, message: str) -> None:
        inv = record.investigation
        if inv.status in (InvestigationStatus.QUEUED,):
            self._waiting = max(0, self._waiting - 1)
        stage = inv.events[-1].stage if inv.events else None
        inv.status = InvestigationStatus.FAILED
        inv.error = ErrorInfo(code=code, message=message, stage=stage)
        _Handle(record).emit(stage or "finalize", "failed", message)

    # --- reads ------------------------------------------------------------------------------------------
    def get(self, investigation_id: str) -> Investigation:
        return self._record(investigation_id).investigation

    def _record(self, investigation_id: str) -> _Record:
        if not is_valid_investigation_id(investigation_id):
            raise InvestigationNotFound()
        record = self._records.get(investigation_id)
        if record is None:
            raise InvestigationNotFound()
        return record

    def diff(self, investigation_id: str) -> str:
        inv = self.get(investigation_id)
        if inv.result is None or not inv.result.diff:
            raise AppError("no_patch", "This investigation has no patch.", 404)
        return inv.result.diff

    async def stream(self, investigation_id: str, last_seq: int = 0) -> AsyncIterator[str]:
        """Server-sent events. Replays missed events, then follows live ones until the investigation ends."""
        record = self._record(investigation_id)
        sent = last_seq
        while True:
            events = record.investigation.events
            while sent < len(events):
                event = events[sent]
                sent += 1
                yield f"id: {event.seq}\nevent: progress\ndata: {event.model_dump_json()}\n\n"
            status = record.investigation.status
            if status in _TERMINAL and sent >= len(record.investigation.events):
                yield f"event: end\ndata: {json.dumps({'status': status.value})}\n\n"
                return
            waiter = record.changed
            try:
                await asyncio.wait_for(waiter.wait(), timeout=15)
            except TimeoutError:
                yield ": keep-alive\n\n"

    # --- persistence / expiry ---------------------------------------------------------------------------
    def _persist(self, record: _Record) -> None:
        try:
            self._store.mkdir(parents=True, exist_ok=True)
            path = self._store / f"{record.investigation.id}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(record.investigation.model_dump_json(), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            logger.warning("Could not persist investigation %s", record.investigation.id)

    def _load_persisted(self) -> None:
        if not self._store.exists():
            return
        cutoff = utcnow() - timedelta(hours=self._s.result_ttl_hours)
        for file in self._store.glob("*.json"):
            try:
                inv = Investigation.model_validate_json(file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if inv.updated_at < cutoff or inv.status not in _TERMINAL or not is_valid_investigation_id(inv.id):
                self._delete_file(file)
                continue
            self._records[inv.id] = _Record(inv)

    def _purge_expired(self) -> None:
        cutoff = utcnow() - timedelta(hours=self._s.result_ttl_hours)
        finished = sorted(
            (r for r in self._records.values() if r.investigation.status in _TERMINAL),
            key=lambda r: r.investigation.updated_at,
        )
        excess = max(0, len(self._records) - self._s.max_stored_investigations)
        for i, record in enumerate(finished):
            if record.investigation.updated_at < cutoff or i < excess:
                self._records.pop(record.investigation.id, None)
                self._delete_file(self._store / f"{record.investigation.id}.json")

    @staticmethod
    def _delete_file(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    async def shutdown(self) -> None:
        tasks = [r.task for r in self._records.values() if r.task and not r.task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
