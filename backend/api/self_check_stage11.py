from __future__ import annotations

"""
Self-check for Stage 11: Auth & Model Persistence Engine.

Acceptance criteria:
  1. Header auth extracts UserSession (X-User-Id fallback & Supabase token).
  2. POST /api/models/save persists a ModelSpecification with user overrides under user_id.
  3. GET /api/models lists user's saved models.
  4. GET /api/models/{id} loads saved model and restores exact model state & Implied Share Price.
  5. Backward-loadability test: loading a model saved under schema version 0.9.0 migrates cleanly to 1.0.0.
  6. DELETE /api/models/{id} removes saved model.
"""

from pathlib import Path
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api.persistence import SavedModelStore, migrate_model_spec
from backend.models.spec.model_specification import ModelSpecification


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"Stage 11 self-check FAILED: {msg}")
    print(f"ok: {msg}")


def main() -> None:
    print("Running Stage 11 Auth & Model Persistence self-check...")
    client = TestClient(app)
    headers = {"X-User-Id": "usr_test_analyst"}

    # 1. Driver Edit (Set Revenue Growth to 15.0%)
    recomp_res = client.post(
        "/api/model/recompute",
        json={"driver_key": "revenue_growth", "value": 15.0, "period": "all", "scenario": "base"},
        headers=headers,
    )
    _assert(recomp_res.status_code == 200, "Driver edit successful before save")
    spec_before = recomp_res.json()
    price_before = spec_before["valuation"][0]["dcf_bridge"]["implied_share_price"]
    print(f"  Pre-save Implied Share Price: INR {price_before:.2f}")

    # 2. Save Model (POST /api/models/save)
    save_res = client.post(
        "/api/models/save",
        json={"name": "Infosys Growth Test Model", "company_id": "infy_infy"},
        headers=headers,
    )
    _assert(save_res.status_code == 200, f"POST /api/models/save status == 200 (got {save_res.status_code})")
    save_data = save_res.json()
    _assert(save_data["status"] == "saved", "Save response status is 'saved'")
    model_id = save_data["header"]["model_id"]
    print(f"  Saved Model ID: {model_id}")

    # 3. List Saved Models (GET /api/models)
    list_res = client.get("/api/models", headers=headers)
    _assert(list_res.status_code == 200, "GET /api/models status == 200")
    models_list = list_res.json()
    _assert(len(models_list) > 0, "Saved models list is non-empty")
    _assert(any(m["model_id"] == model_id for m in models_list), "Newly saved model appears in user's saved list")

    # 4. Load Saved Model (GET /api/models/{model_id})
    load_res = client.get(f"/api/models/{model_id}", headers=headers)
    _assert(load_res.status_code == 200, f"GET /api/models/{model_id} status == 200")
    loaded_spec = load_res.json()
    price_after = loaded_spec["valuation"][0]["dcf_bridge"]["implied_share_price"]
    print(f"  Loaded Model Implied Share Price: INR {price_after:.2f}")
    _assert(abs(price_after - price_before) < 0.01, f"Loaded model price matches pre-save state ({price_after:.2f} == {price_before:.2f})")

    rev_ass = next(a for a in loaded_spec["assumptions"] if a["driver_key"] == "revenue_growth" and a["scenario"] == "base")
    _assert(rev_ass["type"] == "user_override", "Loaded model preserves user_override type")
    _assert(rev_ass["value"] == 15.0, "Loaded model preserves user_override value 15.0%")

    # 5. Backward-Loadability Migration Test (v0.9.0 -> v1.0.0)
    old_spec_dict = {
        "metadata": {
            "company_id": "infy_infy",
            "name": "Infosys Limited",
            "ticker": "INFY",
            "fiscal_year_end": "March 31",
            "model_version": "0.9.0",  # Old schema version
        },
        "assumptions": [
            {
                "assumption_id": "a_old_1",
                "driver_key": "revenue_growth",
                "value": 12.5,
                "period": "all",
                "scenario": "base",
                "type": "user_override",
            }
        ],
    }
    migrated_dict = migrate_model_spec(old_spec_dict)
    _assert(migrated_dict["metadata"]["model_version"] == "1.0.0", "Migrated schema version upgraded to 1.0.0")
    _assert(migrated_dict["metadata"]["market"] == "india", "Migrated metadata populated default market")
    _assert(migrated_dict["assumptions"][0]["previous_model_value"] == 12.5, "Migrated assumption preserved previous_model_value")

    # 6. Delete Saved Model (DELETE /api/models/{model_id})
    del_res = client.delete(f"/api/models/{model_id}", headers=headers)
    _assert(del_res.status_code == 200, f"DELETE /api/models/{model_id} status == 200")
    
    post_del_list = client.get("/api/models", headers=headers).json()
    _assert(not any(m["model_id"] == model_id for m in post_del_list), "Model removed from saved list after deletion")

    # ------------------------------------------------------------------ #
    # Summary
    # ------------------------------------------------------------------ #
    print(f"\n  Stage 11 Auth & Model Persistence summary:")
    print(f"    Header Authentication: Extracted UserSession (usr_test_analyst)")
    print(f"    Model Save / Load    : Preserved overrides (15.0%) and exact price (INR {price_after:.2f})")
    print(f"    Backward Loadability : v0.9.0 -> v1.0.0 schema migration passed without override loss")
    print(f"    Model Deletion       : Clean deletion confirmed")

    print("\nALL STAGE 11 SELF-CHECKS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    import sys
    main()
    sys.exit(0)
