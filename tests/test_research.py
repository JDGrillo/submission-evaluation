from __future__ import annotations

from pathlib import Path

from submission_evaluation.agents.research import RISK_CATEGORIES, ResearchAgent
from submission_evaluation.clients import WebSearchRateLimitError
from submission_evaluation.config import AppConfig
from submission_evaluation.models import LocationManifest


def _config() -> AppConfig:
    return AppConfig(
        input_dir=Path("input"),
        processed_dir=Path("input") / "processed",
        output_dir=Path("output"),
        azure_openai_endpoint="",
        azure_openai_api_key="",
        azure_openai_deployment="",
        azure_openai_api_version="2024-06-01",
        web_search_endpoint="https://example.search",
        web_search_api_key="search-key",
    )


class _StaticSearchClient:
    def __init__(self, *, empty_category: str | None = None) -> None:
        self.queries: list[str] = []
        self.empty_category = empty_category

    def search_web(self, query: str, *, count: int = 5):
        del count
        self.queries.append(query)
        if self.empty_category and self.empty_category in query:
            return []
        return [
            {
                "name": "Result",
                "url": "https://example.com/risk",
                "snippet": "Public risk information.",
            }
        ]


def _manifest() -> LocationManifest:
    return LocationManifest.from_records(
        [
            {
                "location_name": "Site A",
                "address_line_1": "100 Main St",
                "city": "Austin",
                "state": "TX",
                "postal_code": "78701",
                "country": "US",
                "contact_name": "Jane Doe",
                "contact_phone": "555-0101",
                "contact_email": "jane@example.com",
            },
            {
                "location_name": "Site B",
                "address_line_1": "200 Market St",
                "city": "Dallas",
                "state": "TX",
                "postal_code": "75201",
                "country": "US",
                "contact_name": "John Doe",
                "contact_phone": "555-1111",
                "contact_email": "john@example.com",
            },
        ],
        submission_id="sub-005",
    )


def _manifest_with_count(count: int) -> LocationManifest:
    records: list[dict[str, object]] = []
    for idx in range(1, count + 1):
        records.append(
            {
                "location_name": f"Site {idx}",
                "address_line_1": f"{idx} Main St",
                "city": "Austin",
                "state": "TX",
                "postal_code": f"78{idx:03d}",
                "country": "US",
                "contact_name": f"Contact {idx}",
                "contact_phone": f"555-01{idx:02d}",
                "contact_email": f"contact{idx}@example.com",
            }
        )
    return LocationManifest.from_records(records, submission_id="sub-005-scale")


def _company_manifest(*, company_name: str = "Acme Manufacturing") -> LocationManifest:
    return LocationManifest.from_records(
        [
            {
                "location_name": "HQ",
                "address_line_1": "300 Commerce Blvd",
                "city": "Houston",
                "state": "TX",
                "postal_code": "77002",
                "country": "US",
                "contact_name": "Pat Contact",
                "contact_phone": "555-999-1111",
                "contact_email": "pat.contact@example.com",
                "additional_fields": {"company_name": company_name},
            }
        ],
        submission_id="sub-006",
    )


def test_research_when_manifest_has_multiple_locations_should_cover_all_categories_and_key_by_location_id():
    search_client = _StaticSearchClient()
    manifest = _manifest()
    agent = ResearchAgent(
        config=_config(),
        web_search_client=search_client,
        max_workers=2,
        clock_fn=lambda: "2026-05-26T00:00:00Z",
    )

    results = agent.gather_environmental_risk_data(manifest)

    location_ids = {location.id for location in manifest.locations}
    assert set(results.keys()) == location_ids

    expected_categories = {category for category, _ in RISK_CATEGORIES}
    assert "climate_projection_10y" in expected_categories

    for location_id in location_ids:
        location_results = results[location_id]
        categories = {entry["risk_category"] for entry in location_results}
        assert categories == expected_categories
        for entry in location_results:
            assert entry["location_id"] == location_id
            assert entry["retrieval_timestamp"] == "2026-05-26T00:00:00Z"
            assert entry["source_urls"]
            assert entry["sources"]

    all_queries = " ".join(search_client.queries)
    assert "Jane Doe" not in all_queries
    assert "John Doe" not in all_queries
    assert "555-0101" not in all_queries
    assert "555-1111" not in all_queries
    assert "jane@example.com" not in all_queries
    assert "john@example.com" not in all_queries


def test_research_when_manifest_has_5_locations_should_return_results_for_all_5_locations():
    search_client = _StaticSearchClient()
    manifest = _manifest_with_count(5)
    agent = ResearchAgent(
        config=_config(),
        web_search_client=search_client,
        max_workers=3,
        clock_fn=lambda: "2026-05-26T00:00:00Z",
    )

    results = agent.gather_environmental_risk_data(manifest)

    assert len(results) == 5
    assert set(results.keys()) == {location.id for location in manifest.locations}
    for location in manifest.locations:
        entries = results[location.id]
        assert len(entries) == len(RISK_CATEGORIES)


def test_research_when_category_has_no_results_should_set_no_public_data_flag_without_dropping_location():
    search_client = _StaticSearchClient(empty_category="sinkhole risk")
    manifest = _manifest()
    agent = ResearchAgent(
        config=_config(),
        web_search_client=search_client,
        max_workers=2,
        clock_fn=lambda: "2026-05-26T00:00:00Z",
    )

    results = agent.gather_environmental_risk_data(manifest)

    assert len(results) == manifest.count
    for location in manifest.locations:
        entries = results[location.id]
        sinkhole_entries = [entry for entry in entries if entry["risk_category"] == "sinkhole"]
        assert len(sinkhole_entries) == 1
        assert sinkhole_entries[0]["no_public_data"] is True
        assert sinkhole_entries[0]["findings"] == "no public data available"


def test_research_when_rate_limited_should_retry_with_exponential_backoff_and_recover():
    class _RateLimitedThenSuccessClient:
        def __init__(self) -> None:
            self.calls = 0

        def search_web(self, query: str, *, count: int = 5):
            del query, count
            self.calls += 1
            if self.calls < 3:
                raise WebSearchRateLimitError("too many requests")
            return [{"url": "https://example.com", "snippet": "ok"}]

    sleep_calls: list[float] = []

    def _record_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    client = _RateLimitedThenSuccessClient()
    agent = ResearchAgent(
        config=_config(),
        web_search_client=client,
        max_retries=3,
        backoff_seconds=0.1,
        sleep_fn=_record_sleep,
    )

    hits = agent.search_with_backoff("100 Main St Austin TX flood risk")

    assert len(hits) == 1
    assert client.calls == 3
    assert sleep_calls == [0.1, 0.2]


def test_research_when_hits_have_no_urls_should_fallback_to_no_public_data_result():
    class _UrlLessSearchClient:
        def search_web(self, query: str, *, count: int = 5):
            del query, count
            return [{"url": "", "snippet": "unsourced snippet"}]

    manifest = _manifest()
    agent = ResearchAgent(
        config=_config(),
        web_search_client=_UrlLessSearchClient(),
        clock_fn=lambda: "2026-05-26T00:00:00Z",
    )

    results = agent.gather_environmental_risk_data(manifest)

    for entries in results.values():
        for entry in entries:
            assert entry["no_public_data"] is True
            assert entry["source_urls"] == []


def test_research_when_rate_limited_until_exhaustion_should_return_empty_hits_after_retries():
    class _AlwaysRateLimitedClient:
        def __init__(self) -> None:
            self.calls = 0

        def search_web(self, query: str, *, count: int = 5):
            del query, count
            self.calls += 1
            raise WebSearchRateLimitError("too many requests")

    sleep_calls: list[float] = []

    def _record_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    client = _AlwaysRateLimitedClient()
    agent = ResearchAgent(
        config=_config(),
        web_search_client=client,
        max_retries=3,
        backoff_seconds=0.1,
        sleep_fn=_record_sleep,
    )

    hits = agent.search_with_backoff("100 Main St Austin TX flood risk")

    assert hits == []
    assert client.calls == 3
    assert sleep_calls == [0.1, 0.2]


def test_research_when_mixed_sourced_and_unsourced_hits_should_only_emit_sourced_findings():
    class _MixedHitsClient:
        def search_web(self, query: str, *, count: int = 5):
            del query, count
            return [
                {"url": "", "snippet": "unsourced data point"},
                {"url": "https://example.com/sourced", "snippet": "sourced data point"},
            ]

    manifest = _manifest()
    agent = ResearchAgent(
        config=_config(),
        web_search_client=_MixedHitsClient(),
        clock_fn=lambda: "2026-05-26T00:00:00Z",
    )

    results = agent.gather_environmental_risk_data(manifest)

    for entries in results.values():
        for entry in entries:
            assert entry["no_public_data"] is False
            assert entry["source_urls"] == ["https://example.com/sourced"]
            assert "sourced data point" in entry["findings"]
            assert "unsourced data point" not in entry["findings"]


def test_company_research_when_public_data_available_should_return_structured_overview_operations_and_news():
    class _CompanySearchClient:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def search_web(self, query: str, *, count: int = 5):
            del count
            self.queries.append(query)
            if "industry and business profile" in query:
                return [
                    {
                        "name": "Acme Manufacturing Company Profile",
                        "url": "https://example.com/company-profile",
                        "snippet": "Acme is an industrial manufacturer with $2.4 billion annual revenue.",
                    }
                ]
            if "operations footprint and facilities" in query:
                return [
                    {
                        "name": "Acme Operations",
                        "url": "https://example.com/operations",
                        "snippet": "Acme operates production facilities across Gulf Coast regions.",
                    }
                ]
            if "recent news risk events" in query:
                return [
                    {
                        "name": "Acme plant faces flood disruption",
                        "url": "https://example.com/news-event",
                        "snippet": "Flooding temporarily disrupted one Acme site in 2025.",
                    }
                ]
            return []

    manifest = _company_manifest()
    client = _CompanySearchClient()
    agent = ResearchAgent(
        config=_config(),
        web_search_client=client,
        clock_fn=lambda: "2026-05-26T00:00:00Z",
    )

    result = agent.gather_company_research(manifest)

    assert result["company_found"] is True
    assert result["not_found"] is False
    assert result["company_name"] == "Acme Manufacturing"
    assert result["overview"]["industry"] == "Acme Manufacturing Company Profile"
    assert result["overview"]["size_or_revenue"] == "$2.4 billion"
    assert "production facilities" in result["operations_context"]["summary"]
    assert len(result["risk_news_events"]) == 1
    assert result["risk_news_events"][0]["source_url"] == "https://example.com/news-event"
    assert len(result["citations"]) == 3
    assert all(citation["source_url"].startswith("https://") for citation in result["citations"])


def test_company_research_when_company_has_no_public_results_should_set_explicit_not_found_flag():
    class _NoResultsSearchClient:
        def search_web(self, query: str, *, count: int = 5):
            del query, count
            return []

    manifest = _company_manifest(company_name="Unknown Prospect LLC")
    agent = ResearchAgent(
        config=_config(),
        web_search_client=_NoResultsSearchClient(),
    )

    result = agent.gather_company_research(manifest)

    assert result["company_found"] is False
    assert result["not_found"] is True
    assert result["not_found_reason"] == "no_public_data_found"
    assert result["risk_news_events"] == []
    assert result["citations"] == []


def test_company_research_when_findings_exist_should_include_citations_for_overview_and_news():
    class _CitedCompanySearchClient:
        def search_web(self, query: str, *, count: int = 5):
            del count
            if "industry and business profile" in query:
                return [{"name": "Profile", "url": "https://example.com/profile", "snippet": "profile"}]
            if "operations footprint and facilities" in query:
                return [{"name": "Ops", "url": "https://example.com/ops", "snippet": "ops"}]
            if "recent news risk events" in query:
                return [{"name": "News", "url": "https://example.com/news", "snippet": "news"}]
            return []

    manifest = _company_manifest()
    agent = ResearchAgent(
        config=_config(),
        web_search_client=_CitedCompanySearchClient(),
        clock_fn=lambda: "2026-05-26T00:00:00Z",
    )

    result = agent.gather_company_research(manifest)

    assert result["overview"]["citations"]
    assert result["overview"]["size_or_revenue"] is None
    assert result["operations_context"]["citations"]
    assert result["risk_news_events"]
    assert all(event["source_url"].startswith("https://") for event in result["risk_news_events"])


def test_company_research_should_strip_pii_from_constructed_and_logged_queries():
    class _RecordingSearchClient:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def search_web(self, query: str, *, count: int = 5):
            del count
            self.queries.append(query)
            return []

    manifest = _company_manifest(company_name="Acme Manufacturing")
    client = _RecordingSearchClient()
    agent = ResearchAgent(
        config=_config(),
        web_search_client=client,
    )

    result = agent.gather_company_research(manifest)

    all_queries = " ".join(client.queries + result["logged_queries"])
    assert "Pat Contact" not in all_queries
    assert "555-999-1111" not in all_queries
    assert "pat.contact@example.com" not in all_queries
