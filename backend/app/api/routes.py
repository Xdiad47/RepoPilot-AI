"""HTTP routes. Thin: validation and orchestration live in services."""

from __future__ import annotations

from fastapi import APIRouter, Header, Request
from fastapi.responses import PlainTextResponse, StreamingResponse

from app.api.deps import Container
from app.schemas.models import Investigation, RepairAccepted, RepairRequest

router = APIRouter(prefix="/api")

VERSION = "1.0.0"


def container(request: Request) -> Container:
    return request.app.state.container


@router.get("/health")
async def health(request: Request) -> dict:
    c = container(request)
    s = c.settings
    sandbox = await c.validation.runner.status()
    return {
        "status": "ok",
        "version": VERSION,
        "environment": s.environment,
        "llm": {
            "configured": s.llm_configured,
            "model": s.llm_model if s.llm_configured else None,
            "provider_host": _host(s.llm_base_url) if s.llm_configured else None,
        },
        "research": {"configured": s.research_configured, "provider": "Tavily" if s.research_configured else None},
        "sandbox": {"enabled": sandbox.enabled, "available": sandbox.available, "detail": sandbox.reason},
        "github_token_configured": bool(s.github_token),
        "limits": {
            "max_repository_size_mb": s.max_repository_size_mb,
            "max_source_files": s.max_source_files,
            "max_repair_iterations": s.max_repair_iterations,
            "test_timeout_seconds": s.test_timeout_seconds,
            "rate_limit_per_hour": s.rate_limit_per_hour,
            "max_concurrent_investigations": s.max_concurrent_investigations,
        },
    }


@router.post("/repair", response_model=RepairAccepted, status_code=202)
async def create_repair(body: RepairRequest, request: Request) -> RepairAccepted:
    c = container(request)
    c.rate_limiter.check(c.rate_limiter.client_key(request))
    investigation = c.manager.submit(body)
    return RepairAccepted(
        repair_id=investigation.id,
        status=investigation.status,
        status_url=f"/api/repair/{investigation.id}",
        events_url=f"/api/repair/{investigation.id}/events",
    )


@router.get("/repair/{repair_id}", response_model=Investigation)
async def get_repair(repair_id: str, request: Request) -> Investigation:
    return container(request).manager.get(repair_id)


@router.get("/repair/{repair_id}/diff", response_class=PlainTextResponse)
async def get_diff(repair_id: str, request: Request) -> PlainTextResponse:
    diff = container(request).manager.diff(repair_id)
    return PlainTextResponse(
        diff,
        media_type="text/x-diff; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="repopilot-{repair_id[:8]}.patch"'},
    )


@router.get("/repair/{repair_id}/events")
async def stream_events(
    repair_id: str, request: Request, last_event_id: str | None = Header(default=None)
) -> StreamingResponse:
    manager = container(request).manager
    manager.get(repair_id)  # 404 before the stream starts
    try:
        last_seq = max(0, int(last_event_id)) if last_event_id else 0
    except ValueError:
        last_seq = 0
    return StreamingResponse(
        manager.stream(repair_id, last_seq),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


def _host(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).hostname or ""
