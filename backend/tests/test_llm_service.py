import json

import httpx
import pytest

from app.core.errors import LLMNotConfigured, LLMOutputError, LLMUnavailable
from app.schemas.llm import PlanResponse
from app.services import llm_service
from app.services.llm_service import LLMService, extract_json_object

VALID = {"understanding": "u", "hypotheses": [], "search_terms": [], "files_to_inspect": []}


def reply(content, status=200, usage=None):
    body = {"choices": [{"message": {"content": content}}], "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5}}
    return httpx.Response(status, json=body)


def service(settings, handler):
    return LLMService(settings, transport=httpx.MockTransport(handler))


class TestExtractJson:
    def test_plain(self):
        assert extract_json_object('{"a": 1}') == {"a": 1}

    def test_fenced(self):
        assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}

    def test_surrounded_by_prose(self):
        assert extract_json_object('Sure! Here you go: {"a": {"b": "}"}} hope that helps') == {"a": {"b": "}"}}

    @pytest.mark.parametrize("text", ["", "no json here", "[1, 2]", '{"a": 1', "{broken}"])
    def test_invalid(self, text):
        with pytest.raises(ValueError):
            extract_json_object(text)


class TestComplete:
    async def test_valid_reply_is_parsed_and_tokens_counted(self, settings):
        seen = {}

        def handler(request):
            seen["auth"] = request.headers["authorization"]
            seen["body"] = json.loads(request.content)
            return reply(json.dumps(VALID))

        svc = service(settings, handler)
        result = await svc.complete_json("sys", "user", PlanResponse)
        assert result.understanding == "u"
        assert seen["auth"] == f"Bearer {settings.llm_api_key}"
        assert seen["body"]["model"] == "test-model" and seen["body"]["messages"][0]["role"] == "system"
        assert "tools" not in seen["body"]  # the model is never given tools
        assert (svc.calls, svc.prompt_tokens, svc.completion_tokens) == (1, 10, 5)

    async def test_corrective_retry_after_invalid_output(self, settings):
        replies = iter(["not json at all", json.dumps(VALID)])
        svc = service(settings, lambda r: reply(next(replies)))
        assert (await svc.complete_json("s", "u", PlanResponse)).understanding == "u"
        assert svc.calls == 2

    async def test_schema_violation_triggers_retry_then_fails(self, settings):
        svc = service(settings, lambda r: reply(json.dumps({"understanding": 5})))
        with pytest.raises(LLMOutputError):
            await svc.complete_json("s", "u", PlanResponse)
        assert svc.calls == 2

    async def test_oversized_fields_are_rejected(self, settings):
        bad = {**VALID, "understanding": "x" * 5000}
        svc = service(settings, lambda r: reply(json.dumps(bad)))
        with pytest.raises(LLMOutputError):
            await svc.complete_json("s", "u", PlanResponse)

    async def test_not_configured(self, settings):
        unconfigured = settings.model_copy(update={"llm_api_key": ""})
        with pytest.raises(LLMNotConfigured):
            await LLMService(unconfigured).complete_json("s", "u", PlanResponse)

    @pytest.mark.parametrize("status", [401, 403])
    async def test_rejected_key(self, settings, status):
        svc = service(settings, lambda r: httpx.Response(status, text="nope"))
        with pytest.raises(LLMUnavailable, match="API key"):
            await svc.complete_json("s", "u", PlanResponse)

    async def test_rate_limit_is_retried(self, settings, monkeypatch):
        async def no_sleep(_):
            return None

        monkeypatch.setattr(llm_service.asyncio, "sleep", no_sleep)
        responses = iter([httpx.Response(429, headers={"retry-after": "1"}), reply(json.dumps(VALID))])
        svc = service(settings, lambda r: next(responses))
        assert (await svc.complete_json("s", "u", PlanResponse)).understanding == "u"

    async def test_persistent_server_error(self, settings, monkeypatch):
        async def no_sleep(_):
            return None

        monkeypatch.setattr(llm_service.asyncio, "sleep", no_sleep)
        svc = service(settings, lambda r: httpx.Response(503))
        with pytest.raises(LLMUnavailable):
            await svc.complete_json("s", "u", PlanResponse)

    async def test_timeout(self, settings):
        def boom(request):
            raise httpx.ReadTimeout("slow")

        with pytest.raises(LLMUnavailable, match="timed out"):
            await service(settings, boom).complete_json("s", "u", PlanResponse)

    async def test_json_mode_fallback(self, settings):
        calls = []

        def handler(request):
            body = json.loads(request.content)
            calls.append("response_format" in body)
            if "response_format" in body:
                return httpx.Response(400, text="response_format is not supported")
            return reply(json.dumps(VALID))

        await service(settings, handler).complete_json("s", "u", PlanResponse)
        assert calls == [True, False]

    async def test_unexpected_provider_shape(self, settings):
        svc = service(settings, lambda r: httpx.Response(200, json={"weird": True}))
        with pytest.raises(LLMOutputError):
            await svc.complete_json("s", "u", PlanResponse)

    async def test_api_key_never_appears_in_errors(self, settings, monkeypatch):
        async def no_sleep(_):
            return None

        monkeypatch.setattr(llm_service.asyncio, "sleep", no_sleep)
        svc = service(settings, lambda r: httpx.Response(500, text=f"echo {settings.llm_api_key}"))
        try:
            await svc.complete_json("s", "u", PlanResponse)
        except LLMUnavailable as exc:
            assert settings.llm_api_key not in exc.message


class TestRateLimitHandling:
    @pytest.mark.parametrize("raw,expected", [("2", 2), ("3.5s", 3.5), ("1m3.2s", 63.2), ("250ms", 0.25), ("1h2m", 3720), ("garbage", 0), ("", 0)])
    def test_parse_duration(self, raw, expected):
        assert llm_service._parse_duration(raw) == pytest.approx(expected)

    async def test_waits_for_the_provider_token_bucket_reset(self, settings, monkeypatch):
        slept = []

        async def fake_sleep(seconds):
            slept.append(seconds)

        monkeypatch.setattr(llm_service.asyncio, "sleep", fake_sleep)
        responses = iter([httpx.Response(429, headers={"x-ratelimit-reset-tokens": "7.2s"}), reply(json.dumps(VALID))])
        await service(settings, lambda r: next(responses)).complete_json("s", "u", PlanResponse)
        assert slept == [pytest.approx(7.7)]

    async def test_retry_delay_is_capped(self, settings, monkeypatch):
        slept = []

        async def fake_sleep(seconds):
            slept.append(seconds)

        monkeypatch.setattr(llm_service.asyncio, "sleep", fake_sleep)
        responses = iter([httpx.Response(429, headers={"retry-after": "900"}), reply(json.dumps(VALID))])
        await service(settings, lambda r: next(responses)).complete_json("s", "u", PlanResponse)
        assert slept == [llm_service.MAX_RETRY_DELAY]


class TestRequestShape:
    async def test_output_tokens_are_capped_by_step_and_by_config(self, settings):
        seen = []
        svc = service(settings, lambda r: (seen.append(json.loads(r.content)["max_tokens"]), reply(json.dumps(VALID)))[1])
        await svc.complete_json("s", "u", PlanResponse, max_tokens=900)
        await svc.complete_json("s", "u", PlanResponse, max_tokens=999_999)
        assert seen == [900, settings.llm_max_output_tokens]

    async def test_reasoning_effort_only_sent_when_configured_and_dropped_if_rejected(self, settings):
        bodies = []

        def handler(request):
            body = json.loads(request.content)
            bodies.append(body)
            if "reasoning_effort" in body:
                return httpx.Response(400, text="unknown parameter: reasoning_effort")
            return reply(json.dumps(VALID))

        await service(settings, handler).complete_json("s", "u", PlanResponse)
        assert "reasoning_effort" not in bodies[0]
        bodies.clear()
        configured = settings.model_copy(update={"llm_reasoning_effort": "low"})
        await service(configured, handler).complete_json("s", "u", PlanResponse)
        assert bodies[0]["reasoning_effort"] == "low" and "reasoning_effort" not in bodies[1]
