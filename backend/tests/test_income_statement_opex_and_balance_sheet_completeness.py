"""An income statement that does not add up is not a financial statement.

A reader who sees gross profit, then an operating expense section with every
expense line blank, and then an operating profit cannot reconcile any of it. The
profit looks unexplained, and the blank cells read as zero, so the gap is
invisible rather than obviously missing.

The cause was on the ingestion side, not the rendering side. The income
statement renderer has always had rows for research and development, employee
benefit, selling and administrative, and other operating expense, and every one
of them exported blank for every company, because no tag fed them.

The second defect is subtler. Filers split the same selling and administrative
total two ways. Some report one combined line; others report selling and
marketing separately from general and administrative, and the marketing line
alone runs to tens of billions. Reading only the combined tag left the second
kind of filer publishing nothing at all.

Every figure below is as filed, in millions, taken from each company's own
income statement, so the identity is checked against the filing and not against
whatever the engine happened to produce. The tests call the real derivation, so
a regression in the implementation fails here.
"""

import datetime as dt

from backend.normalization.financials.derivation import derive_canonical_metrics
from backend.normalization.taxonomy.models import CanonicalDatapoint

_PERIOD_END = dt.date(2026, 1, 25)

# A filer that reports one combined selling, general and administrative line and
# tags no marketing or administrative breakdown at all. 153,463 - 18,497 - 4,579
# is 130,387, its reported operating profit, so the identity holds on the filed
# figures alone.
COMBINED_PRESENTER = {
    "revenue": 215_938.0,
    "gross_profit": 153_463.0,
    "research_development": 18_497.0,
    "selling_and_admin": 4_579.0,
    "operating_profit": 130_387.0,
}

# A filer that reports a combined line *and* the two halves of it, all from the
# same fiscal year. The halves sum to exactly the combined figure, which is what
# makes them a breakdown rather than an addition: 18,639 + 7,458 = 26,097, its
# reported selling, general and administrative line. Publishing the combined
# figure and the two parts side by side would count 26,097 twice over.
# 180,683 - 31,370 - 26,097 = 123,216, its reported operating profit.
BREAKDOWN_OF_COMBINED = {
    "revenue": 391_035.0,
    "gross_profit": 180_683.0,
    "research_development": 31_370.0,
    "selling_and_admin": 26_097.0,
    "selling_and_marketing": 18_639.0,
    "general_and_administrative": 7_458.0,
    "operating_profit": 123_216.0,
}

# A filer that reports the two halves separately and no combined line at all.
# 25,654 + 7,223 = 32,877, and 32,488 + 32,877 = 65,365, which is the total
# operating expense the filer itself reports. Reading only the combined tag here
# produced nothing, and the workbook's gross profit stopped meeting its own
# operating profit by 25,654, a gap that grew every year.
SPLIT_PRESENTER = {
    "revenue": 281_724.0,
    "gross_profit": 193_893.0,
    "research_development": 32_488.0,
    "selling_and_marketing": 25_654.0,
    "general_and_administrative": 7_223.0,
    "operating_profit": 128_528.0,
}

COMBINED_REPORTED = 26_097.0  # the combined line a filer publishes alongside its parts


def _dp(company_id: str, key: str, value: float) -> CanonicalDatapoint:
    return CanonicalDatapoint(
        company_id=company_id,
        canonical_key=key,
        metric_raw=key,
        period_label="FY25",
        period_end_date=_PERIOD_END,
        value=value,
        currency="USD",
        units="millions",
        status="reported",
        source_datapoint_ids=[f"{company_id}-{key}"],
    )


def _ingest(company_id: str, facts: dict, *, combined_reported: bool = False):
    """Push a filer's filed lines through the real derivation.

    Returns the reported points alongside the derived ones, because the
    derivation returns only what it added and a caller needs the whole result.
    """
    points = [
        _dp(company_id, "canonical.is.revenue", facts["revenue"]),
        _dp(company_id, "canonical.is.gross_profit", facts["gross_profit"]),
        _dp(company_id, "canonical.is.operating_profit", facts["operating_profit"]),
        _dp(company_id, "canonical.is.research_development", facts["research_development"]),
    ]
    if combined_reported:
        points.append(
            _dp(company_id, "canonical.is.selling_admin_exp", facts["selling_and_admin"])
        )
    else:
        points.append(
            _dp(company_id, "canonical.is.sales_marketing", facts["selling_and_marketing"])
        )
        points.append(
            _dp(company_id, "canonical.is.general_admin", facts["general_and_administrative"])
        )
    # A filer may tag the halves of its combined line as well. When it does, those
    # tags are present in the vocabulary and must not be treated as extra expense.
    for key in ("selling_and_marketing", "general_and_administrative"):
        if key in facts:
            canonical = (
                "canonical.is.sales_marketing"
                if key == "selling_and_marketing"
                else "canonical.is.general_admin"
            )
            points.append(_dp(company_id, canonical, facts[key]))
    return points + derive_canonical_metrics(points)


def _value(points, key: str):
    """Last writer wins, matching how the pipeline indexes a key."""
    found = None
    for p in points:
        if p.canonical_key == key:
            found = p.value
    return found


def test_split_opex_lines_reconcile_to_reported_operating_profit():
    out = _ingest("split_us", SPLIT_PRESENTER)
    selling = _value(out, "canonical.is.selling_admin_exp")
    gross = SPLIT_PRESENTER["gross_profit"]
    rd = SPLIT_PRESENTER["research_development"]
    operating = SPLIT_PRESENTER["operating_profit"]

    assert selling == 32_877.0
    # The identity a reader checks by eye, on the filed figures.
    assert gross - rd - selling == operating


def test_reported_combined_line_is_never_overwritten_by_its_own_breakdown():
    out = _ingest("combined_us", BREAKDOWN_OF_COMBINED, combined_reported=True)
    selling = _value(out, "canonical.is.selling_admin_exp")

    # Exactly the combined figure, not the combined figure plus its two parts.
    assert selling == COMBINED_REPORTED
    assert selling != COMBINED_REPORTED + 18_639.0 + 7_458.0
    # The two parts are the filer's own breakdown of it, which is what makes this
    # safe: 18,639 + 7,458 is exactly the combined line they came from.
    assert 18_639.0 + 7_458.0 == COMBINED_REPORTED


def test_both_presentations_foot_to_the_same_identity():
    """The whole point: presentation differs, the arithmetic does not."""
    cases = (
        ("combined", COMBINED_PRESENTER, True),
        ("breakdown", BREAKDOWN_OF_COMBINED, True),
        ("split", SPLIT_PRESENTER, False),
    )
    for name, facts, combined in cases:
        out = _ingest(f"{name}_us", facts, combined_reported=combined)
        implied = (
            facts["gross_profit"]
            - facts["research_development"]
            - _value(out, "canonical.is.selling_admin_exp")
        )
        assert implied == facts["operating_profit"], (
            f"{name} presentation: gross {facts['gross_profit']:,.0f} less research and "
            f"selling {implied:,.0f} against reported {facts['operating_profit']:,.0f}"
        )


def test_selling_and_admin_is_left_absent_rather_than_guessed():
    """No selling expense and no marketing or administrative line means no line."""
    points = [
        _dp("bare_us", "canonical.is.revenue", 1_000.0),
        _dp("bare_us", "canonical.is.gross_profit", 400.0),
        _dp("bare_us", "canonical.is.operating_profit", 150.0),
    ]
    out = points + derive_canonical_metrics(points)
    assert _value(out, "canonical.is.selling_admin_exp") is None


def test_total_non_current_assets_is_derived_when_the_filer_omits_the_subtotal():
    """Total assets minus current assets is the non-current subtotal.

    Most filers publish no non-current subtotal, and the balance sheet renderer
    has a row for one regardless. Empty, that row left the statement visibly
    short: total assets of 206,803 against current assets of 125,605, with
    81,198 unaccounted for and the only non-current line shown being 10,383 of
    property, plant and equipment.
    """
    points = [
        _dp("nca_us", "canonical.bs.total_assets", 206_803.0),
        _dp("nca_us", "canonical.bs.total_current_assets", 125_605.0),
    ]
    out = points + derive_canonical_metrics(points)
    assert _value(out, "canonical.bs.total_non_current_assets") == 81_198.0


def test_reported_non_current_subtotal_is_authoritative():
    """A filer that publishes the subtotal keeps its own figure."""
    points = [
        _dp("rep_us", "canonical.bs.total_assets", 206_803.0),
        _dp("rep_us", "canonical.bs.total_current_assets", 125_605.0),
        _dp("rep_us", "canonical.bs.total_non_current_assets", 80_000.0),
    ]
    out = points + derive_canonical_metrics(points)
    assert _value(out, "canonical.bs.total_non_current_assets") == 80_000.0


def test_gross_property_plant_and_equipment_is_not_published_as_the_net_block():
    """Gross is not net, and a gross figure is worse than no figure.

    Gross property, plant and equipment was the second-choice tag for the net
    block. A filer tagging only the gross figure therefore published gross
    property as the net block, overstating assets by the whole accumulated
    depreciation, and nothing on the statement showed the difference.
    """
    from backend.data.ingestion.sec_edgar import US_GAAP_TAG_MAP

    net_block = next(
        tags for label, tags, _section in US_GAAP_TAG_MAP if label == "Net Block"
    )
    assert "PropertyPlantAndEquipmentNet" in net_block
    assert "PropertyPlantAndEquipmentGross" not in net_block, (
        "gross property, plant and equipment is not a net figure and must not be "
        "read as one"
    )


def test_itemised_securities_are_not_counted_twice_inside_the_filer_catch_all():
    """A securities line smaller than the catch-all is already inside it.

    One filer tags 77,723 of marketable securities against an 83,727 catch-all, and
    another 2,900 of equity securities against a 40,565 catch-all. Naming both made
    the named lines exceed the subtotal they belong to, which overstates the
    balance sheet by the securities figure.
    """
    points = [
        _dp("inside_us", "canonical.bs.total_non_current_assets", 211_284.0),
        _dp("inside_us", "canonical.bs.other_non_current_assets", 83_727.0),
        _dp("inside_us", "canonical.bs.non_current_investments", 77_723.0),
    ]
    out = points + derive_canonical_metrics(points)
    other = _value(out, "canonical.bs.other_non_current_assets")
    investments = _value(out, "canonical.bs.non_current_investments")
    assert investments == 77_723.0
    assert other == 83_727.0 - 77_723.0


def test_securities_exceeding_the_catch_all_stay_a_separate_line():
    """The same tag is a separate caption at one filer and a component at another.

    This filer holds 100,544 of securities against a 64,758 catch-all, so the
    catch-all plainly does not contain it and both are named. Comparing sizes is
    what distinguishes the two presentations; a taxonomy rule could not.
    """
    points = [
        _dp("outside_us", "canonical.bs.total_non_current_assets", 209_017.0),
        _dp("outside_us", "canonical.bs.other_non_current_assets", 64_758.0),
        _dp("outside_us", "canonical.bs.non_current_investments", 100_544.0),
    ]
    out = points + derive_canonical_metrics(points)
    assert _value(out, "canonical.bs.other_non_current_assets") == 64_758.0
    assert _value(out, "canonical.bs.non_current_investments") == 100_544.0


def test_derived_operating_profit_deducts_research_and_development():
    """Research expense is operating expense.

    The fallback that recovers operating profit from gross profit summed other
    operating expense and selling and administrative expense only. That was inert
    while no filer populated a research line, and overstated profit by the whole
    research expense once one did. The statement stayed internally consistent the
    whole time, because the error is that the profit is too high and not that it
    fails to add up, so the coherence checks could not see it.
    """
    from backend.models.statements.income_statement import (
        IS_LINE_ITEM_CONFIG,
        assemble_income_statement,
    )

    assert ("canonical.is.research_development", "Research and Development") in IS_LINE_ITEM_CONFIG

    # Gross profit 193,893 less research 32,488 and selling 32,877 is the 128,528
    # the filer reported as operating profit. Without research in the sum the
    # fallback returns 161,016, overstating profit by the whole research expense.
    points = [
        _dp("ebit_us", "canonical.is.revenue", 281_724.0),
        _dp("ebit_us", "canonical.is.gross_profit", 193_893.0),
        _dp("ebit_us", "canonical.is.research_development", 32_488.0),
        _dp("ebit_us", "canonical.is.selling_admin_exp", 32_877.0),
    ]
    statement = assemble_income_statement(points)
    operating = next(
        (i for i in statement.line_items if i.canonical_key == "canonical.is.operating_profit"),
        None,
    )
    assert operating is not None, "operating profit was not recovered at all"
    recovered = operating.values_by_period["FY25"]
    assert recovered == 128_528.0, (
        f"recovered {recovered:,.0f} against the filed 128,528"
    )


def test_a_single_tagged_half_is_not_published_as_the_total():
    """One half is not the whole of selling and administrative expense.

    A filer that tags only general and administrative has given part of the figure
    at best. Publishing that part under a label saying selling and administrative
    expense states a number the filer never reported, and whether the other half
    exists is not knowable from what it tagged.
    """
    points = [
        _dp("half_us", "canonical.is.gross_profit", 193_893.0),
        _dp("half_us", "canonical.is.general_admin", 7_223.0),
    ]
    out = points + derive_canonical_metrics(points)
    assert _value(out, "canonical.is.selling_admin_exp") is None


def test_derived_lines_outrank_the_reported_line_they_replace():
    """A derivation must not lose a tie against the figure it was written to fix.

    Selection scored a derived row and a reported row identically, so the first one
    won and every such correction was discarded. The reported 83,727 was published
    in place of the derived 6,004, and the double count it was written to prevent
    came back. A derivation is computed from reported figures, so preferring it
    cannot invent a number.
    """
    from backend.models.statements.selector import select_primary_datapoints

    reported = _dp("sel_us", "canonical.bs.other_non_current_assets", 83_727.0)
    derived = CanonicalDatapoint(
        company_id="sel_us",
        canonical_key="canonical.bs.other_non_current_assets",
        metric_raw="Other Non-Current Assets (Net of Itemised Securities)",
        period_label="FY25",
        period_end_date=_PERIOD_END,
        value=6_004.0,
        currency="USD",
        units="millions",
        status="derived",
        source_datapoint_ids=["sel_us-derivation"],
    )
    chosen = select_primary_datapoints([reported, derived], "bs")
    assert chosen[("canonical.bs.other_non_current_assets", "FY25")].value == 6_004.0
    # And with the derived row second, which is how the pipeline emits them.
    chosen = select_primary_datapoints([derived, reported], "bs")
    assert chosen[("canonical.bs.other_non_current_assets", "FY25")].value == 6_004.0


def test_non_current_assets_are_not_derived_from_a_missing_total():
    """One reported side is not enough; the difference would be fiction."""
    points = [_dp("half_us", "canonical.bs.total_assets", 206_803.0)]
    out = points + derive_canonical_metrics(points)
    assert _value(out, "canonical.bs.total_non_current_assets") is None
