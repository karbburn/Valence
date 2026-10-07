"""An outflow must be stored as an outflow.

XBRL stores `PaymentsOfDividends` as a positive magnitude -- the sign is carried by the
element's MEANING, not by its value -- while a printed statement shows the movement in
parentheses. Reading the element verbatim published NVIDIA's dividends as

    FY24  395    FY25  834    FY26  974

where the market feed had supplied -395 / -834 / -974. The magnitude was right and the
direction was inverted, so the model carried a dividend payment as a capital INFLOW and
the forecast, which writes `-dividends_est`, would have added cash that left the
business.

The convention is the engine's, and it is asserted here rather than assumed:

    forecast/engine.py   _item("canonical.cf.dividends_paid", period, -dividends_est)
    forecast/engine.py   abs(hist_div / hist_np)      -- history read sign-agnostically

so the historical line must be negative to sit beside what the forecast writes beside it.

These tests were written after the defect was measured, and they are shaped around the
specific thing that made it invisible: the absolute values were IDENTICAL. Only the sign
differed, and a comparison of magnitudes reports that as agreement.
"""

from __future__ import annotations

import inspect
import pathlib
import re
import sys
from datetime import date, datetime

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.data.store import RawDatapoint  # noqa: E402
from backend.normalization.financials.mapper import map_raw_datapoints  # noqa: E402

# What SEC companyconcept returns for NVIDIA, verified per year.
XBRL_POSITIVE = {
    "FY24": 395_000_000.0,
    "FY25": 834_000_000.0,
    "FY26": 974_000_000.0,
}
# What the market feed supplied, and what the tie-out verified against the filing.
FEED_NEGATIVE = {"FY24": -395.0, "FY25": -834.0, "FY26": -974.0}


def _stored(value_usd: float, metric_label: str = "Dividend Amount") -> float:
    """The value as the SEC reader would store it, in USD millions.

    CALLS the reader's own rule rather than re-deriving it from the source text.

    That is not a style preference. The rule began inline inside
    `fetch_and_parse_sec_edgar`, a 300-line function that takes a `company_id` and
    fetches from SEC, so the only way to test it was to match its source with a regex.
    Five patterns were tried. Three failed on a quote class that matched the line
    perfectly in isolation; one failed because `val\s*([+-])=\s*val` looks like it
    should match `val = -val` and does not, since the source has `-val` after the
    equals sign. Every failure surfaced as the same bare `assert None`, which is
    indistinguishable from the rule having been deleted.

    So the rule was given a name and moved out of the fetch loop, where it is a policy
    that can be asked rather than parsed.
    """
    from backend.data.ingestion.sec_edgar import _as_stored_outflow

    from backend.data.ingestion.sec_edgar import (
        US_GAAP_TAG_MAP,
        _as_stored_outflow,
    )

    tags = next((t for label, t, _s in US_GAAP_TAG_MAP if label == metric_label), None)
    return _as_stored_outflow(value_usd / 1e6, metric_label, tags)


class TestTheRuleMatchesElementsNotLabels:
    """The bug this file's helper was rewritten for.

    Two earlier versions matched the RAW LABEL against a `PaymentsOf...` prefix:

        _as_stored_outflow(395.0, "Dividend Amount")  ->  395.0     # unchanged!

    The label is the reader's own vocabulary and says nothing about which element
    produced the number, so every call returned False and the rule was silently
    disabled. The code read as correct and published a capital INFLOW. The element names
    are what carry the convention, so those are what are matched.
    """

    def test_the_dividends_element_is_recognised(self):
        from backend.data.ingestion.sec_edgar import _is_outflow_element

        assert _is_outflow_element("Dividend Amount", ["PaymentsOfDividends"])
        assert _is_outflow_element("Dividend Amount",
                                   ["PaymentsOfDividendsCommonStock"])

    def test_the_ifrs_dividend_element_is_recognised(self):
        """The ifrs-full spelling carries the same convention as the us-gaap pair.

        Infosys' 20-F files `DividendsPaid` as a positive magnitude -- 1,777 / 2,416
        at FY24/FY25 -- while its market feed supplied -1,777 / -2,416. An element
        the rule does not know reads verbatim, so the ADR model would book the
        payment as a capital INFLOW: the exact defect this file was written for, in
        the other taxonomy.
        """
        from backend.data.ingestion.sec_edgar import (
            _as_stored_outflow,
            _is_outflow_element,
        )

        assert _is_outflow_element("Dividend Amount", ["DividendsPaid"])
        stored = _as_stored_outflow(1777.0, "Dividend Amount", ["DividendsPaid"])
        assert stored == -1777.0, (
            "the ifrs-full dividend magnitude stored as %+.1f; an outflow must be "
            "negative to sit beside what the forecast writes beside it" % stored
        )

    def test_capex_is_not_an_outflow_element(self):
        """`PaymentsToAcquirePropertyPlantAndEquipment` does not begin "PaymentsOf".

        So the prefix rule excluded capex by luck rather than by decision, while
        reading as though it were naming the class of outflows. Membership is explicit
        now.
        """
        from backend.data.ingestion.sec_edgar import _is_outflow_element

        assert not _is_outflow_element(
            "PaymentsToAcquirePropertyPlantAndEquipment",
            ["PaymentsToAcquirePropertyPlantAndEquipment"],
        )

    def test_the_rule_is_membership_not_a_prefix(self):
        """Pins the distinction, which is now demonstrable rather than luck.

        For a long time `any(t in _OUTFLOW_ELEMENTS)` and
        `any(t.startswith("PaymentsOf"))` returned the same answer for every mapped
        element, so the behavioural tests above passed against either and a mutation
        swapping membership for the prefix SURVIVED. `DividendsPaid` breaks the
        coincidence -- a recognised outflow that does not begin "PaymentsOf" -- so
        the prefix rule would store the ADR filer's dividends as an INFLOW.

        The prefix stays wrong for whatever comes next:
        `PaymentsForRepurchaseOfCommonStock` is an outflow, does not match it,
        and is not in the map today -- so the day a buyback line is added, the prefix
        rule would silently store it positive while dividends go negative.
        """
        import inspect

        from backend.data.ingestion import sec_edgar

        src = inspect.getsource(sec_edgar._is_outflow_element)
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        code = re.sub(r"#.*$", "", code, flags=re.M)
        assert "startswith" not in code, (
            "the outflow test is a PREFIX rule again, and it no longer agrees with "
            "membership: `DividendsPaid` is a recognised outflow the prefix misses, "
            "so the ADR filer's dividends would be stored as an inflow"
        )
        assert "_OUTFLOW_ELEMENTS" in code, (
            "the outflow test no longer consults the explicit element set"
        )

    def test_a_buyback_is_not_yet_sourced_so_is_not_claimed(self):
        """`PaymentsForRepurchaseOfCommonStock` is a real outflow element and is NOT here.

        It was in the first version of the set. Nothing in `US_GAAP_TAG_MAP` reads it --
        no reader entry claims it -- so listing it was a rule that could never fire
        while reading as coverage. And the test that checks reachability caught it.

        A share repurchase IS an outflow and would belong here eventually, but only once
        a map entry reads it; until then the model has no buyback line at all, so there
        is no sign convention to enforce.
        """
        from backend.data.ingestion.sec_edgar import _OUTFLOW_ELEMENTS

        assert "PaymentsForRepurchaseOfCommonStock" not in _OUTFLOW_ELEMENTS, (
            "buybacks are now claimed as a signed outflow. If a map entry has been "
            "added to read that element, this should move to asserting the buyback is "
            "stored negative."
        )

    def test_every_outflow_element_is_reachable_from_the_tag_map(self):
        """An element nothing maps is a rule that can never fire.

        Both vocabularies count: the sign rule is applied in the one fetch loop that
        runs whichever map the filer's taxonomy selects, so an element listed only in
        `IFRS_ALTERNATIVES` is exactly as reachable as one in `US_GAAP_TAG_MAP` --
        and an element in neither is dead weight that reads as coverage.
        """
        from backend.data.ingestion.ifrs_tags import IFRS_ALTERNATIVES
        from backend.data.ingestion.sec_edgar import (
            _OUTFLOW_ELEMENTS,
            US_GAAP_TAG_MAP,
        )

        mapped = {t for _label, tags, _s in US_GAAP_TAG_MAP for t in tags}
        mapped |= {t for tags in IFRS_ALTERNATIVES.values() for t in tags}
        unreachable = sorted(_OUTFLOW_ELEMENTS - mapped)
        assert not unreachable, (
            "these outflow elements are in the sign rule but in no reader entry, so "
            "the rule can never fire for them: %r" % unreachable
        )

    def test_the_rule_receives_the_tag_list_at_the_call_site(self):
        """A call that omits `tags` compiles and silently does nothing."""
        import inspect

        from backend.data.ingestion import sec_edgar

        src = inspect.getsource(sec_edgar.fetch_and_parse_sec_edgar)
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        code = re.sub(r"#.*$", "", code, flags=re.M)
        assert "_as_stored_outflow(val, metric_label, tag_list)" in code, (
            "the reader does not pass the element list to the sign rule, so the rule "
            "falls back to matching the raw label and matches nothing"
        )


class TestTheOutflowSign:
    def test_the_filing_element_becomes_a_negative_line(self):
        for period, usd in XBRL_POSITIVE.items():
            got = _stored(usd)
            assert got < 0, (
                "FY%s dividends stored as %+.1f -- XBRL reports %+.0f as a magnitude "
                "and an outflow must be negative, so this would be published as a "
                "capital INFLOW" % (period, got, usd)
            )

    def test_the_sign_now_matches_the_feed_it_replaces(self):
        """Exact agreement, sign included.

        The magnitudes were already identical before the fix, so a magnitude comparison
        would have passed against the defect. The sign is the whole change.
        """
        for period, usd in XBRL_POSITIVE.items():
            filed = _stored(usd)
            fed = FEED_NEGATIVE[period]
            assert abs(filed) == abs(fed), (
                "FY%s magnitude moved: filed %.1f vs feed %.1f"
                % (period, abs(filed), abs(fed))
            )
            assert filed == fed, (
                "FY%s: the filing now reads %+.1f and the feed read %+.1f -- same "
                "magnitude, different sign" % (period, filed, fed)
            )

    def test_an_already_negative_value_is_left_alone(self):
        """A filer that tags the outflow as negative must not be flipped positive.

        The rule is `if val > 0`, so a negative input passes through. Asserted because
        the naive form -- an unconditional negation -- would invert IFRS filers, whose
        cash-flow elements already carry signs.
        """
        assert _stored(-395_000_000.0) < 0


class TestTheForecastAgreesWithHistory:
    def test_the_engine_writes_dividends_negative(self):
        """History and forecast must share one convention.

        If the forecast writes a positive outflow while history is negative, then every
        projected period and every historical period disagree about which direction the
        money moved, and nothing in the model flags it.
        """
        from backend.forecast import engine

        src = inspect.getsource(engine)
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        code = re.sub(r"#.*$", "", code, flags=re.M)
        assert re.search(
            r'_item\(\s*"canonical\.cf\.dividends_paid"[^)]*-\s*\w', code, re.S
        ), (
            "the forecast no longer emits dividends as a negative outflow, so the "
            "historical line's sign has nothing to agree with"
        )

    def test_the_payout_ratio_is_sign_agnostic(self):
        """It reads `abs(...)`, which is why the sign is safe to change here.

        Worth pinning: if this ever becomes a signed division, a negative dividend
        becomes a negative payout ratio, and `min(..., 1.0)` clamps it to a floor of
        -100% rather than catching it.
        """
        from backend.forecast import engine

        src = inspect.getsource(engine)
        assert re.search(r"abs\(\s*hist_div\s*/\s*hist_np\s*\)", src), (
            "the payout ratio no longer takes the absolute value, so a negative "
            "dividend line produces a negative payout"
        )

    def test_the_line_survives_the_mapper_as_negative(self):
        """The sign must not be lost between the reader and the model."""
        dp = RawDatapoint(
            id="probe-div",
            company_id="nvda_us",
            metric_raw="Dividend Amount",
            period_label="FY26",
            period_end_date=date(2026, 1, 25),
            value=_stored(XBRL_POSITIVE["FY26"]),
            currency="USD",
            units="millions",
            source="sec_edgar",
            source_location="p",
            section="CASH FLOW",
            status="reported",
            update_date=datetime.now(),
        )
        canonical, _m, _u = map_raw_datapoints([dp])
        assert canonical, "the dividends line produced no canonical datapoint"
        assert canonical[0].canonical_key == "canonical.cf.dividends_paid"
        assert canonical[0].value < 0, (
            "the mapper produced %+.1f; the sign must survive normalisation"
            % canonical[0].value
        )


class TestCapexIsNotSilentlyChanged:
    """The convention is inconsistent, and that is a separate decision.

    `canonical.cf.capex` is stored POSITIVE for us-gaap filers (NVIDIA 1,069 / 3,236 /
    6,042) while dividends are stored negative, so one cash-flow statement carries one
    outflow as a magnitude and another as a movement. Reconciling it means choosing
    which way capex goes and re-deriving everything that reads it.

    Asserted so the inconsistency is VISIBLE and cannot be quietly relied upon: if a
    future change flips capex, this fails and says the consumers need re-deriving.
    """
    def test_capex_is_still_a_positive_magnitude(self):
        assert _stored(1_069_000_000.0, "PaymentsToAcquirePropertyPlantAndEquipment") > 0, (
            "capex is now stored negative. That is probably the right direction, but "
            "it is a change to every cash flow built on it -- re-derive the forecast, "
            "free cash flow and the workbook formulas, and update this test"
        )

    def test_the_two_conventions_are_not_the_same(self):
        """Spelled out, because 'the outflow rule' implies one convention.

        There are two. The rule is named for what it matches -- a `PaymentsOf` element
        -- rather than for outflows generally, precisely because capex is not covered.
        """
        capex = _stored(1_069_000_000.0, "PaymentsToAcquirePropertyPlantAndEquipment")
        dividends = _stored(974_000_000.0, "Dividend Amount")
        assert capex > 0 > dividends, (
            "capex %+.1f and dividends %+.1f -- if both now share a sign, the "
            "inconsistency is resolved and this note should be rewritten"
            % (capex, dividends)
        )
