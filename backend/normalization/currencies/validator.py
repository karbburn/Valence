from __future__ import annotations

"""
Currency and unit validation for canonical datapoints.

Design decision: unit scale strings are validated against a fixed whitelist
per market. The allowed markets and their associated unit scales are:
  - India market (INR): crores
  - US market (USD): millions
  - Any market: thousands (future-ready)

If an unrecognized unit scale is passed, a descriptive ValueError is raised
rather than silently defaulting, ensuring caller errors are caught early.
"""

from backend.normalization.taxonomy.models import CanonicalDatapoint

ALLOWED_CURRENCIES = {"INR", "USD"}
ALLOWED_UNITS = {"crores", "millions", "thousands"}


def validate_currencies_and_units(
    datapoints: list[CanonicalDatapoint],
    expected_currency: str = "INR",
    expected_units: str = "crores",
) -> dict:
    """Validates that all canonical datapoints match the expected currency and unit basis.

    Args:
        datapoints: Canonical datapoints to validate.
        expected_currency: ISO currency code for this company (e.g. "INR", "USD").
        expected_units: Unit scale string for this company (e.g. "crores", "millions").

    Raises:
        ValueError: If expected_currency or expected_units are not in the allowed whitelist.

    Returns:
        Summary dict with counts and any inconsistent datapoint IDs.
    """
    if expected_currency not in ALLOWED_CURRENCIES:
        raise ValueError(
            f"Unrecognized currency '{expected_currency}'. "
            f"Allowed values: {sorted(ALLOWED_CURRENCIES)}"
        )
    if expected_units not in ALLOWED_UNITS:
        raise ValueError(
            f"Unrecognized unit scale '{expected_units}'. "
            f"Allowed values: {sorted(ALLOWED_UNITS)}"
        )

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
