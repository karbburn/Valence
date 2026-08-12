from datetime import date, datetime
from tempfile import TemporaryDirectory
from pathlib import Path

from backend.data.store import RawDatapoint, save_datapoints, query_datapoints


def _datapoints() -> list[RawDatapoint]:
    return [
        RawDatapoint(
            company_id="infy_nse",
            metric_raw="Revenue from Operations",
            period_label="FY24",
            period_end_date=date(2024, 3, 31),
            value=153670.0,
            currency="INR",
            units="crores",
            source="screener",
            source_location="IncomeStatement!A3:B4",
            status="reported",
            update_date=datetime(2024, 6, 1, 10, 0, 0),
        ),
        RawDatapoint(
            company_id="infy_nse",
            metric_raw="Net Profit",
            period_label="FY24",
            period_end_date=date(2024, 3, 31),
            value=26391.0,
            currency="INR",
            units="crores",
            source="screener",
            source_location="IncomeStatement!A12:B13",
            status="reported",
        ),
    ]


def main():
    with TemporaryDirectory() as tmp:
        db = Path(tmp) / "valence.db"
        ds = _datapoints()
        save_datapoints(db, ds)
        back = query_datapoints(db, "infy_nse")
        assert len(back) == 2, f"expected 2, got {len(back)}"
        a = back[0]
        assert a.metric_raw == "Revenue from Operations"
        assert a.value == 153670.0
        assert a.period_end_date == date(2024, 3, 31)
        assert a.source == "screener"
        assert a.status == "reported"
        by_period = query_datapoints(db, "infy_nse", period_label="FY24")
        assert len(by_period) == 2
        by_source = query_datapoints(db, "infy_nse", source="bse_filing")
        assert len(by_source) == 0
        print("round-trip ok")


if __name__ == "__main__":
    main()