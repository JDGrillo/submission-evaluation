from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import re
import time
from typing import Any, Callable, Mapping

from ..clients import WebSearchClient, WebSearchRateLimitError
from ..config import AppConfig
from ..models import Location, LocationManifest
from .base import AgentResult, NoOpAgent

RISK_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("flood", "flood risk and flood history"),
    ("earthquake", "earthquake risk and seismic history"),
    ("hurricane", "hurricane risk and hurricane history"),
    ("tornado", "tornado risk and tornado history"),
    ("wildfire", "wildfire risk and wildfire history"),
    ("hail", "hail storm risk and hail history"),
    ("storm_surge", "storm surge risk"),
    ("tsunami", "tsunami risk and tsunami history"),
    ("volcanic", "volcanic activity risk"),
    ("landslide", "landslide risk and landslide history"),
    ("sinkhole", "sinkhole risk and sinkhole history"),
    ("winter_storm", "winter storm risk and severe winter weather history"),
    ("lightning", "lightning strike risk and lightning activity"),
    ("climate_projection_10y", "10-year climate projections and climate trends"),
)

COMPANY_QUERY_TOPICS: tuple[tuple[str, str], ...] = (
    ("industry", "industry and business profile"),
    ("operations", "operations footprint and facilities"),
    ("news", "recent news risk events"),
)

_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}")
_PHONE_PATTERN = re.compile(r"(?:\\+?\\d[\\d()\\-\\s]{6,}\\d)")
_SIZE_REVENUE_PATTERN = re.compile(
    r"(\$\s?\d[\d.,]*(?:\s?(?:million|billion|m|bn))?|\d[\d,]*\s+employees?)",
    re.IGNORECASE,
)


def _clean_query_text(value: str) -> str:
    value = _EMAIL_PATTERN.sub("", value)
    value = _PHONE_PATTERN.sub("", value)
    value = " ".join(value.split())
    return value.strip()


def _location_query_base(location: Location) -> str:
    # Deliberately excludes contact_name/contact_phone/contact_email.
    parts = [
        location.address_line_1,
        location.city,
        location.state,
        location.postal_code,
        location.country,
    ]
    return " ".join(
        part.strip() for part in parts if isinstance(part, str) and part.strip()
    )


def _contains_pii(value: str) -> bool:
    return bool(_EMAIL_PATTERN.search(value) or _PHONE_PATTERN.search(value))


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


class ResearchAgent(NoOpAgent):
    def __init__(
        self,
        *,
        config: AppConfig | None = None,
        web_search_client: WebSearchClient | None = None,
        max_workers: int = 4,
        max_retries: int = 3,
        backoff_seconds: float = 0.2,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock_fn: Callable[[], str] | None = None,
    ) -> None:
        super().__init__("research")
        self._config = config or AppConfig.from_env()
        self._web_search_client = web_search_client or WebSearchClient(self._config)
        self._max_workers = max(1, max_workers)
        self._max_retries = max(1, max_retries)
        self._backoff_seconds = max(0.0, backoff_seconds)
        self._sleep_fn = sleep_fn
        self._clock_fn = clock_fn or (lambda: datetime.now(timezone.utc).isoformat())

    def invoke(self, payload: Mapping[str, Any]) -> AgentResult:
        manifest = self._extract_manifest(payload)
        if manifest is None:
            return super().invoke(dict(payload))

        results = self.gather_environmental_risk_data(manifest)
        company_research = self.gather_company_research(manifest)
        return AgentResult(
            agent=self.name,
            status="ok",
            payload={
                "received": dict(payload),
                "message": "research completed",
                "location_count": manifest.count,
                "research_results": results,
                "company_research": company_research,
            },
        )

    def gather_company_research(self, manifest: LocationManifest) -> dict[str, Any]:
        primary_location = manifest.locations[0] if manifest.locations else None
        company_name = self._extract_company_name(manifest)
        primary_address = (
            _location_query_base(primary_location) if primary_location else ""
        )

        result: dict[str, Any] = {
            "company_name": company_name,
            "primary_address": primary_address,
            "company_found": False,
            "not_found": False,
            "not_found_reason": None,
            "logged_queries": [],
            "overview": {
                "industry": None,
                "size_or_revenue": None,
                "operations_summary": None,
                "citations": [],
            },
            "operations_context": {
                "summary": None,
                "citations": [],
            },
            "risk_news_events": [],
            "citations": [],
        }

        if not company_name:
            result["not_found"] = True
            result["not_found_reason"] = "company_name_unavailable"
            return result

        query_hits: dict[str, list[Mapping[str, Any]]] = {}
        for topic, topic_query in COMPANY_QUERY_TOPICS:
            query = self._build_company_query(
                company_name=company_name,
                topic_query=topic_query,
                primary_location=primary_location,
                manifest=manifest,
            )
            if not query or not self._company_query_is_safe(query, manifest):
                continue
            result["logged_queries"].append(query)

            try:
                hits = self.search_with_backoff(query)
            except (RuntimeError, TimeoutError, ValueError, ConnectionError, OSError):
                hits = []

            query_hits[topic] = [
                hit
                for hit in hits
                if isinstance(hit, Mapping) and str(hit.get("url", "")).strip()
            ]

        citations = self._build_citations(query_hits)
        result["citations"] = citations

        if not citations:
            result["not_found"] = True
            result["not_found_reason"] = "no_public_data_found"
            return result

        result["company_found"] = True

        industry_hits = query_hits.get("industry", [])
        operations_hits = query_hits.get("operations", [])
        news_hits = query_hits.get("news", [])

        overview_citations = self._extract_urls(industry_hits + operations_hits)
        overview = result["overview"]
        overview["industry"] = self._extract_industry(industry_hits)
        overview["size_or_revenue"] = self._extract_size_or_revenue(
            industry_hits + operations_hits + news_hits
        )
        overview["operations_summary"] = self._extract_operations_summary(
            operations_hits
        )
        overview["citations"] = overview_citations

        operations_context = result["operations_context"]
        operations_context["summary"] = self._extract_operations_summary(
            operations_hits
        )
        operations_context["citations"] = self._extract_urls(operations_hits)

        result["risk_news_events"] = self._extract_news_events(news_hits)

        return result

    def gather_environmental_risk_data(
        self,
        manifest: LocationManifest,
    ) -> dict[str, list[dict[str, Any]]]:
        keyed_results: dict[str, list[dict[str, Any]]] = {}
        locations = list(manifest.locations)
        if not locations:
            return keyed_results

        max_workers = min(self._max_workers, len(locations))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(self._research_location, location): location
                for location in locations
            }
            for future in as_completed(future_map):
                location = future_map[future]
                location_id = location.id or f"missing-id-{id(location)}"
                try:
                    keyed_results[location_id] = future.result()
                except (
                    RuntimeError,
                    TimeoutError,
                    ValueError,
                    ConnectionError,
                    OSError,
                ):
                    # Preserve location integrity by emitting no-result placeholders for all categories.
                    keyed_results[location_id] = [
                        self._no_data_result(
                            location_id=location_id,
                            risk_category=risk_category,
                            query=self._build_query(location, search_term),
                        )
                        for risk_category, search_term in RISK_CATEGORIES
                    ]
        return keyed_results

    def _research_location(self, location: Location) -> list[dict[str, Any]]:
        location_id = location.id or ""
        location_results: list[dict[str, Any]] = []

        for risk_category, search_term in RISK_CATEGORIES:
            query = self._build_query(location, search_term)
            if not self._query_is_safe(query, location):
                location_results.append(
                    self._no_data_result(
                        location_id=location_id,
                        risk_category=risk_category,
                        query="query_blocked_for_pii",
                    )
                )
                continue
            try:
                hits = self.search_with_backoff(query)
            except (RuntimeError, TimeoutError, ValueError, ConnectionError, OSError):
                hits = []

            if not hits:
                location_results.append(
                    self._no_data_result(
                        location_id=location_id,
                        risk_category=risk_category,
                        query=query,
                    )
                )
                continue

            timestamp = self._clock_fn()
            valid_hits = [
                hit
                for hit in hits
                if isinstance(hit, Mapping) and str(hit.get("url", "")).strip()
            ]
            sources = [
                {
                    "source_url": str(hit.get("url", "")).strip(),
                    "retrieved_at": timestamp,
                }
                for hit in valid_hits
            ]
            if not sources:
                location_results.append(
                    self._no_data_result(
                        location_id=location_id,
                        risk_category=risk_category,
                        query=query,
                    )
                )
                continue
            source_urls = [entry["source_url"] for entry in sources]
            snippets = [
                str(hit.get("snippet", "")).strip()
                for hit in valid_hits
                if hit.get("snippet")
            ]

            location_results.append(
                {
                    "location_id": location_id,
                    "risk_category": risk_category,
                    "query": query,
                    "findings": (
                        " | ".join(snippets) if snippets else "public data found"
                    ),
                    "source_urls": source_urls,
                    "sources": sources,
                    "retrieval_timestamp": timestamp,
                    "no_public_data": False,
                }
            )

        return location_results

    def _build_query(self, location: Location, search_term: str) -> str:
        base = _location_query_base(location)
        query = _clean_query_text(f"{base} {search_term}")
        return query

    def _build_company_query(
        self,
        *,
        company_name: str,
        topic_query: str,
        primary_location: Location | None,
        manifest: LocationManifest,
    ) -> str:
        location_context = ""
        if primary_location is not None:
            location_context = " ".join(
                part.strip()
                for part in [
                    primary_location.city,
                    primary_location.state,
                    primary_location.country,
                ]
                if isinstance(part, str) and part.strip()
            )
        candidate = _clean_query_text(
            f"{company_name} {location_context} {topic_query}"
        )
        candidate = self._strip_contact_tokens(candidate, manifest)
        return _clean_query_text(candidate)

    def _query_is_safe(self, query: str, location: Location) -> bool:
        if _contains_pii(query):
            return False

        contact_tokens = [
            location.contact_name,
            location.contact_email,
            location.contact_phone,
        ]
        query_lower = query.lower()
        for token in contact_tokens:
            if isinstance(token, str):
                normalized = token.strip().lower()
                if normalized and normalized in query_lower:
                    return False
        return True

    def _company_query_is_safe(self, query: str, manifest: LocationManifest) -> bool:
        if _contains_pii(query):
            return False
        query_lower = query.lower()
        for token in self._manifest_contact_tokens(manifest):
            if token.lower() in query_lower:
                return False
        return True

    def _manifest_contact_tokens(self, manifest: LocationManifest) -> list[str]:
        tokens: list[str] = []
        for location in manifest.locations:
            for token in [
                location.contact_name,
                location.contact_email,
                location.contact_phone,
            ]:
                if isinstance(token, str):
                    normalized = token.strip()
                    if normalized:
                        tokens.append(normalized)
        return _dedupe_preserve_order(tokens)

    def _strip_contact_tokens(self, value: str, manifest: LocationManifest) -> str:
        sanitized = value
        for token in self._manifest_contact_tokens(manifest):
            sanitized = re.sub(re.escape(token), " ", sanitized, flags=re.IGNORECASE)
        return " ".join(sanitized.split())

    def _extract_company_name(self, manifest: LocationManifest) -> str | None:
        preferred_keys = (
            "company_name",
            "customer_name",
            "insured_name",
            "company",
            "customer",
            "prospect_name",
        )
        for location in manifest.locations:
            additional_fields = location.additional_fields
            for key in preferred_keys:
                raw_value = additional_fields.get(key)
                if isinstance(raw_value, str):
                    company_name = _clean_query_text(raw_value)
                    if company_name:
                        return company_name
        return None

    def _build_citations(
        self, query_hits: Mapping[str, list[Mapping[str, Any]]]
    ) -> list[dict[str, str]]:
        timestamp = self._clock_fn()
        urls: list[str] = []
        for hits in query_hits.values():
            urls.extend(self._extract_urls(hits))
        return [
            {
                "source_url": url,
                "retrieved_at": timestamp,
            }
            for url in _dedupe_preserve_order(urls)
        ]

    def _extract_urls(self, hits: list[Mapping[str, Any]]) -> list[str]:
        urls = [
            str(hit.get("url", "")).strip()
            for hit in hits
            if str(hit.get("url", "")).strip()
        ]
        return _dedupe_preserve_order(urls)

    def _extract_industry(self, hits: list[Mapping[str, Any]]) -> str | None:
        if not hits:
            return None
        first_name = str(hits[0].get("name", "")).strip()
        if first_name:
            return first_name
        first_snippet = str(hits[0].get("snippet", "")).strip()
        return first_snippet or None

    def _extract_operations_summary(self, hits: list[Mapping[str, Any]]) -> str | None:
        snippets = [
            str(hit.get("snippet", "")).strip()
            for hit in hits
            if str(hit.get("snippet", "")).strip()
        ]
        if not snippets:
            return None
        return " | ".join(snippets[:2])

    def _extract_size_or_revenue(self, hits: list[Mapping[str, Any]]) -> str | None:
        for hit in hits:
            snippet = str(hit.get("snippet", "")).strip()
            if not snippet:
                continue
            match = _SIZE_REVENUE_PATTERN.search(snippet)
            if match:
                return match.group(1).strip()
        return None

    def _extract_news_events(
        self, hits: list[Mapping[str, Any]]
    ) -> list[dict[str, str]]:
        events: list[dict[str, str]] = []
        for hit in hits:
            source_url = str(hit.get("url", "")).strip()
            if not source_url:
                continue
            title = str(hit.get("name", "")).strip() or "Untitled event"
            summary = str(hit.get("snippet", "")).strip() or "No summary available"
            events.append(
                {
                    "title": title,
                    "summary": summary,
                    "source_url": source_url,
                    "retrieved_at": self._clock_fn(),
                }
            )
        return events

    def search_with_backoff(self, query: str) -> list[dict[str, Any]]:
        delay = self._backoff_seconds
        for attempt in range(1, self._max_retries + 1):
            try:
                return self._web_search_client.search_web(query, count=5)
            except WebSearchRateLimitError:
                if attempt >= self._max_retries:
                    return []
                if delay > 0:
                    self._sleep_fn(delay)
                delay *= 2
        return []

    def _no_data_result(
        self,
        *,
        location_id: str,
        risk_category: str,
        query: str,
    ) -> dict[str, Any]:
        timestamp = self._clock_fn()
        return {
            "location_id": location_id,
            "risk_category": risk_category,
            "query": query,
            "findings": "no public data available",
            "source_urls": [],
            "sources": [],
            "retrieval_timestamp": timestamp,
            "no_public_data": True,
        }

    def _extract_manifest(self, payload: Mapping[str, Any]) -> LocationManifest | None:
        cursor: Mapping[str, Any] | None = payload
        for _ in range(4):
            if cursor is None:
                return None
            manifest = cursor.get("manifest")
            if isinstance(manifest, Mapping):
                return LocationManifest.from_dict(manifest)
            previous = cursor.get("previous")
            if isinstance(previous, Mapping):
                cursor = previous
                continue
            return None
        return None


__all__ = ["RISK_CATEGORIES", "ResearchAgent"]
