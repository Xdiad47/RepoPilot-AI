import asyncio
import json
from datetime import timedelta

import pytest

from app.core.errors import InvestigationNotFound, LLMNotConfigured
from app.schemas.models import InvestigationStatus, RepairRequest, utcnow
from app.services.investigation_service import InvestigationManager

from .conftest import FakeAgent

REQUEST = RepairRequest(repository_url="https://github.com/o/r", bug_description="something is broken in the thing")


def manager_with(settings, agents):
    queue = list(agents)
    return InvestigationManager(settings, lambda: queue.pop(0) if len(queue) > 1 else queue[0])


async def finish(manager, inv):
    await manager._records[inv.id].task


class TestLifecycle:
    async def test_success_and_workspace_cleanup(self, settings):
        agent = FakeAgent()
        m = manager_with(settings, [agent])
        inv = m.submit(REQUEST)
        assert inv.status == InvestigationStatus.QUEUED and len(inv.id) == 32
        await finish(m, inv)
        done = m.get(inv.id)
        assert done.status == InvestigationStatus.COMPLETED and done.result.outcome == "patch_proposed"
        assert agent.seen_workspace_exists is True
        assert not (settings.workspace_root / inv.id).exists()
        assert [e.seq for e in done.events] == list(range(1, len(done.events) + 1))

    async def test_expected_errors_surface_their_message(self, settings):
        m = manager_with(settings, [FakeAgent("app_error")])
        inv = m.submit(REQUEST)
        await finish(m, inv)
        done = m.get(inv.id)
        assert done.status == InvestigationStatus.FAILED
        assert done.error.code == "unsupported_repository" and "Go" in done.error.message
        assert not (settings.workspace_root / inv.id).exists()

    async def test_unexpected_errors_do_not_leak_internals(self, settings):
        m = manager_with(settings, [FakeAgent("crash")])
        inv = m.submit(REQUEST)
        await finish(m, inv)
        done = m.get(inv.id)
        assert done.error.code == "internal_error"
        assert "secret" not in done.error.message and "/root" not in done.model_dump_json()
        assert not (settings.workspace_root / inv.id).exists()

    async def test_timeout(self, settings):
        s = settings.model_copy(update={"investigation_timeout_seconds": 1})
        object.__setattr__(s, "investigation_timeout_seconds", 0.2)
        m = manager_with(s, [FakeAgent("hang")])
        inv = m.submit(REQUEST)
        await finish(m, inv)
        done = m.get(inv.id)
        assert done.status == InvestigationStatus.FAILED and done.error.code == "timeout"
        assert not (s.workspace_root / inv.id).exists()

    async def test_llm_must_be_configured(self, settings):
        m = manager_with(settings.model_copy(update={"llm_api_key": ""}), [FakeAgent()])
        with pytest.raises(LLMNotConfigured):
            m.submit(REQUEST)

    async def test_partial_results_survive_a_failure(self, settings):
        class Partial(FakeAgent):
            async def run(self, request, workspace, progress):
                from app.schemas.models import RepositoryInfo
                progress.set_repository(RepositoryInfo(url="u", owner="o", name="r", primary_language="Go"))
                raise RuntimeError("boom")

        m = manager_with(settings, [Partial()])
        inv = m.submit(REQUEST)
        await finish(m, inv)
        done = m.get(inv.id)
        assert done.status == InvestigationStatus.FAILED and done.repository.primary_language == "Go"


class TestQueueing:
    async def test_second_investigation_waits_for_the_first(self, settings):
        gate = asyncio.Event()
        first, second = FakeAgent(gate=gate), FakeAgent()
        m = manager_with(settings, [first, second])
        a, b = m.submit(REQUEST), m.submit(REQUEST)
        await asyncio.sleep(0.05)
        assert m.get(a.id).status == InvestigationStatus.RUNNING
        assert m.get(b.id).status == InvestigationStatus.QUEUED
        assert "queued" in m.get(b.id).events[0].message
        assert second.seen_workspace_exists is None  # has not started
        gate.set()
        await finish(m, a)
        await finish(m, b)
        assert m.get(b.id).status == InvestigationStatus.COMPLETED

    async def test_each_investigation_has_its_own_workspace(self, settings):
        a, b = FakeAgent(), FakeAgent()
        m = manager_with(settings, [a, b])
        i1, i2 = m.submit(REQUEST), m.submit(REQUEST)
        await finish(m, i1)
        await finish(m, i2)
        assert i1.id != i2.id


class TestAccess:
    async def test_unknown_and_malformed_ids(self, settings):
        m = manager_with(settings, [FakeAgent()])
        for bad in ["0" * 32, "../../etc/passwd", "short", "", "G" * 32]:
            with pytest.raises(InvestigationNotFound):
                m.get(bad)

    async def test_diff_only_exists_with_a_patch(self, settings):
        m = manager_with(settings, [FakeAgent(), FakeAgent("app_error")])
        ok, bad = m.submit(REQUEST), m.submit(REQUEST)
        await finish(m, ok)
        await finish(m, bad)
        assert m.diff(ok.id).startswith("--- a/x.py")
        with pytest.raises(Exception) as exc:
            m.diff(bad.id)
        assert getattr(exc.value, "code", "") == "no_patch"


class TestStreaming:
    async def collect(self, m, inv_id, last=0):
        return [chunk async for chunk in m.stream(inv_id, last)]

    async def test_replays_then_ends(self, settings):
        m = manager_with(settings, [FakeAgent()])
        inv = m.submit(REQUEST)
        await finish(m, inv)
        chunks = await self.collect(m, inv.id)
        progress = [json.loads(c.split("data: ")[1]) for c in chunks if "event: progress" in c]
        assert [e["seq"] for e in progress] == list(range(1, len(progress) + 1))
        assert chunks[-1].startswith("event: end") and '"completed"' in chunks[-1]

    async def test_resume_from_last_event_id(self, settings):
        m = manager_with(settings, [FakeAgent()])
        inv = m.submit(REQUEST)
        await finish(m, inv)
        total = len(m.get(inv.id).events)
        chunks = await self.collect(m, inv.id, last=total - 1)
        assert sum("event: progress" in c for c in chunks) == 1

    async def test_follows_live_events(self, settings):
        gate = asyncio.Event()
        m = manager_with(settings, [FakeAgent(gate=gate)])
        inv = m.submit(REQUEST)
        task = asyncio.create_task(self.collect(m, inv.id))
        await asyncio.sleep(0.05)
        assert not task.done()
        gate.set()
        chunks = await asyncio.wait_for(task, 5)
        assert "Done" in "".join(chunks) and chunks[-1].startswith("event: end")


class TestPersistence:
    async def test_results_survive_a_restart(self, settings):
        m = manager_with(settings, [FakeAgent()])
        inv = m.submit(REQUEST)
        await finish(m, inv)
        reloaded = manager_with(settings, [FakeAgent()])
        again = reloaded.get(inv.id)
        assert again.status == InvestigationStatus.COMPLETED and again.result.root_cause == "root cause"

    async def test_expired_results_are_purged(self, settings):
        m = manager_with(settings, [FakeAgent()])
        inv = m.submit(REQUEST)
        await finish(m, inv)
        m._records[inv.id].investigation.updated_at = utcnow() - timedelta(hours=settings.result_ttl_hours + 1)
        m.submit(REQUEST)  # triggers purge
        with pytest.raises(InvestigationNotFound):
            m.get(inv.id)
        assert not (settings.data_dir / "investigations" / f"{inv.id}.json").exists()

    async def test_unfinished_records_are_not_resurrected(self, settings):
        store = settings.data_dir / "investigations"
        store.mkdir(parents=True)
        m = manager_with(settings, [FakeAgent()])
        inv = m.submit(REQUEST)
        await finish(m, inv)
        path = store / f"{inv.id}.json"
        data = json.loads(path.read_text())
        data["status"] = "running"
        path.write_text(json.dumps(data))
        with pytest.raises(InvestigationNotFound):
            manager_with(settings, [FakeAgent()]).get(inv.id)

    async def test_corrupt_files_are_ignored(self, settings):
        store = settings.data_dir / "investigations"
        store.mkdir(parents=True)
        (store / "garbage.json").write_text("{not json")
        manager_with(settings, [FakeAgent()])  # must not raise
