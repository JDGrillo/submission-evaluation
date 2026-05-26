from __future__ import annotations

from dataclasses import dataclass
import importlib
import os
from typing import Any, Dict, List


@dataclass(frozen=True)
class RuntimeStatus:
    foundry_sdk_available: bool
    foundry_initialized: bool
    detail: str


class AgentFrameworkRuntime:
    """Small registry to model Agent Framework-like discoverability and invocation."""

    def __init__(self) -> None:
        self._agents: Dict[str, Any] = {}

    def register(self, name: str, agent: Any) -> None:
        self._agents[name] = agent

    def discover_agents(self) -> List[str]:
        return sorted(self._agents.keys())

    def invoke(self, name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if name not in self._agents:
            raise KeyError(f"Unknown agent: {name}")
        result = self._agents[name].invoke(payload)
        if hasattr(result, "to_dict"):
            return result.to_dict()
        if isinstance(result, dict):
            return result
        return {"status": "unknown", "result": str(result)}


def _resolve_ai_project_client() -> Any | None:
    try:
        module = importlib.import_module("azure.ai.projects")
    except ModuleNotFoundError:
        return None
    return getattr(module, "AIProjectClient", None)


def _resolve_azure_key_credential() -> Any | None:
    try:
        module = importlib.import_module("azure.core.credentials")
    except ModuleNotFoundError:
        return None
    return getattr(module, "AzureKeyCredential", None)


def initialize_foundry_runtime() -> RuntimeStatus:
    ai_project_client = _resolve_ai_project_client()
    if ai_project_client is None:
        return RuntimeStatus(
            foundry_sdk_available=False,
            foundry_initialized=False,
            detail="azure-ai-projects SDK not importable; running in local scaffold mode",
        )

    azure_key_credential = _resolve_azure_key_credential()
    project_endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "")
    project_api_key = os.getenv("FOUNDRY_PROJECT_API_KEY", "")

    if project_endpoint and project_api_key and azure_key_credential is not None:
        try:
            ai_project_client(  # type: ignore[call-arg]
                endpoint=project_endpoint,
                credential=azure_key_credential(project_api_key),
            )
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            return RuntimeStatus(
                foundry_sdk_available=True,
                foundry_initialized=False,
                detail=f"Foundry initialization failed: {exc}",
            )
        return RuntimeStatus(
            foundry_sdk_available=True,
            foundry_initialized=True,
            detail="Foundry project client initialized from endpoint + key",
        )

    return RuntimeStatus(
        foundry_sdk_available=True,
        foundry_initialized=False,
        detail=(
            "Foundry SDK available but no runtime credentials provided. "
            "Set FOUNDRY_PROJECT_ENDPOINT + FOUNDRY_PROJECT_API_KEY"
        ),
    )
