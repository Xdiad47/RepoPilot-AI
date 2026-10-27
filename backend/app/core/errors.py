"""Application error types. Every error carries a stable machine code and a user-safe message."""

from __future__ import annotations


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class InvalidRepositoryURL(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("invalid_repository_url", message, 422)


class UnsafePathError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("unsafe_path", message, 400)


class RepositoryNotFound(AppError):
    def __init__(self, message: str = "Repository not found, or it is private. Only public GitHub repositories are supported.") -> None:
        super().__init__("repository_not_found", message, 404)


class RepositoryTooLarge(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("repository_too_large", message, 413)


class CloneFailed(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("clone_failed", message, 502)


class GitHubUnavailable(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("github_unavailable", message, 502)


class UnsupportedRepository(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("unsupported_repository", message, 422)


class LLMNotConfigured(AppError):
    def __init__(self) -> None:
        super().__init__(
            "llm_not_configured",
            "The AI provider is not configured on the server (LLM_API_KEY / LLM_BASE_URL / LLM_MODEL).",
            503,
        )


class LLMUnavailable(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("llm_unavailable", message, 502)


class LLMOutputError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("llm_output_invalid", message, 502)


class PatchRejected(AppError):
    def __init__(self, message: str) -> None:
        super().__init__("patch_rejected", message, 422)


class RateLimited(AppError):
    def __init__(self, message: str, retry_after: int = 60) -> None:
        super().__init__("rate_limited", message, 429)
        self.retry_after = retry_after


class InvestigationNotFound(AppError):
    def __init__(self) -> None:
        super().__init__("investigation_not_found", "Investigation not found or it has expired.", 404)
