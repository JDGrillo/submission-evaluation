from __future__ import annotations

from .agents.analysis import AnalysisAgent
from .agents.ingestion import IngestionAgent
from .agents.report import ReportAgent
from .agents.research import ResearchAgent
from .agents.validation import ValidationAgent
from .agents.orchestrator import OrchestratorAgent


def build_default_orchestrator() -> OrchestratorAgent:
    return OrchestratorAgent(
        ingestion=IngestionAgent(),
        research=ResearchAgent(),
        analysis=AnalysisAgent(),
        report=ReportAgent(),
        validation=ValidationAgent(),
    )
