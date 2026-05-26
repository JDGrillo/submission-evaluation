from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Iterable, Mapping

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def _canonical_json(value: JsonValue | dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        frozen_items = {key: _deep_freeze(value[key]) for key in sorted(value)}
        return MappingProxyType(frozen_items)
    if isinstance(value, list | tuple):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _to_json_compatible(value: Any) -> JsonValue:
    if isinstance(value, Mapping):
        return {str(key): _to_json_compatible(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_to_json_compatible(item) for item in value]
    return value


def _freeze_mapping(value: Mapping[str, JsonValue] | None) -> Mapping[str, JsonValue]:
    if not value:
        return MappingProxyType({})
    return _deep_freeze(value)


@dataclass(frozen=True)
class Location:
    id: str | None = None
    submission_id: str | None = None
    source_file: str | None = None
    source_sheet: str | None = None
    source_row: int | None = None
    location_name: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    county: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    occupancy_type: str | None = None
    occupancy_subtype: str | None = None
    building_type: str | None = None
    construction_type: str | None = None
    roof_type: str | None = None
    foundation_type: str | None = None
    year_built: int | None = None
    year_renovated: int | None = None
    stories: int | None = None
    square_feet: float | None = None
    sprinklered: bool | None = None
    alarm_type: str | None = None
    protection_class: str | None = None
    total_insured_value: float | None = None
    building_value: float | None = None
    contents_value: float | None = None
    business_interruption_value: float | None = None
    deductible: float | None = None
    flood_zone: str | None = None
    earthquake_zone: str | None = None
    hurricane_zone: str | None = None
    tornado_zone: str | None = None
    wildfire_zone: str | None = None
    hail_zone: str | None = None
    wind_zone: str | None = None
    storm_surge_zone: str | None = None
    tsunami_zone: str | None = None
    volcanic_zone: str | None = None
    landslide_zone: str | None = None
    sinkhole_zone: str | None = None
    winter_storm_zone: str | None = None
    lightning_zone: str | None = None
    climate_zone: str | None = None
    distance_to_coast_miles: float | None = None
    distance_to_fault_miles: float | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    additional_fields: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "additional_fields", _freeze_mapping(self.additional_fields))

    def to_dict(
        self,
        *,
        include_id: bool = True,
        include_submission_id: bool = True,
    ) -> dict[str, JsonValue]:
        data: dict[str, JsonValue] = {}
        for model_field in fields(self):
            field_name = model_field.name
            data[field_name] = _to_json_compatible(getattr(self, field_name))
        if not include_id:
            data.pop("id", None)
        if not include_submission_id:
            data.pop("submission_id", None)
        if include_id and data.get("id") is None:
            data.pop("id", None)
        if include_submission_id and data.get("submission_id") is None:
            data.pop("submission_id", None)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Location:
        return cls(**dict(data))


def deterministic_location_id(location: Location, index: int) -> str:
    canonical_payload = location.to_dict(include_id=False, include_submission_id=True)
    digest = sha256(_canonical_json(canonical_payload).encode("utf-8")).hexdigest()
    return f"loc-{index + 1:04d}-{digest[:12]}"


@dataclass(frozen=True)
class LocationManifest:
    locations: tuple[Location, ...]
    submission_id: str | None = None
    count: int = field(init=False)
    manifest_hash: str = field(init=False)

    def __post_init__(self) -> None:
        locations = tuple(self.locations)
        object.__setattr__(self, "locations", locations)
        object.__setattr__(self, "count", len(locations))
        object.__setattr__(self, "manifest_hash", self._compute_hash(locations, self.submission_id))

    @staticmethod
    def _compute_hash(locations: tuple[Location, ...], submission_id: str | None) -> str:
        payload: dict[str, JsonValue] = {
            "submission_id": submission_id,
            "count": len(locations),
            "locations": [loc.to_dict(include_id=True, include_submission_id=True) for loc in locations],
        }
        return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    @classmethod
    def from_records(
        cls,
        records: Iterable[Mapping[str, Any] | Location],
        *,
        submission_id: str | None = None,
    ) -> LocationManifest:
        assigned_locations: list[Location] = []
        for index, record in enumerate(records):
            location = record if isinstance(record, Location) else Location.from_dict(record)
            effective_submission_id = submission_id if submission_id is not None else location.submission_id
            location = replace(location, id=None, submission_id=effective_submission_id)
            location_id = deterministic_location_id(location, index)
            assigned_locations.append(replace(location, id=location_id))
        return cls(locations=tuple(assigned_locations), submission_id=submission_id)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LocationManifest:
        submission_id = data.get("submission_id")
        locations_data = data.get("locations", [])
        locations = tuple(Location.from_dict(record) for record in locations_data)
        manifest = cls(locations=locations, submission_id=submission_id)
        expected_count = data.get("count")
        if expected_count is not None and manifest.count != expected_count:
            raise ValueError(f"Manifest count mismatch: expected={expected_count}, actual={manifest.count}")
        expected_hash = data.get("manifest_hash") or data.get("hash")
        if expected_hash is not None and manifest.manifest_hash != expected_hash:
            raise ValueError("Manifest hash mismatch during deserialization")
        return manifest

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "submission_id": self.submission_id,
            "count": self.count,
            "manifest_hash": self.manifest_hash,
            "locations": [location.to_dict(include_id=True, include_submission_id=True) for location in self.locations],
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, payload: str) -> LocationManifest:
        return cls.from_dict(json.loads(payload))

    def assert_count(self, expected: int) -> None:
        if self.count != expected:
            raise ValueError(f"Location count mismatch: expected={expected}, actual={self.count}")


__all__ = [
    "Location",
    "LocationManifest",
    "deterministic_location_id",
]
