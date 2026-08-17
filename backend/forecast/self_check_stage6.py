from __future__ import annotations

"""
Self-check for Stage 6: Debt Schedule & Share Count.

Acceptance criteria:
  1. Debt schedule closing balance == FY26 historical borrowings for all 5 periods x 3 scenarios.
  2. reconcile() returns True for the Infosys carry-forward debt schedule.
  3. reconcile() returns False for a deliberately broken synthetic schedule.
  4. share_count.get_diluted("FY26") equals the official metadata share count (412.45 Cr).
  5. Forecast share count FY27-FY31 equals FY26 (flat assumption).
  6. ModelSpecification serializes/deserializes without losing debt_schedule or share_count.
"""

from backend.forecast.debt import DebtPeriod, DebtSchedule, build_debt_schedule, reconcile
from backend.forecast.pipeline import run
from backend.models.spec.model_specification import ModelSpecification


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"Stage 6 self-check FAILED: {msg}")
    print(f"ok: {msg}")


def main() -> None:
    print("Running Stage 6 checks...")
    spec = run()

    from backend.models.spec.forecast import FORECAST_PERIODS

    # ------------------------------------------------------------------ #
    # 1. Debt schedule carries FY26 historical borrowings flat across all periods
    # ------------------------------------------------------------------ #
    _assert(len(spec.debt_schedule) == 3, f"3 debt schedules present (got {len(spec.debt_schedule)})")
    exp_opening = spec.historicals.get_value("canonical.bs.borrowings", "FY26") or 0.0
    for ds in spec.debt_schedule:
        for p in ds.periods:
            _assert(
                abs(p.closing_balance - exp_opening) < 0.01,
                f"Debt closing == FY26 borrowings ({exp_opening:.0f}) scenario={ds.scenario} period={p.period} (got {p.closing_balance})",
            )

    # ------------------------------------------------------------------ #
    # 2. reconcile() returns True for Infosys schedule
    # ------------------------------------------------------------------ #
    for ds in spec.debt_schedule:
        _assert(reconcile(ds), f"reconcile() True for scenario={ds.scenario}")

    # ------------------------------------------------------------------ #
    # 3. reconcile() returns False for a deliberately broken synthetic case
    # ------------------------------------------------------------------ #
    broken_period = DebtPeriod(
        period="FY27",
        opening_balance=1000.0,
        draws=500.0,
        scheduled_repayment=200.0,
        optional_repayment=0.0,
        closing_balance=999.0,   # deliberately wrong: should be 1300.0
        interest_expense=0.0,
        interest_rate=0.0,
    )
    broken_schedule = DebtSchedule(scenario="synthetic", interest_rate=0.0, periods=[broken_period])
    _assert(not reconcile(broken_schedule), "reconcile() correctly returns False for broken synthetic case")

    # ------------------------------------------------------------------ #
    # 4. Share count FY26 = official metadata share count (EPS not in canonical data)
    # ------------------------------------------------------------------ #
    _assert(spec.share_count is not None, "share_count is populated")
    fy26_diluted = spec.share_count.get_diluted("FY26")
    _assert(fy26_diluted is not None, "share_count FY26 diluted is present")
    from backend.models.spec.metadata import get_metadata_for_company
    meta = get_metadata_for_company(spec.metadata.company_id)
    _assert(
        abs(fy26_diluted - meta.shares_outstanding) < 0.01,
        f"share_count FY26 diluted = {fy26_diluted:.4f} Cr (expected ~{meta.shares_outstanding:.4f} Cr)",
    )

    # ------------------------------------------------------------------ #
    # 5. Forecast share count FY27-FY31 equals FY26 (flat)
    # ------------------------------------------------------------------ #
    for p in FORECAST_PERIODS:
        fcst_diluted = spec.share_count.get_diluted(p)
        _assert(
            fcst_diluted is not None and abs(fcst_diluted - fy26_diluted) < 0.001,
            f"share_count {p} diluted == FY26 value ({fcst_diluted} vs {fy26_diluted})",
        )

    # ------------------------------------------------------------------ #
    # 6. Round-trip serialization preserves debt_schedule and share_count
    # ------------------------------------------------------------------ #
    raw = spec.serialize()
    spec2 = ModelSpecification.deserialize(raw)
    _assert(len(spec2.debt_schedule) == 3, "Round-trip: debt_schedule intact")
    _assert(spec2.share_count is not None, "Round-trip: share_count intact")
    _assert(
        abs((spec2.share_count.get_diluted("FY26") or 0) - fy26_diluted) < 0.001,
        "Round-trip: share_count FY26 value preserved",
    )

    # ------------------------------------------------------------------ #
    # Summary
    # ------------------------------------------------------------------ #
    print(f"\n  Stage 6 summary:")
    print(f"    Debt schedules      : {len(spec.debt_schedule)} scenarios (carry-forward of FY26 borrowings)")
    print(f"    Share count periods : {len(spec.share_count.periods)}")
    print(f"    FY26 diluted shares : {fy26_diluted:.2f} Cr")
    print(f"    FY31 diluted shares : {spec.share_count.get_diluted('FY31'):.2f} Cr (flat assumption)")

    print("\nALL STAGE 6 SELF-CHECKS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
