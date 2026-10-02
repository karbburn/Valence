"""A period has one end, and the filing is the authority on it.

`us_live` stored `period_end_date=c_d`, where `c_d` is a yfinance COLUMN HEADER. Yahoo
names columns by the last day of the calendar month, so every 52/53-week filer got a
month end instead of its own fiscal date, and one statement ended up holding two
different period-end dates for the same period:

    intc_us   FY24  filed 2024-12-28   feed 2024-12-31
    nvda_us   FY24  filed 2024-01-28   feed 2024-01-31
    qcom_us   FY25  filed 2025-09-28   feed 2025-09-30

For two filers the dates fall in DIFFERENT MONTHS, which is what shows this is not a
rounding difference:

    sbux_us   FY23  filed 2023-10-01   feed 2023-09-30
    tjx_us    FY24  filed 2024-02-03   feed 2024-01-31

Measured across the store: 18 of the shipped US models, 47 periods.

The tests build a store and read it back through the real function. Asserting the
expression that picks the date would pass against a `filed_period_ends` that returns
nothing, and this defect is precisely a lookup that was never consulted.
"""

from __future__ import annotations

import pathlib
import re
import sqlite3
import sys

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


def _store(tmp, rows) -> pathlib.Path:
    """rows: (company_id, source, period_label, period_end_date)."""
    path = pathlib.Path(tmp) / "valence.db"
    con = sqlite3.connect(str(path))
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO raw_datapoints (id, company_id, metric_raw, period_label,"
        " period_end_date, value, currency, units, source, source_location, status,"
        " update_date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("id%d" % i, cid, "Some caption", pl, ped, 1.0, "USD", "millions",
             src, "loc", "reported", "2026-10-03T00:00:00")
            for i, (cid, src, pl, ped) in enumerate(rows)
        ],
    )
    con.commit()
    con.close()
    return path


class TestTheFiledDateIsFound:
    """The real function, against a real store."""

    def test_a_filed_period_end_is_returned(self, tmp_path, monkeypatch):
        path = _store(tmp_path, [
            ("nvda_us", "sec_edgar", "FY24", "2024-01-28"),
            ("nvda_us", "yfinance_live", "FY24", "2024-01-31"),
        ])
        monkeypatch.setattr(
            "backend.data.universe.store.DB_PATH", path, raising=False)
        assert us_live.filed_period_ends("nvda_us") == {"FY24": _d("2024-01-28")}

    def test_the_feed_never_contributes_the_date(self, tmp_path, monkeypatch):
        """The invariant: the answer comes from the filing and only the filing."""
        path = _store(tmp_path, [
            ("nvda_us", "sec_edgar", "FY24", "2024-01-28"),
            ("nvda_us", "yfinance_live", "FY24", "2024-01-31"),
            ("nvda_us", "yfinance_live", "FY25", "2025-01-31"),
        ])
        monkeypatch.setattr(
            "backend.data.universe.store.DB_PATH", path, raising=False)
        got = us_live.filed_period_ends("nvda_us")
        assert got["FY24"] == _d("2024-01-28")
        # FY25 exists only in the feed, so the filing has no opinion and the function
        # must say nothing rather than invent a date.
        assert "FY25" not in got, (
            "a period the filing never mentioned was given a date anyway, so the "
            "feed's month end would be presented as if it were filed"
        )

    def test_one_company_does_not_leak_into_another(self, tmp_path, monkeypatch):
        path = _store(tmp_path, [
            ("nvda_us", "sec_edgar", "FY24", "2024-01-28"),
            ("intc_us", "sec_edgar", "FY24", "2024-12-28"),
        ])
        monkeypatch.setattr(
            "backend.data.universe.store.DB_PATH", path, raising=False)
        assert us_live.filed_period_ends("nvda_us")["FY24"] == _d("2024-01-28")
        assert us_live.filed_period_ends("intc_us")["FY24"] == _d("2024-12-28")

    def test_the_most_frequent_filed_date_wins(self, tmp_path, monkeypatch):
        """One stray row must not move a period.

        A restatement leaves the old date behind in some stores, so the mode is taken
        rather than the first row, the last row, or the latest date.

        The fixture is arranged so that LATEST and MOST-FREQUENT disagree, which the
        first version of this test got wrong: it had 2025-09-28 twice and 2024-09-29
        once, where the latest date and the mode are the same value. It passed against
        `sorted(dates)[-1]` -- a mutation check reported that as a survivor, and the
        test was at fault rather than the code.
        """
        path = _store(tmp_path, [
            ("qcom_us", "sec_edgar", "FY25", "2024-09-29"),
            ("qcom_us", "sec_edgar", "FY25", "2024-09-29"),
            ("qcom_us", "sec_edgar", "FY25", "2025-09-28"),
        ])
        monkeypatch.setattr(
            "backend.data.universe.store.DB_PATH", path, raising=False)
        assert us_live.filed_period_ends("qcom_us")["FY25"] == _d("2024-09-29"), (
            "the most frequent filed date should win; 2025-09-28 is later but "
            "appears once, so a latest-date rule would pick it"
        )

    def test_a_missing_store_is_not_an_error(self, tmp_path, monkeypatch):
        """`tsm_us` has no SEC rows at all, and must still build."""
        monkeypatch.setattr(
            "backend.data.universe.store.DB_PATH",
            pathlib.Path(tmp_path) / "absent.db", raising=False)
        assert us_live.filed_period_ends("tsm_us") == {}


class TestTheReaderStoresTheFiledDate:
    def test_both_datapoint_sites_use_the_lookup(self):
        """There were TWO sites storing `c_d`, not one.

        `_extract_from_df` and `_extract_borrowings` each built a RawDatapoint with
        `period_end_date=c_d`. Fixing one would have left borrowings carrying the feed
        date while every other line carried the filed one -- the same disagreement,
        half-fixed, and harder to spot than either state alone.
        """
        src = (REPO / "backend" / "data" / "ingestion" / "us_live.py").read_text(
            encoding="utf-8")
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        code = re.sub(r"#.*$", "", code, flags=re.M)

        assert "period_end_date=c_d" not in code, (
            "a datapoint still stores the feed's column header as its period end, so "
            "that line disagrees with the filing in the same statement"
        )
        assert "period_end_date=filed_ends.get(" in code, (
            "the filed date is never consulted when building a datapoint, so "
            "`filed_period_ends` exists and is never called on this path"
        )
        # Once per RawDatapoint construction site.
        assert code.count("period_end_date=filed_ends.get(") == 2, (
            "expected both datapoint sites to use the lookup, found %d"
            % code.count("period_end_date=filed_ends.get(")
        )

    def test_the_lookup_is_resolved_once_per_build(self):
        """Reading the store per datapoint would be a query per line item.

        The value cannot change during a build, and a per-datapoint lookup would make
        a slow reader slower for no benefit.
        """
        src = (REPO / "backend" / "data" / "ingestion" / "us_live.py").read_text(
            encoding="utf-8")
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        code = re.sub(r"#.*$", "", code, flags=re.M)
        assert code.count("filed_period_ends(company_id)") == 1, (
            "the lookup should happen once per build; found %d call sites"
            % code.count("filed_period_ends(company_id)")
        )

    def test_a_period_without_a_filing_keeps_the_feed_date(self):
        """The fallback must remain, or feed-only filers lose their dates entirely.

        `tsm_us` and the other foreign private issuers have no SEC rows, so there is
        no filed date and the feed's is the only one. Returning None there and using it
        unconditionally would leave every period undated.
        """
        import inspect

        src = inspect.getsource(us_live.fetch_and_parse_us_live)
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        code = re.sub(r"#.*$", "", code, flags=re.M)
        assert re.search(
            r"filed_ends\.get\(\s*period_lbl,\s*c_d if isinstance\(c_d, date\)",
            code,
        ), (
            "the lookup has no fallback to the feed's date, so a filer with no SEC "
            "rows would produce datapoints with today's date or none at all"
        )


def _d(iso: str):
    from datetime import date

    return date.fromisoformat(iso)
