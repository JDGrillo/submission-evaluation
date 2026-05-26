from __future__ import annotations

import re
from typing import Any, Mapping

from ..models import Location, LocationManifest
from .base import AgentResult, NoOpAgent

_CATEGORY_ORDER: tuple[str, ...] = (
    "flood",
    "earthquake",
    "hurricane",
    "tornado",
    "wildfire",
    "hail",
    "storm_surge",
    "climate_trend",
)

_CATEGORY_TO_FIELD: dict[str, str] = {
    "flood": "flood_zone",
    "earthquake": "earthquake_zone",
    "hurricane": "hurricane_zone",
    "tornado": "tornado_zone",
    "wildfire": "wildfire_zone",
    "hail": "hail_zone",
    "storm_surge": "storm_surge_zone",
    "climate_trend": "climate_zone",
}

_CATEGORY_TO_RESEARCH: dict[str, str] = {
    "flood": "flood",
    "earthquake": "earthquake",
    "hurricane": "hurricane",
    "tornado": "tornado",
    "wildfire": "wildfire",
    "hail": "hail",
    "storm_surge": "storm_surge",
    "climate_trend": "climate_projection_10y",
}

_HIGH_SIGNAL = (
    "high",
    "very high",
    "severe",
    "extreme",
    "major",
    "critical",
    "frequent",
    "increasing",
)
_LOW_SIGNAL = (
    "low",
    "very low",
    "minimal",
    "minor",
    "outside",
    "rare",
    "decreasing",
)

_FLOOD_ZONE_HIGH = ("a", "ae", "ao", "ah", "ve", "v")
_FLOOD_ZONE_LOW = ("x", "c")


def _clamp_score(value: float) -> float:
    return max(1.0, min(10.0, value))


def _extract_number(value: str) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _coerce_score_text(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw <= 0:
            return None
        if raw <= 1:
            return _clamp_score(raw * 10)
        return _clamp_score(raw)

    text = str(value).strip().lower()
    if not text:
        return None

    number = _extract_number(text)
    if number is not None:
        if "/10" in text or "out of 10" in text:
            return _clamp_score(number)
        if number <= 1:
            return _clamp_score(number * 10)
        return _clamp_score(number)

    if any(signal in text for signal in _HIGH_SIGNAL):
        return 8.0
    if "moderate" in text or "medium" in text:
        return 5.5
    if any(signal in text for signal in _LOW_SIGNAL):
        return 2.5
    return None


def _score_input_signal(category: str, location: Location) -> float | None:
    raw = getattr(location, _CATEGORY_TO_FIELD[category], None)
    if raw is None:
        return None

    if category == "flood" and isinstance(raw, str):
        token = raw.strip().lower()
        if token in _FLOOD_ZONE_HIGH:
            return 8.5
        if token in _FLOOD_ZONE_LOW:
            return 2.0

    return _coerce_score_text(raw)


def _score_research_signal(entries: list[Mapping[str, Any]]) -> float | None:
    if not entries:
        return None
    findings_blob = " ".join(
        str(entry.get("findings", "")).lower().strip()
        for entry in entries
        if not entry.get("no_public_data")
    ).strip()
    if not findings_blob:
        return None

    high_hits = sum(1 for term in _HIGH_SIGNAL if term in findings_blob)
    low_hits = sum(1 for term in _LOW_SIGNAL if term in findings_blob)

    if high_hits > low_hits:
        return 7.5
    if low_hits > high_hits:
        return 3.0
    return 5.5


def _round_score(value: float) -> float:
    return round(_clamp_score(value), 1)


class AnalysisAgent(NoOpAgent):
    def __init__(self) -> None:
        super().__init__("analysis")

    def invoke(self, payload: Mapping[str, Any]) -> AgentResult:
        manifest = self._extract_manifest(payload)
        if manifest is None:
            return super().invoke(dict(payload))

        research_results = self._extract_research_results(payload)
        scores_by_location = self.score_manifest(
            manifest=manifest,
            research_results=research_results,
        )

        return AgentResult(
            agent=self.name,
            status="ok",
            payload={
                "received": dict(payload),
                "message": "analysis completed",
                "location_count": manifest.count,
                "methodology": {
                    "version": "risk-v1",
                    "input_weight": 0.8,
                    "research_weight": 0.2,
                    "categories": list(_CATEGORY_ORDER),
                },
                "risk_scores_by_location": scores_by_location,
            },
        )

    def score_manifest(
        self,
        *,
        manifest: LocationManifest,
        research_results: Mapping[str, list[Mapping[str, Any]]] | None,
    ) -> dict[str, dict[str, Any]]:
        keyed_scores: dict[str, dict[str, Any]] = {}
        for location in manifest.locations:
            location_id = location.id or ""
            per_location_research = (research_results or {}).get(location_id, [])
            category_scores = self._score_location_categories(location, per_location_research)
            overall_score, overall_rationale = self._compute_overall(category_scores)
            keyed_scores[location_id] = {
                "location_id": location_id,
                "methodology_version": "risk-v1",
                "overall_score": overall_score,
                "overall_rationale": overall_rationale,
                "category_scores": category_scores,
            }
        return keyed_scores

    def _score_location_categories(
        self,
        location: Location,
        location_research: list[Mapping[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        by_category: dict[str, list[Mapping[str, Any]]] = {}
        for entry in location_research:
            category = str(entry.get("risk_category", "")).strip()
            by_category.setdefault(category, []).append(entry)

        category_scores: dict[str, dict[str, Any]] = {}
        for category in _CATEGORY_ORDER:
            input_score = _score_input_signal(category, location)
            research_entries = by_category.get(_CATEGORY_TO_RESEARCH[category], [])
            research_score = _score_research_signal(research_entries)
            has_research_data = any(not bool(entry.get("no_public_data")) for entry in research_entries)

            if input_score is None and research_score is None:
                category_scores[category] = {
                    "score": "N/A",
                    "rationale": "Insufficient data: no input signal and no supporting research findings.",
                    "input_signal": None,
                    "research_signal": None,
                    "used_research": False,
                }
                continue

            if input_score is None:
                final_score = _round_score(research_score or 5.5)
                rationale = (
                    f"Score based on research findings only ({final_score}); input field "
                    f"{_CATEGORY_TO_FIELD[category]} is unavailable."
                )
            elif research_score is None:
                final_score = _round_score(input_score)
                rationale = (
                    f"Score derived from primary input field {_CATEGORY_TO_FIELD[category]} "
                    f"({final_score}) with no supplemental research signal."
                )
            else:
                weighted = (input_score * 0.8) + (research_score * 0.2)
                final_score = _round_score(weighted)
                rationale = (
                    f"Score uses 80/20 weighting of input ({_round_score(input_score)}) and "
                    f"research ({_round_score(research_score)}), producing {final_score}."
                )

            category_scores[category] = {
                "score": final_score,
                "rationale": rationale,
                "input_signal": None if input_score is None else _round_score(input_score),
                "research_signal": None if research_score is None else _round_score(research_score),
                "used_research": has_research_data,
            }

        return category_scores

    def _compute_overall(
        self,
        category_scores: Mapping[str, Mapping[str, Any]],
    ) -> tuple[float | str, str]:
        numeric_scores = [
            float(details["score"])
            for details in category_scores.values()
            if isinstance(details.get("score"), (int, float))
        ]
        na_categories = [name for name, details in category_scores.items() if details.get("score") == "N/A"]

        if not numeric_scores:
            return "N/A", "Insufficient data: all risk categories are N/A."

        overall = _round_score(sum(numeric_scores) / len(numeric_scores))
        if na_categories:
            rationale = (
                f"Overall score is the mean of {len(numeric_scores)} scored categories ({overall}); "
                f"{len(na_categories)} categories were N/A due to insufficient data."
            )
            return overall, rationale

        rationale = f"Overall score is the mean of all {len(numeric_scores)} category scores ({overall})."
        return overall, rationale

    def _extract_manifest(self, payload: Mapping[str, Any]) -> LocationManifest | None:
        cursor: Mapping[str, Any] | None = payload
        for _ in range(5):
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

    def _extract_research_results(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, list[Mapping[str, Any]]]:
        cursor: Mapping[str, Any] | None = payload
        for _ in range(6):
            if cursor is None:
                break

            direct = cursor.get("research_results")
            if isinstance(direct, Mapping):
                return {
                    str(location_id): [entry for entry in entries if isinstance(entry, Mapping)]
                    for location_id, entries in direct.items()
                    if isinstance(entries, list)
                }

            received = cursor.get("received")
            if isinstance(received, Mapping):
                embedded = received.get("research_results")
                if isinstance(embedded, Mapping):
                    return {
                        str(location_id): [entry for entry in entries if isinstance(entry, Mapping)]
                        for location_id, entries in embedded.items()
                        if isinstance(entries, list)
                    }

            previous = cursor.get("previous")
            if isinstance(previous, Mapping):
                cursor = previous
                continue
            break
        return {}
