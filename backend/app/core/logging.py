"""Logging setup with secret redaction. Request bodies and prompts are never logged."""

from __future__ import annotations

import logging
import re

_PATTERNS = [
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{16,}"),
]


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: list[str] | None = None) -> None:
        super().__init__()
        self._secrets = [s for s in (secrets or []) if s and len(s) >= 8]

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = message
        for secret in self._secrets:
            redacted = redacted.replace(secret, "[REDACTED]")
        for pattern in _PATTERNS:
            redacted = pattern.sub(lambda m: (m.group(1) if m.lastindex else "") + "[REDACTED]", redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging(secrets: list[str] | None = None, level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if not any(getattr(h, "_repopilot", False) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler._repopilot = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    root.setLevel(level)
    redactor = RedactingFilter(secrets)
    for handler in root.handlers:
        handler.addFilter(redactor)
    # httpx logs full request URLs at INFO; keep it quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)
