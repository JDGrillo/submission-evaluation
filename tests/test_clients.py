from __future__ import annotations

from pathlib import Path

from submission_evaluation.clients import (
    AzureOpenAIClient,
    ConnectivityResult,
    WebSearchClient,
)
from submission_evaluation.config import AppConfig


def _config() -> AppConfig:
    return AppConfig(
        input_dir=Path("input"),
        processed_dir=Path("input") / "processed",
        output_dir=Path("output"),
        azure_openai_endpoint="https://example.openai.azure.com",
        azure_openai_api_key="key",
        azure_openai_deployment="gpt-4.1",
        azure_openai_api_version="2024-06-01",
        web_search_endpoint="https://example.search",
        web_search_api_key="search-key",
    )


def test_azure_connectivity_probe_success():
    captured = {}

    def probe(url, headers):
        captured["url"] = url
        captured["headers"] = headers
        return ConnectivityResult(True, "ok")

    result = AzureOpenAIClient(_config(), probe_fn=probe).connectivity_check(probe=True)
    assert result.ok is True
    assert "/openai/deployments?api-version=2024-06-01" in captured["url"]
    assert captured["headers"]["api-key"] == "key"


def test_web_connectivity_probe_failure():
    captured = {}

    def probe(url, headers):
        captured["url"] = url
        captured["headers"] = headers
        return ConnectivityResult(False, "bad")

    result = WebSearchClient(_config(), probe_fn=probe).connectivity_check(probe=True)
    assert result.ok is False
    assert "q=connectivity-check" in captured["url"]
    assert captured["headers"]["Ocp-Apim-Subscription-Key"] == "search-key"
