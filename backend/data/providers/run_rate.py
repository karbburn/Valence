"""Trailing-twelve-month figures, and the run rate a forecast should start from.

Two things live here because they must never disagree:

  - The TRAILING TWELVE MONTH construction itself, in one implementation. The
    peer path and the forecast anchor both need it, and when the two had their
    own copy a fix to one left the other computing a different denominator.

  - The CURRENT RUN RATE for a company: what it has actually traded in the last
    twelve months.

The run rate matters because a fiscal-year forecast anchored only to the last
REPORTED FISCAL YEAR can be projecting a year the business has already traded
past. A company whose fiscal year ended eight months ago and whose trailing
twelve months are a third above that year is not going to earn less next year
than it has just earned; a forecast built from the stale anchor says it will,
while still publishing a positive growth rate. The two published numbers then
contradict each other, which is the first thing an analyst checks.
"""

from __future__ import annotations

import logging
import warnings
from datetime import date, datetime, timedelta
from typing import Optional, Sequence

logger = logging.getLogger(__name__)

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    try:
        import yfinance as yf
    except ImportError:  # pragma: no cover - dependency guard
        yf = None


# Statement rows that state ordinary share counts, and rows that state revenue,
# are declared by the callers; this module only knows how to read a period.

# Consecutive quarters are between roughly two and four months apart. Anything
# outside that is a gap, and summing across a gap is not a trailing twelve
# months.
_MIN_QUARTER_GAP_DAYS = 60
_MAX_QUARTER_GAP_DAYS = 130

# The span four genuine consecutive quarters must cover.
#
# Gaps alone are not enough. With a 60-day floor, four stamps can be 180 days
# apart in total and still pass every individual gap test, so three of them can
# be a half-year's trading added up and labelled a trailing twelve months. Four
# real quarters span about 273 days; anything under 250 is not four quarters.
_MIN_FOUR_QUARTER_SPAN_DAYS = 250

# A period a whole year or more after the one before it is a different frequency,
# not another quarter. A frame mixing annual and quarterly columns — whose four
# newest date columns would otherwise pass every gap test, because an annual
# column sitting next to a quarter looks like a 90-day gap — would have an annual
# figure added to three quarters and publish five quarters' worth of revenue.
_MAX_PERIOD_GAP_DAYS = 200

# A year-ago quarter is found this close to 365 days from its quarter.
_TWIN_TOLERANCE_DAYS = 10

# How far the two most recent reported periods may differ before the most recent
# is treated as a different unit rather than a later period. Nine months apart
# for a calendar-year filer.
_MAX_PERIOD_SPAN_DAYS = 300


def _column_date(column):
    try:
        return column.to_pydatetime()
    except Exception:
        return None


def _row_value(frame, rows: Sequence[str], column) -> Optional[float]:
    if frame is None or column is None:
        return None
    for label in rows:
        try:
            if label not in frame.index:
                continue
            value = float(frame.loc[label, column])
        except Exception:
            continue
        if value != value:  # NaN
            continue
        return value
    return None


def sum_four_quarters(frame, rows: Sequence[str]) -> Optional[float]:
    """Trailing twelve months taken directly from four consecutive quarters.

    Preferred over rolling an annual figure forward, because it needs no
    year-ago subtraction and so cannot be defeated by a quarter the feed has not
    populated. Where the four most recent quarters are all present and evenly
    spaced, their sum IS the trailing twelve months.

    Returns None when the four newest are not all present or are not
    consecutive: a partial sum would look like a trailing figure without being
    one.
    """
    if frame is None:
        return None
    dates = [c for c in frame.columns if _column_date(c) is not None]
    if len(dates) < 4:
        return None

    newest_first = sorted(dates, key=_column_date, reverse=True)
    window = newest_first[:4]

    values: list[float] = []
    for column in window:
        value = _row_value(frame, rows, column)
        if value is None:
            return None
        values.append(value)

    stamps = sorted(_column_date(c) for c in window)
    gaps = [(stamps[i + 1] - stamps[i]).days for i in range(len(stamps) - 1)]
    if not all(_MIN_QUARTER_GAP_DAYS <= gap <= _MAX_QUARTER_GAP_DAYS for gap in gaps):
        return None

    # The window must span four quarters in total, not merely have three
    # acceptable gaps between it.
    span = (stamps[-1] - stamps[0]).days
    if span < _MIN_FOUR_QUARTER_SPAN_DAYS:
        return None

    # And no column may be a different frequency from its neighbour. An annual
    # column sitting among quarterly ones is about 275 days from the quarter
    # before it and about 90 from the one after, so only the span of the whole
    # window and the individual gaps together catch it.
    if any(gap > _MAX_PERIOD_GAP_DAYS for gap in gaps):
        return None

    return sum(values)


def roll_annual_forward(frame, rows: Sequence[str], quarterly) -> Optional[float]:
    """The latest annual figure rolled forward by each quarter since its year end.

    Used only where four consecutive quarters are unavailable. Each quarter is
    paired with its own year-ago twin and the pair added in; a quarter the feed
    has not populated, or whose twin is missing, simply contributes nothing,
    because the remaining pairs are still correct adjustments. The twin is found
    by DATE — feeds publish quarters newest-first and not always contiguously,
    so the neighbouring column is not reliably its twin.
    """
    if frame is None or len(getattr(frame, "columns", [])) == 0:
        return None
    annual_column = frame.columns[0]
    annual_value = _row_value(frame, rows, annual_column)
    if annual_value is None:
        return None

    if quarterly is None or len(getattr(quarterly, "columns", [])) == 0:
        return annual_value

    annual_end = _column_date(annual_column)
    if annual_end is None:
        return annual_value

    quarter_dates = [c for c in quarterly.columns if _column_date(c) is not None]
    rolled = annual_value
    applied = 0
    for column in quarter_dates:
        stamp = _column_date(column)
        if stamp is None or stamp <= annual_end:
            continue
        value = _row_value(quarterly, rows, column)
        if value is None:
            continue

        target = stamp - timedelta(days=365)
        twin = None
        for candidate in quarter_dates:
            candidate_date = _column_date(candidate)
            if candidate_date is None:
                continue
            if abs((candidate_date - target).days) <= _TWIN_TOLERANCE_DAYS:
                twin = candidate
                break
        if twin is None:
            continue
        twin_value = _row_value(quarterly, rows, twin)
        if twin_value is None:
            continue

        rolled += value - twin_value
        applied += 1

    if applied == 0:
        return annual_value
    return rolled if annual_value > 0 else annual_value


def trailing_twelve_months(frame, rows: Sequence[str], quarterly) -> Optional[float]:
    """Trailing twelve months for a statement line, however it can be built."""
    summed = sum_four_quarters(quarterly, rows)
    if summed is not None:
        return summed
    return roll_annual_forward(frame, rows, quarterly)


# --------------------------------------------------------------------------- #
# Current run rate
# --------------------------------------------------------------------------- #

_REVENUE_ROWS = ("Total Revenue", "Operating Revenue", "Gross Revenue")

# Symbol by company id, for the companies whose trailing revenue is read from a
# market feed. Resolution is by the company's own ticker where one is known, so
# this is not a list of companies but a list of symbols to ask about.
def _symbol_for(company_id: str) -> str:
    """The market symbol this company's figures are read from.

    Resolved by the same function the price chain uses, so the run rate is read
    for the identical instrument the quoted price refers to. Deriving it from the
    company id instead — treating the id's suffix as a market — produced a
    bare ticker for every Indian listing, which is not a symbol the feed
    recognises, so the run rate silently came back empty for the whole country.
    """
    from backend.data.providers.market_data import _yf_ticker_for
    from backend.models.spec.metadata import resolve_market

    try:
        market = resolve_market(company_id)
        ticker = company_id.split("_")[0].upper()
        return _yf_ticker_for(company_id, market, ticker)
    except Exception:
        return company_id.split("_")[0].upper()


# Run rates change every reporting day, so the cache is keyed by the day it was
# read rather than reused indefinitely.
_RUN_RATE_CACHE: dict[str, tuple[str, Optional[float], str]] = {}


def current_run_rate_revenue(company_id: str) -> tuple[Optional[float], str]:
    """Revenue actually traded in the last twelve months, in absolute currency.

    Returns (revenue, basis). `basis` states the period the figure covers, so a
    reader can tell a fresh number from a stale one, and says so plainly when
    the figure could not be sourced — in which case the caller falls back to the
    reported fiscal year rather than inventing a run rate.
    """
    if yf is None:
        return None, "no market feed available"

    today = date.today().isoformat()
    cached = _RUN_RATE_CACHE.get(company_id)
    if cached and cached[0] == today:
        return cached[1], cached[2]

    symbol = _symbol_for(company_id)
    try:
        handle = yf.Ticker(symbol)
        annual = getattr(handle, "income_stmt", None)
        quarterly = getattr(handle, "quarterly_income_stmt", None)
        revenue = trailing_twelve_months(annual, _REVENUE_ROWS, quarterly)
    except Exception as exc:
        logger.info("Run rate unavailable for %s (%s): %s", company_id, symbol, exc)
        _RUN_RATE_CACHE[company_id] = (today, None, f"not sourceable ({type(exc).__name__})")
        return None, f"not sourceable ({type(exc).__name__})"

    if revenue is None or revenue <= 0:
        _RUN_RATE_CACHE[company_id] = (today, None, "no trailing revenue reported")
        return None, "no trailing revenue reported"

    # State the period the figure ACTUALLY covers.
    #
    # Not whichever statement happens to be the most recent. Feeds commonly carry
    # only four or five quarters, so there is no year-ago twin to roll against and
    # the figure is the un-rolled annual — which is a fiscal year, not a trailing
    # twelve months. Labelling that "trailing twelve months to <latest quarter>"
    # states a period the number does not cover, and the string is published
    # verbatim in the growth source where a reader would take it at face value.
    basis = _period_basis(revenue, annual, quarterly)
    _RUN_RATE_CACHE[company_id] = (today, revenue, basis)
    return revenue, basis


def _period_basis(revenue, annual, quarterly) -> str:
    """Name the period the figure covers, chosen by how it was actually built.

    The construction decides the label, not the most recent date available. If
    the four most recent quarters were summed, it is a trailing twelve months;
    if the annual could not be rolled forward it is a fiscal year, and calling it
    a trailing figure would misdescribe it in a string a reader sees.
    """
    if sum_four_quarters(quarterly, _REVENUE_ROWS) is not None:
        return f"trailing twelve months to {_newest_date(quarterly)}"
    return f"reported fiscal year to {_newest_date(annual)} (not a trailing twelve months)"


def _newest_date(frame) -> str:
    newest = max(
        (c for c in getattr(frame, "columns", []) if _column_date(c) is not None),
        key=_column_date,
        default=None,
    )
    return _column_date(newest).date().isoformat() if newest is not None else "unknown"


# A trailing twelve months is compared with the last reported fiscal year, which
# covers almost the same period. The two therefore have to be within a small
# multiple of each other: a business does not quadruple or collapse to a
# twentyieth inside one year.
#
# This is also the guard against a UNIT mismatch, which is what a run rate read
# in the wrong currency looks like. One listing reported its trailing revenue in
# its domestic currency against a model denominated in dollars, thirty-seven
# times too large; another came back a hundredth of its reported year. Both
# would otherwise be taken as fact and would set a growth rate that is arithmetically
# valid and economically absurd.
#
# The upper edge is EXCLUSIVE. At exactly 4x the floor would publish a year-one
# growth rate of +300%, which is arithmetically what the ratio says and not a
# thing a business does inside a year. Past the band the reading is not a fast
# company; it is a different unit or a different company.
_RUN_RATE_SANE_BAND = (0.25, 4.0)


def run_rate_is_comparable(run_rate: Optional[float], reported: Optional[float]) -> bool:
    """True when the run rate and the reported year are in the same units.

    A reading outside the band is a unit error or a different entity, and the
    caller falls back to the reported fiscal year rather than acting on it.
    """
    if not run_rate or not reported or reported <= 0 or run_rate <= 0:
        return False
    ratio = run_rate / reported
    return _RUN_RATE_SANE_BAND[0] <= ratio < _RUN_RATE_SANE_BAND[1]


def run_rate_advanced_beyond(run_rate: Optional[float], reported: Optional[float]) -> bool:
    """True when the trailing twelve months exceed the last reported fiscal year.

    This is the condition under which a fiscal-year forecast anchored only to
    that year is projecting a period the business has already traded past.
    """
    if not run_rate or not reported or reported <= 0:
        return False
    return run_rate > reported
