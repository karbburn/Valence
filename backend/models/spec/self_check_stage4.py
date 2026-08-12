from __future__ import annotations

import json
from pathlib import Path

from backend.models.spec.assumptions import AssumptionObject
from backend.models.spec.drivers import V1_DRIVERS
from backend.models.spec.metadata import INFOSYS_METADATA
from backend.models.spec.model_specification import ModelSpecification
from backend.models.spec.qa import V1_CHECK_NAMES
from backend.models.statements.pipeline import run as run_historical


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"Model Spec self-check FAILED: {msg}")
    print(f"ok: {msg}")


def main() -> None:
    print("Building HistoricalModel...")
    hist_model = run_historical(target_periods=["FY24", "FY25", "FY26"])

    print("\nBuilding ModelSpecification from HistoricalModel...")
    spec = ModelSpecification.from_historical_model(hist_model, metadata=INFOSYS_METADATA)

    # ------------------------------------------------------------------ #
    # 1. Metadata checks
    # ------------------------------------------------------------------ #
    _assert(spec.metadata.company_id == "infy_infy", "metadata.company_id correct")
    _assert(spec.metadata.market == "india", "metadata.market correct")
    _assert(spec.metadata.model_version == "1.0.0", f"model_version == 1.0.0 ({spec.metadata.model_version})")
    _assert(spec.metadata.generation_date is not None, "metadata.generation_date set")

    # ------------------------------------------------------------------ #
    # 2. Historicals section
    # ------------------------------------------------------------------ #
    for period in ("FY24", "FY25", "FY26"):
        rev = spec.historicals.get_value("canonical.is.revenue", period)
        ebitda = spec.historicals.get_value("canonical.is.ebitda", period)
        np_ = spec.historicals.get_value("canonical.is.net_profit", period)
        assets = spec.historicals.get_value("canonical.bs.total_assets", period)

        _assert(rev is not None and rev > 0, f"historicals: revenue present {period} ({rev})")
        _assert(ebitda is not None and ebitda > 0, f"historicals: ebitda present {period} ({ebitda})")
        _assert(np_ is not None and np_ > 0, f"historicals: net_profit present {period} ({np_})")
        _assert(assets is not None and assets > 0, f"historicals: total_assets present {period} ({assets})")

    ebitda_item = spec.historicals.get("canonical.is.ebitda", "FY26")
    _assert(ebitda_item is not None and ebitda_item.status == "derived", "EBITDA status == 'derived'")
    _assert(ebitda_item is not None and ebitda_item.derivation_rule is not None, "EBITDA derivation_rule attached")

    all_items_with_lineage = [i for i in spec.historicals.line_items if len(i.source_datapoint_ids) > 0]
    _assert(len(all_items_with_lineage) > 0, f"Source lineage IDs present ({len(all_items_with_lineage)} items)")

    # ------------------------------------------------------------------ #
    # 3. Drivers — all 13 V1 drivers registered
    # ------------------------------------------------------------------ #
    _assert(len(spec.drivers) == len(V1_DRIVERS), f"All {len(V1_DRIVERS)} drivers registered ({len(spec.drivers)})")
    driver_keys = {d.driver_key for d in spec.drivers}
    for required in ["revenue_growth", "ebitda_margin", "tax_rate", "dso_days",
                     "capex_pct_revenue", "wacc.cost_of_equity", "terminal_growth_rate", "exit_ev_multiple"]:
        _assert(required in driver_keys, f"Driver '{required}' registered")

    # ------------------------------------------------------------------ #
    # 4. AssumptionObject — override + revert round-trip
    # ------------------------------------------------------------------ #
    original = AssumptionObject(
        driver_key="revenue_growth",
        value=10.5,
        period="FY27",
        scenario="base",
        type="model_generated",
        source="3yr historical CAGR",
    )
    overridden = original.with_override(new_value=11.0, source="Analyst")
    reverted = overridden.reverted()

    _assert(original.type == "model_generated", "original is model_generated")
    _assert(overridden.type == "user_override", "override applied correctly")
    _assert(overridden.value == 11.0, "overridden value correct")
    _assert(overridden.previous_model_value == 10.5, "previous_model_value preserved on override")
    _assert(reverted.type == "model_generated", "reverted to model_generated")
    _assert(reverted.value == 10.5, "reverted value matches original")
    _assert(reverted.previous_model_value is None, "previous_model_value cleared after revert")

    # ------------------------------------------------------------------ #
    # 5. Scenarios — base/bull/bear scaffolds present
    # ------------------------------------------------------------------ #
    scenario_ids = {s.scenario_id for s in spec.scenarios}
    for required_sc in ("base", "bull", "bear"):
        _assert(required_sc in scenario_ids, f"Scenario '{required_sc}' present")

    # ------------------------------------------------------------------ #
    # 6. Valuation scaffolds — one per scenario
    # ------------------------------------------------------------------ #
    val_scenarios = {v.scenario for v in spec.valuation}
    for required_sc in ("base", "bull", "bear"):
        _assert(required_sc in val_scenarios, f"Valuation scaffold for '{required_sc}' present")

    # ------------------------------------------------------------------ #
    # 7. JSON serialization round-trip — no data loss
    # ------------------------------------------------------------------ #
    raw_json = spec.serialize()
    _assert(isinstance(raw_json, str) and len(raw_json) > 0, "serialized to JSON string")

    spec2 = ModelSpecification.deserialize(raw_json)
    rev_after = spec2.historicals.get_value("canonical.is.revenue", "FY26")
    rev_before = spec.historicals.get_value("canonical.is.revenue", "FY26")
    _assert(rev_after == rev_before, f"Round-trip: FY26 revenue preserved ({rev_before} -> {rev_after})")

    schema_version_in_json = json.loads(raw_json).get("_schema_version")
    _assert(schema_version_in_json == "1.0.0", f"Schema version in JSON envelope ({schema_version_in_json})")

    # ------------------------------------------------------------------ #
    # 8. No renderer-specific fields leaked into schema
    # ------------------------------------------------------------------ #
    json_str_lower = raw_json.lower()
    for forbidden in ("excel_", "cell_ref", "web_color", "display_order", "sheet_name"):
        _assert(forbidden not in json_str_lower, f"No renderer leak: '{forbidden}' absent from schema JSON")

    # ------------------------------------------------------------------ #
    # 9. QA scaffold structure correct
    # ------------------------------------------------------------------ #
    _assert(spec.qa.summary_label == "NOT RUN", f"QA scaffold: summary_label == 'NOT RUN' ({spec.qa.summary_label})")

    print(f"\n  Spec summary:")
    print(f"    Historicals line items : {len(spec.historicals.line_items)}")
    print(f"    Periods covered        : {spec.historicals.periods}")
    print(f"    Drivers registered     : {len(spec.drivers)}")
    print(f"    Scenarios              : {[s.scenario_id for s in spec.scenarios]}")
    print(f"    Model version          : {spec.metadata.model_version}")
    print(f"    JSON size (chars)      : {len(raw_json):,}")

    print("\nALL MODEL SPECIFICATION SELF-CHECKS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()

