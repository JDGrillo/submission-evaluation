from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from submission_evaluation.models import Location, LocationManifest


def _sample_record(name: str, address: str) -> dict[str, object]:
    return {
        "location_name": name,
        "address_line_1": address,
        "city": "Austin",
        "state": "TX",
        "postal_code": "78701",
        "country": "US",
        "building_type": "Office",
        "construction_type": "Masonry",
        "year_built": 2005,
        "stories": 4,
        "square_feet": 12500.0,
        "total_insured_value": 5500000.0,
        "flood_zone": "X",
        "earthquake_zone": "Low",
        "wildfire_zone": "Moderate",
        "contact_name": "Jane Doe",
        "contact_email": "jane@example.com",
        "contact_phone": "555-0101",
        "additional_fields": {"custom_col": "value"},
    }


def test_manifest_assigns_unique_deterministic_location_ids():
    records = [
        _sample_record("HQ", "100 Main St"),
        _sample_record("HQ", "100 Main St"),
    ]

    manifest_a = LocationManifest.from_records(records, submission_id="sub-001")
    manifest_b = LocationManifest.from_records(records, submission_id="sub-001")

    ids_a = [loc.id for loc in manifest_a.locations]
    ids_b = [loc.id for loc in manifest_b.locations]

    assert ids_a == ids_b
    assert ids_a[0] != ids_a[1]


def test_manifest_hash_is_deterministic_for_same_input():
    records = [
        _sample_record("HQ", "100 Main St"),
        _sample_record("Warehouse", "200 Market St"),
    ]
    manifest_a = LocationManifest.from_records(records, submission_id="sub-002")
    manifest_b = LocationManifest.from_records(records, submission_id="sub-002")

    assert manifest_a.manifest_hash == manifest_b.manifest_hash
    assert manifest_a.to_json() == manifest_b.to_json()


def test_location_and_manifest_are_immutable_after_creation():
    location = Location(**_sample_record("HQ", "100 Main St"))
    manifest = LocationManifest.from_records([location], submission_id="sub-003")

    with pytest.raises(FrozenInstanceError):
        manifest.submission_id = "other"

    with pytest.raises(TypeError):
        location.additional_fields["new_key"] = "new_value"

    with pytest.raises(AttributeError):
        manifest.locations.append(location)


def test_assert_count_raises_on_mismatch():
    manifest = LocationManifest.from_records([
        _sample_record("HQ", "100 Main St"),
    ])

    with pytest.raises(ValueError, match="Location count mismatch"):
        manifest.assert_count(2)


def test_manifest_json_roundtrip_preserves_hash_and_locations():
    manifest = LocationManifest.from_records(
        [
            _sample_record("HQ", "100 Main St"),
            _sample_record("Warehouse", "200 Market St"),
        ],
        submission_id="sub-004",
    )

    roundtripped = LocationManifest.from_json(manifest.to_json())

    assert roundtripped.manifest_hash == manifest.manifest_hash
    assert roundtripped.count == manifest.count
    assert [loc.id for loc in roundtripped.locations] == [loc.id for loc in manifest.locations]
    assert roundtripped.to_dict() == manifest.to_dict()


def test_manifest_from_json_rejects_hash_mismatch():
    manifest = LocationManifest.from_records([_sample_record("HQ", "100 Main St")])
    payload = manifest.to_dict()
    payload["manifest_hash"] = "0" * 64

    with pytest.raises(ValueError, match="hash mismatch"):
        LocationManifest.from_dict(payload)


def test_location_when_additional_fields_nested_should_be_deeply_immutable():
    location = Location(
        location_name="HQ",
        address_line_1="100 Main St",
        additional_fields={"outer": {"inner": ["a", "b"]}},
    )

    with pytest.raises(TypeError):
        location.additional_fields["outer"]["inner"] += ("c",)
