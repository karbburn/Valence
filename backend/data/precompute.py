from __future__ import annotations

"""
Precomputation Batch Script for Valence.

Simulates the scheduled GitHub Actions batch pipeline by pre-compiling the
complete ModelSpecification (historicals -> forecast -> valuation -> QA) and
saving it to a static JSON cache file.
"""

import json
from pathlib import Path

from backend.forecast.pipeline import run as run_forecast_pipeline
from backend.models.statements.pipeline import run as run_historical
from backend.validation.pipeline import run_qa
from backend.valuation.pipeline import run_valuation

import os
import sys

PRECOMPUTE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PRECOMPUTE_DIR.parent.parent
CACHE_DIR = PROJECT_ROOT / "backend" / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def run_precompute(company_id: str | None = None) -> Path:
    """Compile model specification and write to JSON cache file."""
    target_id = company_id or os.getenv("PRECOMPANY_ID", "infy_infy")
    print(f"Precompiling ModelSpecification for '{target_id}'...")

    try:
        # 1. Run Historical 3-Statement Model
        hist_model = run_historical(target_periods=["FY24", "FY25", "FY26"], company_id=target_id)

        # 2. Run Forecast Engine
        forecast_spec = run_forecast_pipeline(hist_model)

        # 3. Run Valuation Engine
        valuation_spec = run_valuation(forecast_spec)

        # 4. Run QA model validation checks
        final_spec = run_qa(valuation_spec)
    except Exception as e:
        print(f"Error: Precomputation failed during pipeline execution: {e}")
        raise

    # 5. Serialize and write to cache file
    cache_file = CACHE_DIR / f"{target_id}.json"
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(final_spec.serialize(), f, indent=2)
    except Exception as e:
        print(f"Error: Failed to write cache file to {cache_file}: {e}")
        raise

    print(f"ok: Precomputed ModelSpecification written to {cache_file} ({cache_file.stat().st_size} bytes)")
    return cache_file


if __name__ == "__main__":
    run_precompute()

