"""Web research through Tavily: official documentation, known issues and discussions about the reported bug.

Only a short search query leaves the server (derived from the bug report, with anything that looks like a secret
masked). Repository source code is never sent. Results are untrusted text: they are length-limited, de-duplicated,
ranked by source credibility and later shown to the model inside a tag that it is told not to obey.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.core.logging import redact
from app.schemas.models import ResearchSource

logger = logging.getLogger(__name__)

MAX_QUERY_CHARS = 200
MAX_SNIPPET_CHARS = 300
MAX_TITLE_CHARS = 140
MAX_SOURCES = 8

# Hosts whose content is the primary documentation of a language, framework or platform.
OFFICIAL_DOMAINS = {
    "python.org", "docs.python.org", "docs.pytest.org", "pytest.org", "djangoproject.com", "fastapi.tiangolo.com",
    "palletsprojects.com", "pydantic.dev", "sqlalchemy.org", "numpy.org", "pandas.pydata.org", "pytorch.org",
    "developer.mozilla.org", "nodejs.org", "react.dev", "nextjs.org", "vuejs.org", "angular.dev", "angular.io",
    "svelte.dev", "typescriptlang.org", "expressjs.com", "npmjs.com", "vitejs.dev", "jestjs.io", "vitest.dev",
    "kotlinlang.org", "developer.android.com", "android.com", "developer.apple.com", "swift.org", "flutter.dev",
    "dart.dev", "pub.dev", "api.flutter.dev", "go.dev", "pkg.go.dev", "rust-lang.org", "docs.rs", "crates.io",
    "learn.microsoft.com", "docs.microsoft.com", "dotnet.microsoft.com", "docs.oracle.com", "openjdk.org",
    "spring.io", "gradle.org", "maven.apache.org", "junit.org", "php.net", "laravel.com", "symfony.com",
    "ruby-lang.org", "ruby-doc.org", "rubyonrails.org", "cppreference.com", "isocpp.org", "gcc.gnu.org",
    "llvm.org", "cmake.org", "docs.docker.com", "kubernetes.io", "postgresql.org", "mysql.com", "sqlite.org",
}
COMMUNITY_DOMAINS = {
    "stackoverflow.com", "stackexchange.com", "serverfault.com", "superuser.com", "github.com", "gitlab.com",
    "discuss.python.org", "discourse.org", "dev.to", "reddit.com", "hashnode.dev",
}
# Where to look first for each language / framework: used for one extra search restricted to these sites.
DOCS_BY_LANGUAGE = {
    "Python": ["docs.python.org"], "JavaScript": ["developer.mozilla.org", "nodejs.org"],
    "TypeScript": ["typescriptlang.org", "developer.mozilla.org"], "Java": ["docs.oracle.com", "docs.spring.io"],
    "Kotlin": ["kotlinlang.org", "developer.android.com"], "Swift": ["developer.apple.com", "swift.org"],
    "Objective-C": ["developer.apple.com"], "Dart": ["dart.dev", "api.flutter.dev"], "Go": ["go.dev", "pkg.go.dev"],
    "Rust": ["doc.rust-lang.org", "docs.rs"], "C#": ["learn.microsoft.com"], "C++": ["cppreference.com"],
    "C": ["cppreference.com"], "PHP": ["php.net"], "Ruby": ["ruby-doc.org", "ruby-lang.org"], "Scala": ["docs.scala-lang.org"],
}
DOCS_BY_FRAMEWORK = {
    "Flutter": ["docs.flutter.dev", "api.flutter.dev"], "Next.js": ["nextjs.org"], "React": ["react.dev"],
    "React Native": ["reactnative.dev"], "Vue": ["vuejs.org"], "Angular": ["angular.dev"], "Svelte": ["svelte.dev"],
    "Express": ["expressjs.com"], "NestJS": ["docs.nestjs.com"], "Django": ["docs.djangoproject.com"],
    "FastAPI": ["fastapi.tiangolo.com"], "Flask": ["flask.palletsprojects.com"], "Android": ["developer.android.com"],
    "Jetpack Compose": ["developer.android.com"], "SwiftUI": ["developer.apple.com"], "UIKit": ["developer.apple.com"],
    "Spring Boot": ["docs.spring.io"], "Laravel": ["laravel.com"], "Ruby on Rails": ["guides.rubyonrails.org"],
    "ASP.NET Core": ["learn.microsoft.com"], "Gradle": ["docs.gradle.org"], "Tokio": ["docs.rs"],
}
_KIND_RANK = {"official": 0, "community": 1, "other": 2}
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_WS = re.compile(r"\s+")


@dataclass
class ResearchOutcome:
    status: str  # "completed" | "unavailable" | "skipped"
    queries: list[str] = field(default_factory=list)
    sources: list[ResearchSource] = field(default_factory=list)
    note: str = ""
    per_query: dict[str, int] = field(default_factory=dict)  # real result count per query, for progress events


def _host_matches(host: str, domains: set[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def classify_source(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if not host:
        return "other"
    if _host_matches(host, OFFICIAL_DOMAINS) or host.startswith(("docs.", "developer.", "developers.", "devdocs.")):
        return "official"
    if _host_matches(host, COMMUNITY_DOMAINS):
        return "community"
    return "other"


# Languages a framework is written in, so a Flutter project's docs are not searched for a bug in its Go service.
FRAMEWORK_LANGUAGES = {
    "Flutter": {"Dart"}, "Next.js": {"JavaScript", "TypeScript"}, "React": {"JavaScript", "TypeScript"},
    "React Native": {"JavaScript", "TypeScript"}, "Vue": {"JavaScript", "TypeScript", "Vue"}, "Angular": {"TypeScript"},
    "Svelte": {"JavaScript", "TypeScript", "Svelte"}, "Express": {"JavaScript", "TypeScript"}, "NestJS": {"TypeScript"},
    "Django": {"Python"}, "FastAPI": {"Python"}, "Flask": {"Python"}, "Android": {"Kotlin", "Java"},
    "Jetpack Compose": {"Kotlin"}, "SwiftUI": {"Swift"}, "UIKit": {"Swift", "Objective-C"}, "Spring Boot": {"Java", "Kotlin"},
    "Laravel": {"PHP"}, "Ruby on Rails": {"Ruby"}, "ASP.NET Core": {"C#"}, "Gradle": {"Kotlin", "Java"}, "Tokio": {"Rust"},
}


def relevant_frameworks(languages: list[str], frameworks: list[str]) -> list[str]:
    """Frameworks that belong to the languages being investigated (all of them when the stack is unknown)."""
    wanted = set(languages)
    return [f for f in frameworks if not wanted or f not in FRAMEWORK_LANGUAGES or FRAMEWORK_LANGUAGES[f] & wanted]


def official_domains(languages: list[str] | str | None, frameworks: list[str], limit: int = 6) -> list[str]:
    """Documentation sites for the investigated stack, most specific (framework) first."""
    langs = [languages] if isinstance(languages, str) else [lang for lang in (languages or []) if lang]
    out: list[str] = []
    names = [(f, DOCS_BY_FRAMEWORK) for f in relevant_frameworks(langs, frameworks)] + [(lang, DOCS_BY_LANGUAGE) for lang in langs]
    for name, table in names:
        for domain in table.get(name, []):
            if domain not in out:
                out.append(domain)
    return out[:limit]


def clean_text(text: object, limit: int) -> str:
    value = _WS.sub(" ", _CONTROL.sub(" ", str(text or ""))).strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def sanitize_queries(candidates: list[str], limit: int) -> list[str]:
    """Search queries safe to send to a third party: single-line, masked, bounded and unique."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        if not isinstance(raw, str):
            continue
        query = clean_text(redact(raw), MAX_QUERY_CHARS)
        query = re.sub(r"https?://\S+", "", query).strip()  # no URLs: they may carry tokens or private hosts
        key = query.lower()
        if len(query) < 6 or key in seen:
            continue
        seen.add(key)
        out.append(query)
        if len(out) >= limit:
            break
    return out


_ERROR_LINE = re.compile(r"^\s*(?:[\w.$]*(?:Error|Exception|Panic|Fault)\b.*|panic:.*|fatal error:.*|error(?:\[\w+\])?:.*)$", re.I)


def fallback_queries(bug: str, trace: str | None, language: str | None, frameworks: list[str]) -> list[str]:
    """Deterministic queries used when the model proposed none: the error message plus the detected stack."""
    stack = " ".join([*frameworks[:1], language or ""]).strip()
    lines = [ln.strip() for ln in (trace or "").splitlines() if _ERROR_LINE.match(ln)]
    first_sentence = re.split(r"(?<=[.!?])\s", bug.strip(), maxsplit=1)[0]
    candidates = []
    if lines:
        candidates.append(f"{stack} {lines[-1]}")
    candidates.append(f"{stack} {first_sentence}")
    return [c.strip() for c in candidates if c.strip()]


class ResearchService:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._s = settings
        self._transport = transport

    @property
    def configured(self) -> bool:
        return self._s.research_configured

    async def search(self, queries: list[str], docs_domains: list[str] | None = None) -> ResearchOutcome:
        """Run the queries concurrently. Never raises: any failure becomes an honest ``unavailable`` outcome.

        When ``docs_domains`` is given, the first query is searched once more restricted to those official sites, so
        documentation is found even when general results are dominated by forums and blogs.
        """
        queries = sanitize_queries(queries, self._s.research_max_queries)
        if not self.configured:
            return ResearchOutcome("skipped", queries, note="Web research is not configured on this server (no Tavily API key).")
        if not queries:
            return ResearchOutcome("skipped", [], note="No usable search query could be derived from the bug report.")

        jobs: list[tuple[str, str, list[str] | None]] = [(q, q, None) for q in queries]
        if docs_domains and self._s.research_official_pass:
            jobs.append((f"{queries[0]} [official docs only]", queries[0], docs_domains))

        async with httpx.AsyncClient(
            timeout=self._s.research_timeout_seconds, transport=self._transport, follow_redirects=False,
            headers={"Authorization": f"Bearer {self._s.tavily_api_key}", "Content-Type": "application/json"},
        ) as client:
            results = await asyncio.gather(*(self._one(client, q, d) for _, q, d in jobs), return_exceptions=True)

        sources: list[tuple[str, dict]] = []
        per_query: dict[str, int] = {}
        failures: list[str] = []
        for (label, query, _), result in zip(jobs, results, strict=True):
            if isinstance(result, _ResearchFailure):
                failures.append(str(result))
                continue
            if isinstance(result, BaseException):
                logger.warning("Tavily query failed unexpectedly: %s", type(result).__name__)
                failures.append("the search service returned an unexpected error")
                continue
            per_query[label] = len(result)
            sources.extend((query, item) for item in result)

        if not sources:
            reason = failures[0] if failures else "the search returned no results"
            return ResearchOutcome("unavailable", queries, note=f"Web research found nothing usable: {reason}.", per_query=per_query)
        return ResearchOutcome("completed", queries, self._rank(sources), per_query=per_query)

    async def _one(self, client: httpx.AsyncClient, query: str, domains: list[str] | None = None) -> list[dict]:
        body: dict = {
            "query": query,
            "search_depth": "basic",
            "max_results": self._s.research_results_per_query,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }
        if domains:
            body["include_domains"] = domains
        try:
            response = await client.post(f"{self._s.tavily_base_url}/search", json=body)
        except httpx.TimeoutException:
            raise _ResearchFailure("the search service timed out") from None
        except httpx.HTTPError:
            raise _ResearchFailure("the search service could not be reached") from None
        if response.status_code in (401, 403):
            raise _ResearchFailure("the Tavily API key was rejected")
        if response.status_code in (429, 432, 433):
            raise _ResearchFailure("the Tavily usage limit was reached")
        if response.status_code >= 400:
            raise _ResearchFailure(f"the search service answered HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise _ResearchFailure("the search service returned an unreadable response") from None
        items = data.get("results") if isinstance(data, dict) else None
        return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []

    @staticmethod
    def _rank(found: list[tuple[str, dict]]) -> list[ResearchSource]:
        """De-duplicate by URL, drop non-web links, then order official docs first, community next, the rest last."""
        unique: dict[str, tuple[str, dict]] = {}
        for query, item in found:
            url = str(item.get("url") or "").strip()
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                continue
            key = f"{parsed.hostname}{parsed.path}".rstrip("/").lower() + (f"?{parsed.query}" if parsed.query else "")
            unique.setdefault(key, (query, {**item, "url": url}))

        def score(item: dict) -> float:
            try:
                return float(item.get("score") or 0)
            except (TypeError, ValueError):
                return 0.0

        entries = []
        for query, item in unique.values():
            kind = classify_source(item["url"])
            entries.append((_KIND_RANK[kind], -score(item), kind, query, item))
        entries.sort(key=lambda e: (e[0], e[1]))

        out: list[ResearchSource] = []
        for number, (_, _, kind, query, item) in enumerate(entries[:MAX_SOURCES], 1):
            url = item["url"]
            host = (urlparse(url).hostname or "").removeprefix("www.")
            out.append(ResearchSource(
                id=f"R{number}", title=clean_text(item.get("title"), MAX_TITLE_CHARS) or host, url=url, domain=host,
                snippet=clean_text(item.get("content"), MAX_SNIPPET_CHARS), kind=kind,  # type: ignore[arg-type]
                query=query, score=round(score(item), 3) if item.get("score") is not None else None,
            ))
        return out


class _ResearchFailure(Exception):
    """A search problem whose message is safe to show to the user (never contains the key)."""
