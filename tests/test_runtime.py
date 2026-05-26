from __future__ import annotations

from submission_evaluation.main import _register_agents
from submission_evaluation.runtime import AgentFrameworkRuntime, initialize_foundry_runtime
import submission_evaluation.runtime as runtime_module


def test_register_agents_contains_full_stub_set():
    runtime = AgentFrameworkRuntime()
    _register_agents(runtime)
    names = runtime.discover_agents()

    assert names == [
        "analysis",
        "ingestion",
        "orchestrator",
        "report",
        "research",
        "validation",
    ]


def test_initialize_foundry_runtime_when_sdk_unavailable(monkeypatch):
    monkeypatch.setattr(runtime_module, "_resolve_ai_project_client", lambda: None)
    status = initialize_foundry_runtime()
    assert status.foundry_sdk_available is False
    assert status.foundry_initialized is False


def test_initialize_foundry_runtime_with_endpoint_and_key(monkeypatch):
    called = {"value": False}

    class FakeClient:
        def __init__(self, endpoint, credential):
            _ = endpoint
            _ = credential
            called["value"] = True

    class FakeCredential:
        def __init__(self, _key):
            pass

    monkeypatch.setattr(runtime_module, "_resolve_ai_project_client", lambda: FakeClient)
    monkeypatch.setattr(runtime_module, "_resolve_azure_key_credential", lambda: FakeCredential)
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example.foundry")
    monkeypatch.setenv("FOUNDRY_PROJECT_API_KEY", "key")

    status = initialize_foundry_runtime()
    assert status.foundry_sdk_available is True
    assert status.foundry_initialized is True
    assert called["value"] is True
