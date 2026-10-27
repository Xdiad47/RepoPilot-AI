import json
import time

import pytest
from fastapi.testclient import TestClient

from app.api.deps import Container
from app.core.rate_limit import RateLimiter
from app.main import create_app
from app.services.investigation_service import InvestigationManager
from app.services.validation_service import ValidationService

from .conftest import FakeAgent

VALID = {
    "repository_url": "https://github.com/octocat/hello",
    "bug_description": "Submitting an empty email returns a 500 error instead of a validation message.",
}


def make_client(settings, behavior="ok"):
    def factory(s):
        return Container(
            settings=s,
            manager=InvestigationManager(s, lambda: FakeAgent(behavior)),
            rate_limiter=RateLimiter(s),
            validation=ValidationService(s),
        )

    return TestClient(create_app(settings, container_factory=factory))


def wait_done(client, repair_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/repair/{repair_id}").json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.02)
    raise AssertionError("investigation did not finish")


@pytest.fixture
def client(settings):
    with make_client(settings) as c:
        yield c


class TestHealth:
    def test_reports_status_without_secrets(self, client, settings):
        r = client.get("/api/health")
        body = r.json()
        assert r.status_code == 200 and body["status"] == "ok"
        assert body["llm"] == {"configured": True, "model": "test-model", "provider_host": "llm.example.test"}
        assert body["sandbox"]["enabled"] is False and body["sandbox"]["available"] is False
        assert settings.llm_api_key not in r.text and "api_key" not in r.text.lower()
        assert str(settings.workspace_root) not in r.text

    def test_reports_missing_configuration(self, settings):
        with make_client(settings.model_copy(update={"llm_api_key": ""})) as c:
            body = c.get("/api/health").json()
            assert body["llm"]["configured"] is False and body["llm"]["model"] is None


class TestCreateRepair:
    def test_accepts_and_returns_links(self, client):
        r = client.post("/api/repair", json=VALID)
        assert r.status_code == 202
        body = r.json()
        assert body["status"] in ("queued", "running", "completed")
        assert body["status_url"] == f"/api/repair/{body['repair_id']}"
        done = wait_done(client, body["repair_id"])
        assert done["status"] == "completed" and done["result"]["outcome"] == "patch_proposed"

    def test_normalizes_the_repository_url(self, client):
        r = client.post("/api/repair", json={**VALID, "repository_url": "https://github.com/octocat/hello.git/"})
        done = wait_done(client, r.json()["repair_id"])
        assert done["repository_url"] == "https://github.com/octocat/hello"

    @pytest.mark.parametrize(
        "payload,field",
        [
            ({**VALID, "repository_url": "https://gitlab.com/o/r"}, "repository_url"),
            ({**VALID, "repository_url": "git@github.com:o/r.git"}, "repository_url"),
            ({**VALID, "repository_url": ""}, "repository_url"),
            ({**VALID, "bug_description": "short"}, "bug_description"),
            ({**VALID, "bug_description": "x" * 4001}, "bug_description"),
            ({**VALID, "stack_trace": "x" * 8001}, "stack_trace"),
            ({"bug_description": VALID["bug_description"]}, "repository_url"),
        ],
    )
    def test_validation_errors_have_a_consistent_shape(self, client, payload, field):
        r = client.post("/api/repair", json=payload)
        assert r.status_code == 422
        err = r.json()["error"]
        assert err["code"] == "validation_error" and field in err["fields"] and err["message"]

    def test_malformed_json(self, client):
        r = client.post("/api/repair", content=b"{nope", headers={"content-type": "application/json"})
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"

    def test_request_size_limit(self, client):
        r = client.post("/api/repair", content=b"x" * 70_000, headers={"content-type": "application/json"})
        assert r.status_code == 413 and r.json()["error"]["code"] == "request_too_large"

    def test_llm_not_configured(self, settings):
        with make_client(settings.model_copy(update={"llm_api_key": ""})) as c:
            r = c.post("/api/repair", json=VALID)
            assert r.status_code == 503 and r.json()["error"]["code"] == "llm_not_configured"

    def test_rate_limit(self, client, settings):
        for _ in range(settings.rate_limit_per_hour):
            assert client.post("/api/repair", json=VALID).status_code == 202
        r = client.post("/api/repair", json=VALID)
        assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
        assert int(r.headers["retry-after"]) > 0

    def test_invalid_requests_do_not_consume_rate_limit(self, client, settings):
        for _ in range(settings.rate_limit_per_hour + 2):
            assert client.post("/api/repair", json={**VALID, "repository_url": "nope"}).status_code == 422
        assert client.post("/api/repair", json=VALID).status_code == 202


class TestReadEndpoints:
    def test_failed_investigation_reports_error_and_events(self, settings):
        with make_client(settings, "app_error") as c:
            rid = c.post("/api/repair", json=VALID).json()["repair_id"]
            body = wait_done(c, rid)
            assert body["status"] == "failed" and body["error"]["code"] == "unsupported_repository"
            assert body["events"][-1]["status"] == "failed"
            assert c.get(f"/api/repair/{rid}/diff").status_code == 404

    def test_diff_download(self, client):
        rid = client.post("/api/repair", json=VALID).json()["repair_id"]
        wait_done(client, rid)
        r = client.get(f"/api/repair/{rid}/diff")
        assert r.status_code == 200 and r.text.startswith("--- a/x.py")
        assert "attachment" in r.headers["content-disposition"] and "x-diff" in r.headers["content-type"]

    @pytest.mark.parametrize("rid", ["0" * 32, "not-an-id", "..%2F..%2Fetc%2Fpasswd", "A" * 32])
    def test_unknown_ids_are_404_with_json_errors(self, client, rid):
        for suffix in ("", "/diff", "/events"):
            r = client.get(f"/api/repair/{rid}{suffix}")
            assert r.status_code == 404 and r.json()["error"]["code"] in ("investigation_not_found", "not_found")

    def test_events_stream(self, client):
        rid = client.post("/api/repair", json=VALID).json()["repair_id"]
        wait_done(client, rid)
        with client.stream("GET", f"/api/repair/{rid}/events") as r:
            assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
            assert r.headers["x-accel-buffering"] == "no"  # keeps nginx from buffering SSE
            text = "".join(r.iter_text())
        events = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: {") and '"seq"' in line]
        assert events[0]["stage"] == "queued" and events[-1]["stage"] == "finalize"
        assert "event: end" in text

    def test_events_stream_resumes_with_last_event_id(self, client):
        rid = client.post("/api/repair", json=VALID).json()["repair_id"]
        done = wait_done(client, rid)
        with client.stream("GET", f"/api/repair/{rid}/events", headers={"Last-Event-ID": str(len(done["events"]) - 1)}) as r:
            text = "".join(r.iter_text())
        assert text.count("event: progress") == 1

    def test_unknown_route_and_method(self, client):
        assert client.get("/api/nope").json()["error"]["code"] == "not_found"
        assert client.delete("/api/repair").status_code == 405


class TestCors:
    def test_allowed_origin(self, client):
        r = client.options("/api/repair", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
                                                   "Access-Control-Request-Headers": "content-type"})
        assert r.headers["access-control-allow-origin"] == "http://localhost:3000"

    def test_other_origins_get_no_cors_headers(self, client):
        r = client.get("/api/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in r.headers

    def test_multiple_origins_from_env(self, settings):
        s = settings.model_copy(update={"frontend_origin": "https://a.vercel.app, http://localhost:3000/"})
        assert s.allowed_origins == ["https://a.vercel.app", "http://localhost:3000"]
        with make_client(s) as c:
            r = c.get("/api/health", headers={"Origin": "https://a.vercel.app"})
            assert r.headers["access-control-allow-origin"] == "https://a.vercel.app"


class TestRateLimiterUnit:
    def test_window_slides_and_global_cap(self, settings):
        now = [0.0]
        limiter = RateLimiter(settings.model_copy(update={"rate_limit_per_hour": 2, "daily_global_limit": 3}), clock=lambda: now[0])
        limiter.check("a")
        limiter.check("a")
        with pytest.raises(Exception, match="Rate limit"):
            limiter.check("a")
        limiter.check("b")  # different client unaffected, but this is the 3rd global request
        with pytest.raises(Exception, match="daily capacity"):
            limiter.check("c")
        now[0] = 86401
        limiter.check("a")  # both windows have slid

    def test_proxy_header_only_trusted_when_configured(self, settings):
        class Req:
            headers = {"x-real-ip": "9.9.9.9"}

            class client:
                host = "1.1.1.1"

        assert RateLimiter(settings).client_key(Req) == "1.1.1.1"
        assert RateLimiter(settings.model_copy(update={"trust_proxy_headers": True})).client_key(Req) == "9.9.9.9"


class TestProduction:
    def test_docs_are_disabled_in_production(self, settings):
        with make_client(settings.model_copy(update={"environment": "production"})) as c:
            assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404
