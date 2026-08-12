from __future__ import annotations

from backend.normalization.taxonomy.models import CanonicalDatapoint


def validate_currencies_and_units(
    datapoints: list[CanonicalDatapoint],
    expected_currency: str = "INR",
    expected_units: str = "crores",
) -> dict:
    """Validates that all canonical datapoints match the expected currency and unit basis.

    Returns:
        Summary dict with counts and any inconsistent datapoint IDs.
    """
    inconsistent: list[dict] = []

    for dp in datapoints:
        if dp.currency != expected_currency or dp.units != expected_units:
            inconsistent.append({
                "id": dp.id,
                "canonical_key": dp.canonical_key,
                "currency": dp.currency,
                "units": dp.units,
                "expected_currency": expected_currency,
                "expected_units": expected_units,
            })

    return {
        "total_checked": len(datapoints),
        "inconsistent_count": len(inconsistent),
        "inconsistent_datapoints": inconsistent,
        "is_valid": len(inconsistent) == 0,
    }
