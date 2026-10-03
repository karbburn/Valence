"""The `site` gate must not report a correctly-cached page as a missing figure.

`/stock/[ticker]/page.tsx` declares `revalidate = 3600` and `serverApi.ts` hands that to
next's fetch cache, so a page is DELIBERATELY served up to an hour stale. The gate called
`/api/model/{cid}` directly, got a freshly revalued answer, and demanded the two be equal
at all times -- a condition the product does not promise. Sub-1% drift was reported as

    FAIL  nvda_us: page /stock/NVDA does not contain its implied price 156.89
          -- the route answers 200 but the figure is not on it

which is a different finding with a different fix, and it fails on correct behaviour, so
it gets muted. It blocked six clean audit loops.

The distinction is drawn from the page's OWN quote date, which is real and was verified in
the committed components rather than assumed:

  * `JsonLd.tsx:169` emits `temporalCoverage: priceDate`, the raw
    `reverse_dcf.market_price_date` -- a `YYYY-MM-DD` string, not an ISO timestamp.
  * `page.tsx:82` puts the same date in the meta description as
    `vs <price> market (<date>)`.

Three properties are guarded here, and the second is the one a naive fix breaks:

  1. A page behind the API is REPORTED STALE, naming both dates -- not failed.
  2. Staleness is only forgiven when the page shows a price AT ITS OWN DATE. Knowing a
     page is a day behind is not enough; the reader needs the figure on screen to belong
     to the date printed beside it.
  3. The genuine defects still fail: a same-date mismatch, a stale page with no figure
     beside its date, and a page that states no date at all.

Point 3 is what stops this fix from being bought with a weakened check. A tolerance-based
fix would pass property 1 and fail property 3, which is why it was not taken.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "audit_loop.py"


def _load_gate():
    """Import the gate module under a registered name.

    The module builds a @dataclass, which resolves `cls.__module__` through sys.modules
    while it is being defined -- so exec_module alone raises AttributeError on None.
    Registering first is the difference between importing the gate and not.
    """
    spec = importlib.util.spec_from_file_location("valence_audit_loop_stale", GATE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATE_MOD = _load_gate()


def _page(date, price):
    """The two shapes a real page emits: the ld+json date and the caption figure.

    Built from what the committed components produce rather than from what the gate
    expects, so a frontend change that drops either shape shows up here as a failure
    rather than as a silently-skipped staleness check.
    """
    ld = ('<script type="application/ld+json">{"@type":"Dataset",'
          '"temporalCoverage":"%s"}</script>' % date)
    if price is None:
        return ld
    caption = ('<meta name="description" content="DCF implied value 160.65 vs %s market '
               '(%s) at a 9.2%% WACC. Full unlevered FCFF model.">' % (price, date))
    return ld + caption


def _verdict(html, api_price, api_date):
    """Run the gate's own comparison and return (failed, is_stale).

    Calls `_judge_market_price` in the gate module rather than reimplementing the logic.

    That distinction is the whole point, and it was learned the hard way: the first
    version of this test carried its own copy of the comparison, so a mutation that
    deleted the staleness branch from the gate SURVIVED -- the test was passing against
    its own transcription while the gate kept failing correct pages. A guard on a copy is
    not a guard. When this logic changes, this test must fail.
    """
    v = GATE_MOD._judge_market_price(html, api_price, api_date, "yfinance",
                                    cid="cid", ticker="TK")
    return v.failed, v.stale


class TestAStalePageIsNotAMissingFigure:
    def test_a_page_a_day_behind_is_reported_not_failed(self):
        failed, stale = _verdict(_page("2026-10-02", "158.11"), 156.89, "2026-10-03")
        assert not failed, (
            "a correctly-cached page was failed. This is the defect: the page is "
            "within the declared revalidation window and states its own quote date."
        )
        assert stale == 1, "expected it to be reported as stale, not silently passed"

    def test_a_page_in_sync_passes_without_being_called_stale(self):
        failed, stale = _verdict(_page("2026-10-03", "156.89"), 156.89, "2026-10-03")
        assert not failed and stale == 0


class TestTheGenuineDefectsStillFail:
    """The fix must not be a weakened check.

    Each of these was a FAIL before and has to stay one. A gate that stops distinguishing
    staleness from a wrong figure has thrown away the reason it existed.
    """

    def test_a_same_date_mismatch_still_fails(self):
        """Larsen & Toubro: 3,766.40 on the page against 3,756.10 in the model.

        Both at 2026-09-28, so no amount of caching explains it -- the page is reading a
        different backend. This is the case a tolerance-based fix would have swallowed.
        """
        failed, stale = _verdict(_page("2026-09-28", "3766.40"), 3756.10, "2026-09-28")
        assert failed, "a same-date mismatch passed. That is a wrong figure on the page."
        assert stale == 0

    def test_a_stale_page_with_no_figure_beside_its_date_still_fails(self):
        """Knowing a page is behind is not enough to call it healthy.

        A page that prints a date with no figure next to it tells a reader nothing about
        how old the number is, which is the property this gate protects.
        """
        failed, _ = _verdict(_page("2026-10-02", None), 156.89, "2026-10-03")
        assert failed, (
            "a stale page carrying no price beside its date was forgiven. Its date is "
            "not tied to any figure."
        )

    def test_a_page_that_states_no_date_still_fails(self):
        """No date means no way to tell staleness from wrongness.

        Treating it as stale would make the check unfalsifiable: any page could claim to
        be behind.
        """
        failed, _ = _verdict("<html>DCF implied value 160.65</html>",
                             156.89, "2026-10-03")
        assert failed, "a page with no quote date was forgiven"


class TestReadingTheDateOffThePage:
    """`_page_quote_date` has to survive the shapes Next actually emits."""

    def test_it_reads_plain_json_ld(self):
        assert GATE_MOD._page_quote_date(
            _page("2026-10-01", "158.11")) == "2026-10-01"

    def test_it_reads_html_escaped_json_ld(self):
        """Next may serialise the ld+json block with &quot; instead of a quote.

        Measured, not assumed: before the escaped branch was added this returned None on
        a document that plainly carried the date, which would have silently disabled the
        staleness check.
        """
        escaped = ('<script type="application/ld+json">'
                   '{&quot;temporalCoverage&quot;:&quot;2026-10-01&quot;}'
                   '</script>')
        assert GATE_MOD._page_quote_date(escaped) == "2026-10-01"

    def test_it_falls_back_to_the_meta_caption(self):
        html = ('<meta name="description" content="DCF implied value 160.65 vs '
                '158.11 market (2026-10-01) at a 9.2% WACC.">')
        assert GATE_MOD._page_quote_date(html) == "2026-10-01"

    def test_it_returns_none_when_no_date_is_stated(self):
        """A guessed date would turn a real mismatch into a silent pass."""
        for html in ("", "<html>no date here</html>",
                     "<html>as of yesterday</html>"):
            assert GATE_MOD._page_quote_date(html) is None

    def test_it_does_not_invent_a_price_for_a_given_date(self):
        """`_price_at_date` pairs with the date, so a loose number is not good enough.

        Any figure elsewhere on the page would satisfy a naive substring search, which is
        exactly what makes this unable to be one.
        """
        html = _page("2026-10-02", "158.11")
        assert GATE_MOD._price_at_date(html, "2026-10-02") == "158.11"
        assert GATE_MOD._price_at_date(html, "2026-10-03") is None