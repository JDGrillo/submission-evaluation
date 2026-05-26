from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Dict
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import AppConfig

try:
    from openai import (
        APIConnectionError,
        APIError,
        APITimeoutError,
        AuthenticationError,
        AzureOpenAI,
        BadRequestError,
        InternalServerError,
        NotFoundError,
        RateLimitError,
    )

    _AOAI_EXCEPTIONS: tuple[type[BaseException], ...] = (
        APIConnectionError,
        APIError,
        APITimeoutError,
        AuthenticationError,
        BadRequestError,
        InternalServerError,
        NotFoundError,
        RateLimitError,
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised when openai is unavailable
    AzureOpenAI = None  # type: ignore[assignment]
    _AOAI_EXCEPTIONS = (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    )


@dataclass(frozen=True)
class ConnectivityResult:
    ok: bool
    detail: str


ProbeFn = Callable[[str, Dict[str, str]], ConnectivityResult]


class WebSearchRateLimitError(RuntimeError):
    """Raised when the web search provider returns a rate-limit response."""


def default_probe(url: str, headers: Dict[str, str]) -> ConnectivityResult:
    request = Request(url=url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=5) as response:
            if 200 <= response.status < 400:
                return ConnectivityResult(
                    True, f"Live probe ok (HTTP {response.status})"
                )
            return ConnectivityResult(
                False, f"Live probe failed (HTTP {response.status})"
            )
    except URLError as exc:
        return ConnectivityResult(False, f"Live probe error: {exc}")


class AzureOpenAIClient:
    """Configuration-backed Azure OpenAI client placeholder for later SDK wiring."""

    def __init__(self, config: AppConfig, probe_fn: ProbeFn = default_probe) -> None:
        self._config = config
        self._probe_fn = probe_fn

    def connectivity_check(self, probe: bool = False) -> ConnectivityResult:
        if not self._config.azure_openai_endpoint:
            return ConnectivityResult(False, "Missing AZURE_OPENAI_ENDPOINT")
        if not self._config.azure_openai_api_key:
            return ConnectivityResult(False, "Missing AZURE_OPENAI_API_KEY")
        if not self._config.azure_openai_deployment:
            return ConnectivityResult(False, "Missing AZURE_OPENAI_DEPLOYMENT")
        if not probe:
            return ConnectivityResult(True, "Azure OpenAI configuration is present")

        endpoint = self._config.azure_openai_endpoint.rstrip("/")
        url = (
            f"{endpoint}/openai/deployments?api-version="
            f"{self._config.azure_openai_api_version}"
        )
        headers = {"api-key": self._config.azure_openai_api_key}
        return self._probe_fn(url, headers)

    def extract_location_candidates(self, text: str) -> list[dict[str, object]]:
        """Best-effort structured extraction used by ingestion; returns [] on any failure."""
        if not text.strip():
            return []
        if not self.connectivity_check(probe=False).ok:
            return []
        if AzureOpenAI is None:
            return []

        try:
            client = AzureOpenAI(
                api_key=self._config.azure_openai_api_key,
                api_version=self._config.azure_openai_api_version,
                azure_endpoint=self._config.azure_openai_endpoint,
            )
            response = client.chat.completions.create(
                model=self._config.azure_openai_deployment,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Extract insurance location candidates from unstructured text. "
                            "Return strict JSON with key 'locations' as an array. "
                            "Each location may include: location_name, address_line_1, city, "
                            "state, postal_code, country, confidence (0..1), supplementary_text."
                        ),
                    },
                    {"role": "user", "content": text[:16000]},
                ],
            )
            content = response.choices[0].message.content or "{}"
            parsed = json.loads(content)
            locations = parsed.get("locations", [])
            if not isinstance(locations, list):
                return []

            sanitized: list[dict[str, object]] = []
            for entry in locations:
                if isinstance(entry, dict):
                    sanitized.append({str(key): value for key, value in entry.items()})
            return sanitized
        except _AOAI_EXCEPTIONS:
            return []


class WebSearchClient:
    """Configuration-backed Web Search client placeholder for later SDK wiring."""

    def __init__(self, config: AppConfig, probe_fn: ProbeFn = default_probe) -> None:
        self._config = config
        self._probe_fn = probe_fn

    def connectivity_check(self, probe: bool = False) -> ConnectivityResult:
        if not self._config.web_search_endpoint:
            return ConnectivityResult(False, "Missing WEB_SEARCH_ENDPOINT")
        if not self._config.web_search_api_key:
            return ConnectivityResult(False, "Missing WEB_SEARCH_API_KEY")
        if not probe:
            return ConnectivityResult(True, "Web Search configuration is present")

        endpoint = self._config.web_search_endpoint.rstrip("/")
        url = f"{endpoint}?q=connectivity-check&count=1"
        headers = {"Ocp-Apim-Subscription-Key": self._config.web_search_api_key}
        return self._probe_fn(url, headers)

    def search_web(self, query: str, *, count: int = 5) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        if not self._config.web_search_endpoint or not self._config.web_search_api_key:
            return []

        endpoint = self._config.web_search_endpoint.rstrip("/")
        params = urlencode({"q": query, "count": max(1, count)})
        url = f"{endpoint}?{params}"
        headers = {"Ocp-Apim-Subscription-Key": self._config.web_search_api_key}
        request = Request(url=url, headers=headers, method="GET")

        try:
            with urlopen(request, timeout=10) as response:
                if not (200 <= response.status < 400):
                    return []
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 429:
                raise WebSearchRateLimitError("Web search rate-limited") from exc
            return []
        except (URLError, ValueError, TypeError, json.JSONDecodeError):
            return []

        values = payload.get("webPages", {}).get("value", [])
        if not isinstance(values, list):
            return []

        normalized: list[dict[str, Any]] = []
        for item in values:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "name": str(item.get("name", "")).strip(),
                    "url": str(item.get("url", "")).strip(),
                    "snippet": str(item.get("snippet", "")).strip(),
                }
            )
        return normalized


def run_connectivity_checks(
    config: AppConfig, probe: bool = False
) -> Dict[str, ConnectivityResult]:
    aoai = AzureOpenAIClient(config).connectivity_check(probe=probe)
    web = WebSearchClient(config).connectivity_check(probe=probe)
    return {
        "azure_openai": aoai,
        "web_search": web,
    }
