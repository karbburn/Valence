"""A served model must be priced against the close that has actually happened.

The in-memory model cache evicts by capacity, and the capacity is larger than the
number of onboarded companies, so nothing is ever evicted from it. A spec
therefore lived for the whole life of the process with its market price frozen at
the moment it was first requested. The code that recomputes valuation against live
quotes only ever ran on the single request that missed the cache.

Nothing in the served output revealed this. The price carried a real session date
and a real source, and it was simply yesterday's close, indefinitely. The
statement still foots, the checks still pass, and the implied upside is measured
against a close the market moved past hours or days ago.

A spec is now discarded when a newer session has closed since it was valued. The
question is the same one the quote cache asks, asked with the same calendar, so
the two cannot disagree about which close is current.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from backend.api.routes import (
    _cached_spec_session,
    _spec_is_current_for_session,
)
from backend.data.providers.market_data import last_completed_session

SESSION = "2026-09-28"  # a Monday


def _spec(session: str):
    """A spec shaped like a real one, carrying a reverse DCF quote date."""

    class _Reverse:
        market_price_date = session
        market_price = 228.86
        market_price_source = "yfinance_history"

    class _Output:
        reverse_dcf = _Reverse()

    class _Spec:
        valuation = [_Output()]

    return _Spec()


MONDAY_AFTER_CLOSE = datetime(2026, 9, 28, 22, 0, tzinfo=timezone.utc)
TUESDAY_BEFORE_CLOSE = datetime(2026, 9, 29, 19, 0, tzinfo=timezone.utc)
TUESDAY_AFTER_CLOSE = datetime(2026, 9, 29, 22, 0, tzinfo=timezone.utc)


def test_the_session_a_spec_was_valued_against_is_readable():
    assert _cached_spec_session(_spec(SESSION)) == SESSION


def test_a_spec_valued_against_the_last_closed_session_is_served():
    assert _spec_is_current_for_session(_spec(SESSION), "us", MONDAY_AFTER_CLOSE)


def test_a_spec_is_dropped_once_a_newer_session_closes():
    """The defect. Tuesday's close printed, and Monday's price was still being served."""
    assert not _spec_is_current_for_session(_spec(SESSION), "us", TUESDAY_AFTER_CLOSE)


def test_mondays_spec_survives_until_tuesdays_close():
    """Not before. Tuesday's session is live during the day, so Monday is current."""
    assert _spec_is_current_for_session(_spec(SESSION), "us", TUESDAY_BEFORE_CLOSE)


def test_a_weekend_does_not_invalidate_a_spec():
    """Saturday and Sunday have no session, so Friday's close is still the last one.

    Counting days here would invalidate every model on Saturday morning and not
    replace it until Monday's close, which is a two-day window serving a stale
    price for every company at once.
    """
    friday = "2026-09-25"
    spec = _spec(friday)
    for day in (26, 27):
        moment = datetime(2026, 9, day, 22, 0, tzinfo=timezone.utc)
        assert _spec_is_current_for_session(spec, "us", moment), (
            f"a Friday close was invalidated on {moment:%A}"
        )


def test_a_spec_with_no_recorded_session_is_never_trusted():
    """A price that does not say which close it came from cannot be shown current."""
    assert _cached_spec_session(_spec(None)) is None
    assert not _spec_is_current_for_session(_spec(None), "us", TUESDAY_AFTER_CLOSE)


def test_the_two_markets_close_at_different_times():
    """An Indian company is current on a session the US market has not closed yet.

    Testing both markets against one clock is how an Indian price would be
    invalidated every US trading morning and re-fetched for nothing. At 12:00 UTC
    the Indian session has closed and the American one has not, so Monday is the
    last completed session in India and Friday still is in the United States.
    """
    moment = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
    monday_spec = _spec("2026-09-28")
    assert _spec_is_current_for_session(monday_spec, "india", moment)
    # The same spec is ahead of the US market, whose Monday close has not printed.
    assert not _spec_is_current_for_session(monday_spec, "us", moment)
    # And the Friday spec the US market is actually on is current there.
    assert _spec_is_current_for_session(_spec("2026-09-25"), "us", moment)


def test_a_spec_from_the_future_is_not_accepted():
    """A session that has not happened cannot have a close."""
    spec = _spec("2026-12-31")
    assert not _spec_is_current_for_session(spec, "us", TUESDAY_AFTER_CLOSE)


def test_every_trading_day_of_a_week_keeps_a_fresh_spec_fresh():
    """Walks a full week of trading days so a weekend cannot hide in a gap.

    A spec valued against the last completed session must survive until the next
    one closes. The weekend is the interesting case: 2026-10-03 is a Saturday, so
    a spec dated that day is dated against a session that never happened and is
    not current, while a Friday spec stays current across it.
    """
    friday = datetime(2026, 10, 2, 22, 0, tzinfo=timezone.utc)
    for offset in (0, 1, 2, 3, 4):  # Fri, Sat, Sun, Mon, Tue
        day = friday + timedelta(days=offset)
        last_session = last_completed_session("us", day)
        spec = _spec(last_session.isoformat())
        assert _spec_is_current_for_session(spec, "us", day), (
            f"a spec valued against {last_session} was invalidated at {day:%Y-%m-%d %H:%M}Z"
        )
