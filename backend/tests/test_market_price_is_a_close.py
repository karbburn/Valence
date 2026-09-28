"""A cached price must be a close, not whatever the market was doing when it was read.

The provider chain prefers a daily close, and every price the engine publishes
carries the session it was read from. Both of those were fine. What was not fine
was deciding when a cached price was still good.

Freshness was tested against the local calendar date. On a machine 5:30 east of
UTC the local date is already the next day while the exchange is still trading, so
an entry written at 00:19 local on the Tuesday after a Monday session is 18:49 UTC
on Monday: mid-session, holding a live price under Monday's bar date. The date
test passed, so that live price was served for the rest of the day and the
valuation compared its implied price against a number the market never printed at
the close. Five of the largest companies were frozen that way, each between 0.3
and 1.0 percent from its own close.

Nothing about those entries looked wrong. The price was positive, it was dated,
it named a real session, and it came from the preferred source.

The rule is now that a price is usable only if it is the close of the last
completed session on its own exchange. That question needs no wall clock, no local
offset and no write time: a feed labels a live print with the session it is
trading in, so the only thing that distinguishes a close from a mid-session print
is whether that session has finished, and the exchange calendar knows that.

Three earlier attempts at this rule are what the tests below pin:

- A single 20:00 UTC cutoff. Correct for US equities only in summer. The US close
  is 21:00 UTC under standard time, so a price read at 20:05 UTC in January was
  served with the market still open. And Indian equities close at 10:00 UTC, so
  an Indian price read at 11:57 UTC could never satisfy a 20:00 test and was
  refetched on every call for the rest of the day.
- Comparing the entry's write time to a cutoff. It needs a timezone-aware
  timestamp, and the stored one was naive local time, which made it an hour out
  under daylight saving.
- Counting days back to find the last session. It counted Saturdays and Sundays,
  so a correct Friday close was refused from Saturday evening through Monday's
  own close, a two-day blackout every weekend.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from backend.data.providers.market_data import (
    _cache_is_settled,
    _entry_session_date,
    _exchange_close_instant,
    last_completed_session,
)

TUE_AFTER_CLOSE = datetime(2026, 9, 29, 22, 0, tzinfo=timezone.utc)
TUE_BEFORE_CLOSE = datetime(2026, 9, 29, 19, 0, tzinfo=timezone.utc)


def _entry(session: str, *, with_field: bool = True) -> dict:
    """A cache entry whose price came from the given session."""
    data = {
        "company_id": "nvda_us",
        "ticker": "NVDA",
        "market": "us",
        "price": {
            "value": 228.86,
            "source": "yfinance_history",
            "fetch_date": session,
            "provenance_note": f"yfinance daily close for NVDA ({session})",
        },
        "timestamp": "2026-09-29T06:40:00.000000+00:00",
    }
    if with_field:
        data["session_date"] = session
    return {"fetch_date": "2026-09-29", "data": data}


# The defect, as it shipped. Written at 00:19 local, which is 18:49 UTC on the
# Monday, with Monday's bar date and a live price.
MID_SESSION_ENTRY = _entry("2026-09-28")


# --- the session is read from a field, not from prose -----------------------


def test_the_session_is_read_from_the_recorded_field():
    assert _entry_session_date(_entry("2026-09-28")) == date(2026, 9, 28)


def test_a_legacy_entry_without_the_field_falls_back_to_its_note():
    """Entries written before the field existed carry the date only in prose.

    They are still usable, which is why the fallback exists. It is a fallback
    rather than the source because a sentence is not a contract: reword it and
    the parse fails silently, and the price is refetched forever.
    """
    assert _entry_session_date(_entry("2026-09-28", with_field=False)) == date(2026, 9, 28)


def test_the_field_wins_over_the_note_when_they_disagree():
    """A reworded or stale note cannot redirect the rule."""
    entry = _entry("2026-09-28")
    entry["data"]["price"]["provenance_note"] = "some rewritten note (1999-01-01)"
    assert _entry_session_date(entry) == date(2026, 9, 28)


def test_an_entry_with_no_session_anywhere_is_refetched():
    entry = _entry("2026-09-28", with_field=False)
    entry["data"]["price"]["provenance_note"] = "provider quote"
    assert _entry_session_date(entry) is None
    assert not _cache_is_settled(entry, "us", TUE_AFTER_CLOSE)


# --- settled means the close of the last completed session ------------------


def test_a_price_from_todays_closed_session_is_served():
    assert _cache_is_settled(_entry("2026-09-29"), "us", TUE_AFTER_CLOSE)


def test_a_price_from_yesterdays_session_is_served_before_todays_close():
    assert _cache_is_settled(_entry("2026-09-28"), "us", TUE_BEFORE_CLOSE)


def test_a_price_from_todays_open_session_is_refetched():
    """The defect. The price carries today's date, so only the calendar can tell."""
    assert not _cache_is_settled(_entry("2026-09-29"), "us", TUE_BEFORE_CLOSE)


def test_the_shipped_mid_session_entry_is_refetched():
    assert not _cache_is_settled(MID_SESSION_ENTRY, "us", TUE_AFTER_CLOSE)


def test_a_price_behind_the_last_completed_session_is_refetched():
    assert not _cache_is_settled(_entry("2026-09-24"), "us", TUE_AFTER_CLOSE)


# --- the US close moves with daylight saving --------------------------------


def test_the_us_close_is_21_utc_in_standard_time():
    """21:00 UTC under EST. A fixed 20:00 UTC cutoff is wrong here."""
    assert _exchange_close_instant("us", date(2026, 1, 15)) == datetime(
        2026, 1, 15, 21, 0, tzinfo=timezone.utc
    )


def test_the_us_close_is_20_utc_in_daylight_time():
    assert _exchange_close_instant("us", date(2026, 7, 15)) == datetime(
        2026, 7, 15, 20, 0, tzinfo=timezone.utc
    )


def test_a_january_quote_at_2005_utc_is_still_refetched():
    """20:05 UTC in January is mid-session. The market does not close until 21:00."""
    moment = datetime(2026, 1, 15, 20, 5, tzinfo=timezone.utc)
    assert not _cache_is_settled(_entry("2026-01-15"), "us", moment)


def test_a_july_quote_at_2005_utc_is_settled():
    """The same wall-clock minute, in the same year, on the other side of DST."""
    moment = datetime(2026, 7, 15, 20, 5, tzinfo=timezone.utc)
    assert _cache_is_settled(_entry("2026-07-15"), "us", moment)


# --- the Indian market closes five hours earlier ----------------------------


def test_the_indian_close_is_1000_utc():
    assert _exchange_close_instant("india", date(2026, 9, 28)) == datetime(
        2026, 9, 28, 10, 0, tzinfo=timezone.utc
    )


def test_an_indian_price_read_after_its_close_is_served():
    """11:57 UTC, nearly two hours after NSE shut.

    A single 20:00 UTC cutoff made this unserviceable at every instant of the day,
    so Indian prices were refetched on every call. 34 of the 156 cached entries
    sat in that band.
    """
    moment = datetime(2026, 9, 28, 11, 57, tzinfo=timezone.utc)
    assert _cache_is_settled(_entry("2026-09-28"), "india", moment)


def test_an_indian_price_read_before_its_close_is_refetched():
    moment = datetime(2026, 9, 28, 8, 0, tzinfo=timezone.utc)
    assert not _cache_is_settled(_entry("2026-09-28"), "india", moment)
    # The previous session is the one that has closed.
    assert _cache_is_settled(_entry("2026-09-25"), "india", moment)


def test_the_two_markets_are_independent():
    """An Indian close is settled hours before a US close, on the same day."""
    moment = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
    assert _cache_is_settled(_entry("2026-09-28"), "india", moment)
    assert not _cache_is_settled(_entry("2026-09-28"), "us", moment)


# --- weekends ---------------------------------------------------------------


def test_a_friday_close_is_served_all_weekend():
    """Counting days back made this a two-day refusal every weekend."""
    for day in (26, 27):  # Saturday, Sunday
        moment = datetime(2026, 9, day, 22, 0, tzinfo=timezone.utc)
        assert last_completed_session("us", moment) == date(2026, 9, 25)
        assert _cache_is_settled(_entry("2026-09-25"), "us", moment)


def test_a_weekend_never_reports_itself_as_a_session():
    """Saturday has no close, so it cannot be the last completed session."""
    saturday = datetime(2026, 9, 26, 22, 0, tzinfo=timezone.utc)
    assert last_completed_session("us", saturday) != saturday.date()


def test_friday_evening_settles_immediately_after_the_close():
    moment = datetime(2026, 9, 25, 20, 30, tzinfo=timezone.utc)
    assert last_completed_session("us", moment) == date(2026, 9, 25)


def test_monday_morning_serves_friday_until_monday_closes():
    moment = datetime(2026, 9, 28, 14, 0, tzinfo=timezone.utc)  # 10:00 ET, open
    assert last_completed_session("us", moment) == date(2026, 9, 25)
    assert _cache_is_settled(_entry("2026-09-25"), "us", moment)
    assert not _cache_is_settled(_entry("2026-09-28"), "us", moment)


# --- robustness -------------------------------------------------------------


def test_an_unknown_market_falls_back_without_raising():
    moment = datetime(2026, 9, 29, 22, 0, tzinfo=timezone.utc)
    assert isinstance(last_completed_session("atlantis", moment), date)


def test_a_broken_session_date_does_not_raise():
    entry = _entry("2026-09-28")
    entry["data"]["session_date"] = "not-a-date"
    assert _entry_session_date(entry) is None
    assert not _cache_is_settled(entry, "us", TUE_AFTER_CLOSE)


def test_the_rule_does_not_consult_the_write_time():
    """The write time is the one thing that cannot distinguish the two cases.

    An entry written at 18:49 UTC on the session and one written at 22:00 UTC on it
    carry the same evidence, so the rule ignores it. Pinned because a rule that
    starts reading the timestamp again is a rule that will need the timestamp to
    be timezone-aware on every machine that reads it.

    The instant is Tuesday before the close, so Monday's session is still the last
    completed one and both entries are judged on the same footing.
    """
    early = _entry("2026-09-28")
    early["data"]["timestamp"] = "2026-09-28T18:49:14.628186+00:00"
    late = _entry("2026-09-28")
    late["data"]["timestamp"] = "2026-09-28T22:00:00+00:00"
    assert _cache_is_settled(early, "us", TUE_BEFORE_CLOSE)
    assert _cache_is_settled(late, "us", TUE_BEFORE_CLOSE)


def test_every_session_of_a_normal_week_resolves():
    """A full week at a fixed late hour, so a weekend cannot slip through."""
    for offset in range(7):
        day = datetime(2026, 9, 28, 22, 0, tzinfo=timezone.utc) + timedelta(days=offset)
        session = last_completed_session("us", day)
        assert isinstance(session, date)
        assert session <= day.date()
        assert session.weekday() < 5, f"{day.date()} resolved to a weekend session"


def test_the_fetcher_reaches_the_rule(monkeypatch):
    """The rule has to be consulted, not merely present.

    An earlier version of this check existed and was correct on its own, and was
    still never called: the fetcher kept comparing fetch_date with the local date.
    A test on the helper cannot see that, so the call is pinned here.
    """
    from backend.data.providers import market_data as md

    consulted = []
    monkeypatch.setattr(
        md, "_cache_is_settled",
        lambda cached, market="us", now=None: consulted.append(market) or True,
    )

    entry = _entry("2026-09-28")
    entry["data"].update(
        shares_outstanding={
            "value": 24147.0, "source": "yfinance", "fetch_date": "2026-09-28",
            "provenance_note": "filed ordinary shares outstanding",
        },
        beta={
            "value": 1.67, "source": "registry", "fetch_date": "2026-09-28",
            "provenance_note": "registry benchmark beta",
        },
        risk_free_rate={
            "value": 5.242, "source": "yfinance", "fetch_date": "2026-09-28",
            "provenance_note": "10-Year US Treasury yield",
        },
        equity_risk_premium={
            "value": 4.5, "source": "market_default", "fetch_date": "2026-09-28",
            "provenance_note": "US market default",
        },
    )
    monkeypatch.setattr(md, "_load_cache", lambda: {"nvda_us": entry})

    def _refuse(*_a, **_kw):
        raise AssertionError("the network was reached; the cache should have answered")

    for fetcher in ("_fetch_yfinance_history", "_fetch_yahoo_chart", "_fetch_yfinance"):
        monkeypatch.setattr(md, fetcher, _refuse)

    data = md.get_company_market_data(company_id="nvda_us", market="us", ticker="NVDA")

    assert consulted, "the fetcher served the cache without consulting the rule"
    assert data.price.value == 228.86
