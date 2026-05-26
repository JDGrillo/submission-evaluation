from __future__ import annotations

from submission_evaluation.agents.analysis import AnalysisAgent
from submission_evaluation.models import LocationManifest


def _manifest_with_full_signals() -> LocationManifest:
    return LocationManifest.from_records(
        [
            {
                "location_name": "Plant A",
                "address_line_1": "100 Main St",
                "city": "Austin",
                "state": "TX",
                "postal_code": "78701",
                "country": "US",
                "flood_zone": "AE",
                "earthquake_zone": "moderate",
                "hurricane_zone": "high",
                "tornado_zone": "medium",
                "wildfire_zone": "high",
                "hail_zone": "moderate",
                "storm_surge_zone": "high",
                "climate_zone": "high",
            }
        ],
        submission_id="sub-007",
    )


def _research_entries(location_id: str) -> dict[str, list[dict[str, object]]]:
    findings = {
        "flood": "High flood frequency and increasing event severity.",
        "earthquake": "Moderate seismic activity in recent years.",
        "hurricane": "Major hurricane exposure with frequent storms.",
        "tornado": "Moderate tornado risk in regional history.",
        "wildfire": "High wildfire activity in nearby counties.",
        "hail": "Moderate hail incidents in local records.",
        "storm_surge": "Severe storm surge exposure in worst-case scenarios.",
        "climate_projection_10y": "Increasing heat and rainfall volatility over 10 years.",
    }
    return {
        location_id: [
            {
                "location_id": location_id,
                "risk_category": category,
                "findings": text,
                "no_public_data": False,
                "source_urls": ["https://example.com/source"],
            }
            for category, text in findings.items()
        ]
    }


def test_analysis_when_full_data_present_should_score_all_categories_and_overall():
    manifest = _manifest_with_full_signals()
    location_id = manifest.locations[0].id
    agent = AnalysisAgent()

    result = agent.invoke(
        {
            "manifest": manifest.to_dict(),
            "research_results": _research_entries(location_id),
        }
    )

    scored = result.payload["risk_scores_by_location"][location_id]
    assert isinstance(scored["overall_score"], float)
    assert scored["overall_score"] >= 1.0
    assert scored["overall_score"] <= 10.0
    for details in scored["category_scores"].values():
        assert isinstance(details["score"], float)
        assert details["score"] >= 1.0
        assert details["score"] <= 10.0


def test_analysis_when_partial_data_should_mark_missing_categories_as_na_not_zero():
    manifest = LocationManifest.from_records(
        [
            {
                "location_name": "Plant B",
                "address_line_1": "200 Market St",
                "city": "Dallas",
                "state": "TX",
                "postal_code": "75201",
                "country": "US",
                "flood_zone": "X",
            }
        ],
        submission_id="sub-007b",
    )
    location_id = manifest.locations[0].id
    agent = AnalysisAgent()

    result = agent.invoke({"manifest": manifest.to_dict(), "research_results": {location_id: []}})
    categories = result.payload["risk_scores_by_location"][location_id]["category_scores"]

    assert categories["flood"]["score"] != "N/A"
    assert categories["earthquake"]["score"] == "N/A"
    assert categories["hurricane"]["score"] == "N/A"
    assert categories["tornado"]["score"] == "N/A"
    assert categories["wildfire"]["score"] == "N/A"
    assert categories["hail"]["score"] == "N/A"
    assert categories["storm_surge"]["score"] == "N/A"
    assert categories["climate_trend"]["score"] == "N/A"


def test_analysis_when_same_inputs_repeated_should_produce_consistent_scores():
    manifest = _manifest_with_full_signals()
    location_id = manifest.locations[0].id
    payload = {
        "manifest": manifest.to_dict(),
        "research_results": _research_entries(location_id),
    }
    agent = AnalysisAgent()

    result_a = agent.invoke(payload)
    result_b = agent.invoke(payload)

    assert result_a.payload["risk_scores_by_location"] == result_b.payload["risk_scores_by_location"]
    assert result_a.payload["methodology"] == result_b.payload["methodology"]


def test_analysis_should_include_rationale_for_overall_and_each_category():
    manifest = _manifest_with_full_signals()
    location_id = manifest.locations[0].id
    agent = AnalysisAgent()

    result = agent.invoke(
        {
            "manifest": manifest.to_dict(),
            "research_results": _research_entries(location_id),
        }
    )
    scored = result.payload["risk_scores_by_location"][location_id]

    assert isinstance(scored["overall_rationale"], str)
    assert scored["overall_rationale"].strip()
    for details in scored["category_scores"].values():
        assert isinstance(details["rationale"], str)
        assert details["rationale"].strip()


def test_analysis_when_multiple_locations_should_key_output_by_location_id_integrity():
    manifest = LocationManifest.from_records(
        [
            {
                "location_name": "Site A",
                "address_line_1": "100 Main St",
                "city": "Austin",
                "state": "TX",
                "postal_code": "78701",
                "country": "US",
                "flood_zone": "AE",
            },
            {
                "location_name": "Site B",
                "address_line_1": "200 Market St",
                "city": "Dallas",
                "state": "TX",
                "postal_code": "75201",
                "country": "US",
                "flood_zone": "X",
            },
        ],
        submission_id="sub-007c",
    )

    research_results = {
        location.id: [
            {
                "location_id": location.id,
                "risk_category": "flood",
                "findings": "Moderate flood history.",
                "no_public_data": False,
                "source_urls": ["https://example.com/flood"],
            }
        ]
        for location in manifest.locations
    }

    agent = AnalysisAgent()
    result = agent.invoke(
        {
            "manifest": manifest.to_dict(),
            "research_results": research_results,
        }
    )

    scored = result.payload["risk_scores_by_location"]
    expected_ids = {location.id for location in manifest.locations}
    assert set(scored.keys()) == expected_ids
    for key, details in scored.items():
        assert details["location_id"] == key
