"""Dependency container: builds the services once and wires them together."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.core.rate_limit import RateLimiter
from app.services.investigation_service import InvestigationManager
from app.services.llm_service import LLMService
from app.services.patch_service import PatchService
from app.services.repair_agent import RepairAgent
from app.services.repository_analyzer import RepositoryAnalyzer
from app.services.repository_service import RepositoryService
from app.services.research_service import ResearchService
from app.services.validation_service import ValidationService


@dataclass
class Container:
    settings: Settings
    manager: InvestigationManager
    rate_limiter: RateLimiter
    validation: ValidationService


def build_container(settings: Settings) -> Container:
    repos = RepositoryService(settings)
    analyzer = RepositoryAnalyzer()
    patches = PatchService(settings)
    validation = ValidationService(settings)
    research = ResearchService(settings)

    def agent_factory() -> RepairAgent:
        # A fresh LLMService per investigation keeps token accounting per-investigation.
        return RepairAgent(settings, LLMService(settings), repos, analyzer, patches, validation, research)

    return Container(
        settings=settings,
        manager=InvestigationManager(settings, agent_factory),
        rate_limiter=RateLimiter(settings),
        validation=validation,
    )
