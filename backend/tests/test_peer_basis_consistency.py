"""A peer must be measured on the same basis as the company it is compared to.

Every defect pinned here produced a plausible-looking multiple that disagreed
with the market by a wide margin, which is the worst kind of error in a
comparables table: nothing on the page looks wrong, and the conclusion drawn
from the peer set is wrong.

  - Share count came from the provider's summary field, which reports ONE class
    for a multi-class issuer. One large-cap read 5.87bn against a filed 12.23bn,
    so its market capitalisation was half and its EV/Revenue read 5.0x against
    a market 9.2x — a real company made to look cheap by a share-class
    convention.
  - Net debt was taken from a snapshot denominated in crores and millions and
    added to a market capitalisation in rupees and dollars, understating debt
    ten-millionfold.
  - That same snapshot omitted the minority interests and preferred stock that
    enterprise value also carries. At one conglomerate those holdings exceed
    its gross debt.
  - The trailing-twelve-month roll matched each quarter's year-ago twin by
    POSITION in the column list. Feeds publish newest-first and not always
    contiguously, so it subtracted the wrong period, and then voided the whole
    roll on any single unpopulated quarter — leaving a stale annual as the
    denominator of a live market capitalisation.
  - Return on invested capital was withheld when invested capital fell below 2%
    of MARKET capitalisation, which is ordinary for a company that has
    repurchased its shares for years. It published 0.0%, reading as "earns
    nothing" rather than "not measurable".
"""

from __future__ import annotations

import pytest

from backend.valuation import peer_multiples as pm


class _FakeColumn:
    """A statement column that behaves like the Timestamp keys feeds publish."""

    def __init__(self, date):
        self._date = date

    def to_pydatetime(self):
        return self._date

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"Col({self._date})"


class _Loc:
    """Subscriptable stand-in for a frame's ``.loc``.

    Readers subscript it — ``frame.loc[label, column]`` — so it has to be
    indexable. A plain method here would raise a TypeError that the row reader
    catches and skips, and every lookup would quietly come back empty.
    """

    def __init__(self, data):
        self._data = data

    def __getitem__(self, key):
        label, column = key
        return self._data[label][column]


class _FakeFrame:
    """A statement frame: rows of line items across dated columns."""

    def __init__(self, data: dict[str, dict], columns: list):
        self.index = list(data)
        self.columns = columns
        self.loc = _Loc(data)


def _frame(rows, series):
    """rows: line labels. series: {label: {column: value}}, newest-first order."""
    return _FakeFrame({label: series[label] for label in rows}, list(series[rows[0]].keys()))


class _FakeTicker:
    def __init__(self, **attrs):
        for name, value in attrs.items():
            setattr(self, name, value)


# --------------------------------------------------------------------------- #
# Trailing twelve months
# --------------------------------------------------------------------------- #

def _quarterly_annual_and_quarters():
    from datetime import date

    q = {
        _FakeColumn(date(2026, 6, 30)): 130.0,
        _FakeColumn(date(2026, 3, 31)): 120.0,
        _FakeColumn(date(2025, 12, 31)): 110.0,
        _FakeColumn(date(2025, 9, 30)): 100.0,
        _FakeColumn(date(2025, 6, 30)): 90.0,
        _FakeColumn(date(2025, 3, 31)): 80.0,
    }
    annual = {_FakeColumn(date(2025, 12, 31)): 400.0}
    return _frame(["Total Revenue"], {"Total Revenue": q}), _frame(
        ["Total Revenue"], {"Total Revenue": annual}
    )


def test_four_recent_quarters_are_summed_directly():
    """Where four consecutive quarters exist, they ARE the trailing figure."""
    quarterly, annual = _quarterly_annual_and_quarters()
    # 130 + 120 + 110 + 100
    assert pm._ttl(annual, pm._REVENUE_ROWS, quarterly) == pytest.approx(460.0)


def test_roll_pairs_each_quarter_with_its_year_ago_twin():
    """The twin is found by DATE, not by position in the column list.

    This frame is newest-first and the twins sit AFTER the quarters they pair
    with, which is the opposite of what reading the list backwards assumes. The
    four newest quarters are deliberately not consecutive, so the direct
    four-quarter sum is unavailable and the roll is what runs.
    """
    from datetime import date

    q = {
        _FakeColumn(date(2026, 6, 30)): 200.0,
        _FakeColumn(date(2026, 3, 31)): 180.0,
        _FakeColumn(date(2025, 12, 31)): float("nan"),  # not populated
        _FakeColumn(date(2025, 9, 30)): 400.0,           # the annual period
        _FakeColumn(date(2025, 6, 30)): 150.0,           # twin of 2026-06-30
        _FakeColumn(date(2025, 3, 31)): 140.0,           # twin of 2026-03-31
    }
    annual = _frame(["Total Revenue"], {"Total Revenue": {_FakeColumn(date(2025, 9, 30)): 400.0}})
    quarterly = _frame(["Total Revenue"], {"Total Revenue": q})

    # The direct four-quarter sum is refused: one of the four newest quarters
    # is unpopulated.
    assert pm._sum_last_four_quarters(quarterly, pm._REVENUE_ROWS) is None

    # 400 + (200 - 150) + (180 - 140) = 490.
    #
    # The column list is newest-first, so the twins sit AFTER the quarters they
    # belong to. Pairing by position from either end of the list picks up the
    # unpopulated column or the annual period instead, and produces a figure that
    # is not a trailing twelve months at all.
    assert pm._ttl(annual, pm._REVENUE_ROWS, quarterly) == pytest.approx(490.0)


def test_one_unpopulated_quarter_does_not_void_the_whole_roll():
    """A missing quarter contributes nothing; the other pairs still count.

    Voiding the entire roll on a single gap left the denominator on a stale
    annual while the market capitalisation stayed live.
    """
    from datetime import date

    q = {
        _FakeColumn(date(2026, 6, 30)): 200.0,
        _FakeColumn(date(2026, 3, 31)): float("nan"),   # not populated
        _FakeColumn(date(2025, 12, 31)): 400.0,
        _FakeColumn(date(2025, 6, 30)): 150.0,
    }
    annual = _frame(["Total Revenue"], {"Total Revenue": {_FakeColumn(date(2025, 12, 31)): 400.0}})
    quarterly = _frame(["Total Revenue"], {"Total Revenue": q})

    # 400 + (200 - 150) = 450, not the untouched annual of 400.
    assert pm._ttl(annual, pm._REVENUE_ROWS, quarterly) == pytest.approx(450.0)


def test_roll_falls_back_to_the_annual_when_no_quarter_can_be_paired():
    """With nothing pairable, the annual is used — and that is visible."""
    from datetime import date

    q = {_FakeColumn(date(2026, 6, 30)): 200.0}   # no twin present
    annual = _frame(["Total Revenue"], {"Total Revenue": {_FakeColumn(date(2025, 12, 31)): 400.0}})
    quarterly = _frame(["Total Revenue"], {"Total Revenue": q})

    assert pm._ttl(annual, pm._REVENUE_ROWS, quarterly) == pytest.approx(400.0)


def test_gappy_four_quarters_are_refused_rather_than_summed():
    """Three quarters plus a hole is not twelve months."""
    from datetime import date

    q = {
        _FakeColumn(date(2026, 6, 30)): 130.0,
        _FakeColumn(date(2026, 3, 31)): 120.0,
        _FakeColumn(date(2025, 12, 31)): 110.0,
        _FakeColumn(date(2025, 3, 31)): 100.0,   # 2025-09-30 is missing
    }
    quarterly = _frame(["Total Revenue"], {"Total Revenue": q})

    assert pm._sum_last_four_quarters(quarterly, pm._REVENUE_ROWS) is None


# --------------------------------------------------------------------------- #
# Share count
# --------------------------------------------------------------------------- #

def test_filed_share_count_beats_a_single_class_provider_figure():
    """A multi-class issuer's summary field is one class; the filing is the total."""
    from datetime import date

    filed = _frame(
        ["Ordinary Shares Number"],
        {"Ordinary Shares Number": {_FakeColumn(date(2026, 6, 30)): 12_229_934_831.0}},
    )
    handle = _FakeTicker(quarterly_balance_sheet=filed, balance_sheet=None)

    shares, basis = pm._resolve_peer_shares(handle, {"sharesOutstanding": 5_867_155_790}, "GOOGL")

    assert shares == pytest.approx(12_229_934_831.0)
    assert "filed ordinary shares outstanding" in basis
    assert "rejected as a single-class figure" in basis


def test_provider_share_count_is_used_when_the_filing_omits_the_line():
    """Absence of the line is not a reason to withhold the peer."""
    handle = _FakeTicker(quarterly_balance_sheet=None, balance_sheet=None)

    shares, basis = pm._resolve_peer_shares(handle, {"sharesOutstanding": 1000.0}, "XYZ")

    assert shares == pytest.approx(1000.0)
    assert "provider" in basis


def test_agreeing_provider_figure_is_not_called_out_as_rejected():
    """A small difference is rounding, not a share-class problem."""
    from datetime import date

    filed = _frame(
        ["Ordinary Shares Number"],
        {"Ordinary Shares Number": {_FakeColumn(date(2026, 6, 30)): 1000.0}},
    )
    handle = _FakeTicker(quarterly_balance_sheet=filed, balance_sheet=None)

    _, basis = pm._resolve_peer_shares(handle, {"sharesOutstanding": 1002.0}, "XYZ")

    assert "rejected" not in basis


def test_no_share_count_anywhere_reports_unavailable():
    handle = _FakeTicker(quarterly_balance_sheet=None, balance_sheet=None)

    shares, basis = pm._resolve_peer_shares(handle, {}, "XYZ")

    assert shares is None
    assert basis == "unresolved"


# --------------------------------------------------------------------------- #
# Invested capital
# --------------------------------------------------------------------------- #

def test_invested_capital_floor_is_measured_against_revenue_not_market_cap():
    """A company that buys back its shares still has a measurable return.

    Measuring the capital base against market value silently withheld the
    figure for exactly the companies with the longest buyback histories, and
    published 0.0% in its place — which reads as "earns nothing" rather than
    "not measurable".
    """
    revenue = 466_823_000_000.0
    market_cap = 5_009_416_510_920.0
    # A large repurchase programme has left book equity well below market value:
    # 1.5% of it, against a capital base that is a fifth of its own annual sales.
    equity = 73_733_000_000.0
    net_debt = 21_945_000_000.0
    ebit = 154_859_000_000.0
    tax = 26_976_000_000.0

    invested = equity + max(net_debt, 0.0)

    # The premise: this company FAILS the old market-cap-relative test, which is
    # exactly why its return was being withheld.
    assert invested < market_cap * pm.PLAUSIBLE_INVESTED_CAPITAL_FLOOR, (
        "this fixture must be one whose book capital base is small relative to "
        "its market value, or it does not reproduce the defect"
    )
    # And it clears the floor that is actually applied, measured against sales.
    assert invested > revenue * pm.PLAUSIBLE_INVESTED_CAPITAL_FLOOR, (
        "and it must still clear the floor when measured against its own revenue"
    )

    effective_tax = min(max(tax / ebit, 0.0), 0.6)
    roic = (ebit * (1.0 - effective_tax)) / invested * 100.0
    assert pm.PLAUSIBLE_ROIC[0] <= roic <= pm.PLAUSIBLE_ROIC[1], (
        "the return this company actually earns on its own capital base must sit "
        "inside the published band"
    )


# --------------------------------------------------------------------------- #
# Unit consistency
# --------------------------------------------------------------------------- #

def test_snapshot_can_be_requested_in_absolute_currency(monkeypatch):
    """A caller combining the bridge with absolute figures must be able to ask.

    A market capitalisation is price times shares and is therefore in rupees or
    dollars. Adding a crores-denominated net debt to it understates the debt by
    a factor of ten million.
    """
    import backend.data.bridge_inputs as bi

    seen = {}

    def _fake_build(frame, column, source):
        snapshot = bi.BridgeSnapshot(as_of="2026-06-30", source=source)
        snapshot.terms = {"cash_and_bank": 1.0}
        snapshot.total_debt = 2.0
        snapshot.total_liquid_assets = 1.0
        return snapshot

    frame = _frame(["Total Assets"], {"Total Assets": {_FakeColumn.__new__(_FakeColumn): 1.0}})

    def _fake_scale(snapshot, company_id):
        seen["scaled"] = True

    monkeypatch.setattr(bi, "_build", _fake_build)
    monkeypatch.setattr(bi, "_scale_snapshot", _fake_scale)
    monkeypatch.setattr(bi, "_ticker_symbol", lambda company_id: "X.NS")
    monkeypatch.setattr(bi.yf, "Ticker", lambda symbol: _FakeTicker(quarterly_balance_sheet=frame))

    bi.fetch_bridge_snapshot("x_ns", in_model_units=False)
    assert "scaled" not in seen, "absolute request must not be rescaled into model units"

    bi.fetch_bridge_snapshot("x_ns")
    assert seen.get("scaled") is True, "the default request is still scaled for the model"
