"""Drive the real reader with a stubbed feed and check the dates it actually builds.

This file exists because six of seven mutations of the first attempt at
`test_one_period_one_end.py` SURVIVED. Those tests called `filed_period_ends` directly
and asserted on the source text, so they never noticed when `fetch_and_parse_us_live`
did:

    filed_period_ends(company_id)      # fetched
    filed_ends = {}                    # and discarded

The function under test was correct and the caller was wrong, which is the whole
defect. So the caller is what gets exercised here: a fake yfinance whose columns are
named by the calendar month end, a store holding the filer's real fiscal dates, and an
assertion on the `period_end_date` of the RawDatapoints that come out.

NVIDIA's FY2024 is the worked example, because it is the case that was wrong:

    feed column   2024-01-31   (Yahoo names columns by month end)
    filed          2024-01-28   (NVIDIA's own fiscal year end)
"""

from __future__ import annotations

import pathlib
import sqlite3
import sys
from datetime import date

import pandas as pd

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.data.ingestion import us_live  # noqa: E402

SCHEMA = (
    "CREATE TABLE raw_datapoints ("
    "id TEXT PRIMARY KEY, company_id TEXT NOT NULL, metric_raw TEXT NOT NULL,"
    " period_label TEXT NOT NULL, period_end_date TEXT NOT NULL, value REAL NOT NULL,"
    " currency TEXT NOT NULL, units TEXT NOT NULL, source TEXT NOT NULL,"
    " source_location TEXT NOT NULL, status TEXT NOT NULL, update_date TEXT NOT NULL,"
    " superseded_by_id TEXT)"
)

# Yahoo names its columns by the last day of the calendar month.
FEED_COLUMNS = [date(2024, 1, 31), date(2025, 1, 31), date(2026, 1, 31)]

# NVIDIA's own fiscal year ends, from its filings.
FILED = {"FY24": date(2024, 1, 28), "FY25": date(2025, 1, 26), "FY26": date(2026, 1, 25)}


class _FakeTicker:
    """Just enough yfinance for `fetch_and_parse_us_live`."""

    def __init__(self, _ticker):
        # One row per caption the maps ask for, valued so nothing is NaN.
        def frame(rows):
            return pd.DataFrame(
                {c: [float(i + 1) for i in range(len(rows))] for c in FEED_COLUMNS},
                index=rows,
            )

        self.income_stmt = frame(["Total Revenue", "Net Income"])
        self.financials = self.income_stmt
        self.balance_sheet = frame(["Total Assets", "Cash And Cash Equivalents"])
        self.cashflow = frame(["Operating Cash Flow"])
        self.info = {"financialCurrency": "USD"}


class _FakeYf:
    @staticmethod
    def Ticker(ticker):  # noqa: N802 - mirrors the yfinance API
        return _FakeTicker(ticker)


def _filed_store(tmp_path, company_id: str, filed: dict[str, date]) -> pathlib.Path:
    path = pathlib.Path(tmp_path) / "valence.db"
    con = sqlite3.connect(str(path))
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO raw_datapoints (id, company_id, metric_raw, period_label,"
        " period_end_date, value, currency, units, source, source_location, status,"
        " update_date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("id-%s-%s" % (company_id, label), company_id, "Some caption", label,
             ped.isoformat(), 1.0, "USD", "millions", "sec_edgar", "loc",
             "reported", "2026-10-03T00:00:00")
            for label, ped in filed.items()
        ],
    )
    con.commit()
    con.close()
    return path


def _build(tmp_path, monkeypatch, company_id="nvda_us", filed=FILED):
    path = _filed_store(tmp_path, company_id, filed)
    monkeypatch.setattr("backend.data.universe.store.DB_PATH", path, raising=False)
    monkeypatch.setattr(us_live, "yf", _FakeYf)
    return us_live.fetch_and_parse_us_live(company_id)


class TestTheReaderStoresTheFiledDate:
    def test_no_datapoint_carries_the_feeds_month_end(self, tmp_path, monkeypatch):
        """The invariant, asserted on the objects the reader actually returns.

        Every one of these came from a feed column named 2024-01-31 / 2025-01-31 /
        2026-01-31. None of those dates may survive into the model when the filing
        disagrees, because the filed rows for the same periods are already in the
        store carrying the real ones.
        """
        dps = _build(tmp_path, monkeypatch)
        assert dps, "the reader produced nothing, so nothing was verified"

        by_period = {}
        for dp in dps:
            by_period.setdefault(dp.period_label, set()).add(dp.period_end_date)

        for period_label, dates in sorted(by_period.items()):
            assert len(dates) == 1, (
                "%s carries %d different period-end dates: %s"
                % (period_label, len(dates), sorted(dates))
            )
            assert dates == {FILED[period_label]}, (
                "%s ends %s but NVIDIA filed %s -- the feed's month end survived"
                % (period_label, dates.pop(), FILED[period_label])
            )

    def test_the_feed_month_end_appears_nowhere(self, tmp_path, monkeypatch):
        dps = _build(tmp_path, monkeypatch)
        month_ends = set(FEED_COLUMNS)
        leaked = sorted({dp.period_end_date for dp in dps} & month_ends)
        assert not leaked, (
            "these feed month ends reached the model: %s -- the lookup was not "
            "consulted" % leaked
        )

    def test_a_period_the_filing_never_filed_keeps_the_feed_date(self, tmp_path,
                                                                monkeypatch):
        """A filer with no SEC rows must still be dated.

        `tsm_us` and the other foreign private issuers have nothing in the store, so
        the feed's date is the only date there is. Dropping it would leave every
        period undated, which is worse than a month end.
        """
        dps = _build(tmp_path, monkeypatch, company_id="tsm_us", filed={})
        assert dps, "a feed-only filer produced nothing"
        ends = {dp.period_end_date for dp in dps}
        assert ends == set(FEED_COLUMNS), (
            "with no filing to defer to, the reader should keep the feed's dates, "
            "got %s" % sorted(ends)
        )

    def test_a_partial_filing_dates_only_what_it_filed(self, tmp_path, monkeypatch):
        """One filed period must not drag the others with it."""
        dps = _build(tmp_path, monkeypatch, filed={"FY25": date(2025, 1, 26)})
        by_period = {}
        for dp in dps:
            by_period.setdefault(dp.period_label, set()).add(dp.period_end_date)
        assert by_period["FY25"] == {date(2025, 1, 26)}
        assert by_period["FY24"] == {date(2024, 1, 31)}, (
            "FY24 was never filed, so its date should be the feed's 2024-01-31, "
            "got %s" % sorted(by_period["FY24"])
        )
