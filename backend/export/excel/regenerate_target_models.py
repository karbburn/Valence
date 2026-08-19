from __future__ import annotations

"""
Script to regenerate all 4 target models (MSFT, NVDA, ONGC, TCS)
through the full pipeline (ingest -> normalize -> forecast -> value -> QA -> Excel export).
"""

from pathlib import Path
import shutil

from backend.data.batch import ensure_company_ingested
from backend.export.excel.exporter import export_model_to_excel
from backend.forecast.pipeline import run as run_forecast_pipeline
from backend.models.statements.pipeline import run as run_historical
from backend.validation.pipeline import run_qa
from backend.valuation.pipeline import run_valuation

TARGET_COMPANIES = [
    ("msft_us", "msft_valuation_model.xlsx"),
    ("nvda_us", "nvda_valuation_model.xlsx"),
    ("ongc_ongc", "ongc_valuation_model.xlsx"),
    ("tcs_tcs", "tcs_valuation_model.xlsx"),
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
OUTPUT_DIR = PROJECT_ROOT / "backend" / "export" / "output"


def main():
    print("=======================================================================")
    print("REGENERATING VALUATION MODELS FOR TARGET UNIVERSE")
    print("=======================================================================\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    for company_id, filename in TARGET_COMPANIES:
        print(f"--> Processing {company_id} ({filename})...")
        ensure_company_ingested(company_id)

        hist_model = run_historical(company_id=company_id)
        forecast_spec = run_forecast_pipeline(historical_model=hist_model)
        val_spec = run_valuation(forecast_spec)
        final_spec = run_qa(val_spec)

        out_path = OUTPUT_DIR / filename
        export_model_to_excel(final_spec, out_path=out_path)

        # Copy to assets/
        asset_path = ASSETS_DIR / filename
        shutil.copyfile(out_path, asset_path)
        print(f"    [SUCCESS] Exported {filename} to {asset_path} ({asset_path.stat().st_size / 1024.0:.1f} KB)\n")

    print("=======================================================================")
    print("ALL 4 VALUATION MODELS SUCCESSFULLY REGENERATED!")
    print("=======================================================================")


if __name__ == "__main__":
    main()
