"""Provider-agnostic LLM client for any OpenAI-compatible /chat/completions endpoint (Groq, OpenAI, vLLM, ...).

Switching providers only requires LLM_BASE_URL / LLM_MODEL / LLM_API_KEY. The model never gets tools:
it returns JSON which we validate against a pydantic schema before using any of it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.errors import LLMNotConfigured, LLMOutputError, LLMUnavailable

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def extract_json_object(text: str) -> dict:
    """Parse the first JSON object in a model reply, tolerating code fences and surrounding prose."""
    cleaned = _FENCE.sub("", (text or "").strip()).strip()
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    if start == -1:
        raise ValueError("no JSON object found in the reply")
    depth, in_str, escape = 0, False, False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                value = json.loads(cleaned[start : i + 1])
                if isinstance(value, dict):
                    return value
                break
    raise ValueError("the reply did not contain a complete JSON object")


class LLMService:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._s = settings
        self._transport = transport
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.calls = 0

    @property
    def configured(self) -> bool:
        return self._s.llm_configured

    @property
    def model(self) -> str:
        return self._s.llm_model

    async def complete_json(self, system: str, user: str, schema: type[T], *, max_tokens: int | None = None) -> T:
        """Ask for a JSON object, validate it against ``schema``; one corrective retry on invalid output."""
        if not self.configured:
            raise LLMNotConfigured()
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last_problem = ""
        for attempt in range(2):
            reply = await self._chat(messages, max_tokens or self._s.llm_max_output_tokens)
            try:
                return schema.model_validate(extract_json_object(reply))
            except (ValueError, ValidationError) as exc:
                last_problem = _summarize_error(exc)
                logger.warning("LLM output failed validation (attempt %d): %s", attempt + 1, last_problem)
                messages += [
                    {"role": "assistant", "content": reply[:6000]},
                    {
                        "role": "user",
                        "content": "Your previous reply was not valid. Problem: "
                        f"{last_problem}\nReturn ONLY one corrected JSON object that matches the required schema.",
                    },
                ]
        raise LLMOutputError(f"The AI returned an invalid response twice ({last_problem}). Please try again.")

    async def _chat(self, messages: list[dict[str, str]], max_tokens: int) -> str:
        url = f"{self._s.llm_base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._s.llm_api_key}", "Content-Type": "application/json"}
        body: dict = {
            "model": self._s.llm_model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": min(max_tokens, self._s.llm_max_output_tokens),
            "response_format": {"type": "json_object"},
        }
        if self._s.llm_reasoning_effort:
            body["reasoning_effort"] = self._s.llm_reasoning_effort
        timeout = httpx.Timeout(self._s.llm_timeout_seconds, connect=10)
        attempts = 4
        async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
            for attempt in range(attempts):
                try:
                    response = await client.post(url, headers=headers, json=body)
                except httpx.TimeoutException:
                    raise LLMUnavailable("The AI provider timed out. Please try again.") from None
                except httpx.HTTPError:
                    raise LLMUnavailable("Could not reach the AI provider.") from None

                if response.status_code == 400:
                    # Optional features some providers reject: drop them once and retry rather than fail.
                    dropped = next((k for k in ("response_format", "reasoning_effort") if k in body and k in response.text), None)
                    if dropped:
                        body.pop(dropped)
                        continue
                if response.status_code in (401, 403):
                    raise LLMUnavailable("The AI provider rejected the server's API key (invalid or expired).")
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < attempts - 1:
                        delay = _retry_delay(response) or 2 * (attempt + 1)
                        logger.info("LLM provider returned %s; retrying in %.1fs", response.status_code, delay)
                        await asyncio.sleep(min(delay, MAX_RETRY_DELAY))
                        continue
                    raise LLMUnavailable("The AI provider is rate limiting or unavailable. Please try again shortly.")
                if response.status_code != 200:
                    logger.warning("LLM provider returned %s: %s", response.status_code, response.text[:300])
                    raise LLMUnavailable(f"The AI provider returned an error ({response.status_code}).")
                break
            else:  # pragma: no cover - loop always breaks or raises
                raise LLMUnavailable("The AI provider did not return a usable response.")

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError, TypeError):
            raise LLMOutputError("The AI provider returned an unexpected response format.") from None
        usage = data.get("usage") or {}
        self.calls += 1
        self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.completion_tokens += int(usage.get("completion_tokens") or 0)
        return content or ""


MAX_RETRY_DELAY = 45.0
_DURATION = re.compile(r"^(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?$")


def _parse_duration(value: str) -> float:
    """Parse '2', '3.5s', '1m3.2s' or '250ms' into seconds (0 when unparseable)."""
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        pass
    m = _DURATION.match(value)
    if not m or not any(m.groups()):
        return 0
    h, mins, s, ms = (float(g) if g else 0.0 for g in m.groups())
    return h * 3600 + mins * 60 + s + ms / 1000


def _retry_delay(response: httpx.Response) -> float:
    """How long the provider asks us to wait: Retry-After, or the token-bucket reset time (+ a small margin)."""
    candidates = [response.headers.get("retry-after", ""), response.headers.get("x-ratelimit-reset-tokens", "")]
    waits = [_parse_duration(c) for c in candidates if c]
    return (max(waits) + 0.5) if waits and max(waits) > 0 else 0


def _summarize_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]]
        return "; ".join(parts)
    return str(exc)[:300]
