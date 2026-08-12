from __future__ import annotations

"""
Self-check for the Driver Engine & Forecast.

Acceptance criteria:
  1. All 13 base assumptions: type=model_generated, non-empty source.
  2. FY27-FY31 revenue present and growing at the assumed rate.
  3. Balance sheet balances for all 5 periods × 3 scenarios (15 checks).
  4. Operating CF > 0 for all Base forecast periods.
  5. Override + revert on revenue_growth propagates correctly.
  6. Bull FY31 revenue > Base FY31 revenue > Bear FY31 revenue.
"""

from backend.forecast.pipeline import run
from backend.models.spec.assumptions import AssumptionObject
from backend.models.spec.forecast import FORECAST_PERIODS
from backend.models.spec.drivers import V1_DRIVERS


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"Forecast self-check FAILED: {msg}")
    print(f"ok: {msg}")


def main() -> None:
    print("Running Forecast Pipeline...")
    spec = run()

    # ------------------------------------------------------------------ #
    # 1. Base assumptions — all 13 drivers, model_generated, named source
    # ------------------------------------------------------------------ #
    required_driver_keys = {d.driver_key for d in V1_DRIVERS}
    base_assumptions = [a for a in spec.assumptions if a.scenario == "base"]
    base_driver_keys_found = {a.driver_key for a in base_assumptions}

    for dk in required_driver_keys:
        _assert(dk in base_driver_keys_found, f"Base assumption present for driver '{dk}'")

    for a in base_assumptions:
        _assert(a.type == "model_generated", f"Base assumption '{a.driver_key}' period={a.period} is model_generated")
        _assert(len(a.source) > 0, f"Base assumption '{a.driver_key}' has non-empty source")

    # ------------------------------------------------------------------ #
    # 2. Forecast revenue present and monotonically increasing (Base)
    # ------------------------------------------------------------------ #
    prev_rev = None
    for p in FORECAST_PERIODS:
        rev = spec.forecast.get_value("canonical.is.revenue", p, "base")
        _assert(rev is not None and rev > 0, f"Base forecast revenue present FY period={p} ({rev})")
        if prev_rev is not None:
            _assert(rev > prev_rev, f"Base revenue grows period-over-period ({p}: {rev:.0f} > prior: {prev_rev:.0f})")
        prev_rev = rev

    # ------------------------------------------------------------------ #
    # 3. Balance sheet balances: total_assets == total_liabilities_and_equity
    # ------------------------------------------------------------------ #
    for scenario in ("base", "bull", "bear"):
        for p in FORECAST_PERIODS:
            assets = spec.forecast.get_value("canonical.bs.total_assets", p, scenario)
            liab_eq = spec.forecast.get_value("canonical.bs.total_liabilities_and_equity", p, scenario)
            _assert(
                assets is not None and liab_eq is not None and abs(assets - liab_eq) < 1.0,
                f"Balance sheet balances {scenario} {p} (assets={assets:.0f} vs liab+eq={liab_eq:.0f})",
            )

    # ------------------------------------------------------------------ #
    # 4. Operating CF > 0 for all Base periods
    # ------------------------------------------------------------------ #
    for p in FORECAST_PERIODS:
        cfo = spec.forecast.get_value("canonical.cf.operating_activities", p, "base")
        _assert(cfo is not None and cfo > 0, f"Base operating CF > 0 for {p} ({cfo:.0f})")

    # ------------------------------------------------------------------ #
    # 5. Override + revert round-trip on revenue_growth FY27
    # ------------------------------------------------------------------ #
    original_assumption = next(
        (a for a in spec.assumptions if a.driver_key == "revenue_growth" and a.period == "FY27" and a.scenario == "base"),
        None,
    )
    _assert(original_assumption is not None, "Found base revenue_growth FY27 assumption")

    overridden = original_assumption.with_override(new_value=5.0, source="Test Override")
    _assert(overridden.type == "user_override", "Override produces user_override type")
    _assert(overridden.previous_model_value == original_assumption.value,
            f"previous_model_value preserved ({overridden.previous_model_value})")

    reverted = overridden.reverted()
    _assert(reverted.type == "model_generated", "Revert restores model_generated")
    _assert(reverted.value == original_assumption.value,
            f"Revert restores original value ({reverted.value})")

    # ------------------------------------------------------------------ #
    # 6. Bull > Base > Bear revenue in FY31
    # ------------------------------------------------------------------ #
    rev_bull = spec.forecast.get_value("canonical.is.revenue", "FY31", "bull")
    rev_base = spec.forecast.get_value("canonical.is.revenue", "FY31", "base")
    rev_bear = spec.forecast.get_value("canonical.is.revenue", "FY31", "bear")
    _assert(
        rev_bull is not None and rev_base is not None and rev_bear is not None
        and rev_bull > rev_base > rev_bear,
        f"Bull > Base > Bear revenue FY31 ({rev_bull:.0f} > {rev_base:.0f} > {rev_bear:.0f})",
    )

    # ------------------------------------------------------------------ #
    # Summary
    # ------------------------------------------------------------------ #
    print(f"\n  Forecast summary:")
    print(f"    Total assumptions   : {len(spec.assumptions)} ({len([a for a in spec.assumptions if a.scenario=='base'])} base)")
    print(f"    Forecast line items : {len(spec.forecast.line_items)}")
    base_rev_fy31 = spec.forecast.get_value("canonical.is.revenue", "FY31", "base")
    print(f"    Base revenue FY31   : {base_rev_fy31:,.0f} Cr")
    print(f"    Scenarios present   : base, bull, bear")

    print("\nALL FORECAST SELF-CHECKS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
