"""A dropped comparative must be dropped, not relabelled onto the period that was kept.

HCLTech's balance sheet compares two DIFFERENT dates:

    printed page 5    30 June 2026   and   31 March 2026
    printed page 6    30 June 2026   and   31 March 2026

and both used to arrive as FY26, because `_year_anchors` matches only the year token and
"31 March 2026" and "30 June 2026" share one. So the comparative was lost, `total_assets` appeared
twice for one period as 11,806 and 12,261, and nothing objected -- every row was a real figure from a
real column of a real filing.

The engine has no quarter, so a page comparing a quarter against a year-end cannot be represented.
That larger decision is unbuilt. What is pinned here is the rule chosen for it: a column the engine
cannot represent is DROPPED AND REPORTED, never given a label that makes it look like a duplicate of
a real period. Refusing-and-recording was chosen over representing because a recorded unknown beats
an unverified pass, and over silently relabelling because silent relabelling is the defect.

**The distinction that matters, and that an earlier attempt at this fix got wrong.**

A page prints one caption twice for two unrelated reasons:

  * two COLUMNS -- two dates. That is the defect above.
  * two ROWS in the SAME column -- a caption in both the current and the non-current half of one
    page. `bs_half` exists to disambiguate those, both are real, and discarding either loses a
    figure.

The first version of this fix treated both as the same thing and silently dropped eleven legitimate
TCS captions. The control below caught it. The drop is therefore keyed on the column, and only ever
across columns.

TCS printed 11 is the control that matters most: it compares March 2026 with March 2025, so its two
columns have distinct year tokens, nothing should ever be dropped, and any collapse of it would pass
every HCLTech assertion while destroying the cases that work.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


import pytest

sys.path.insert(0, ".")

from backend.data.parsers.pdf_tables import parse_predicted_statement_page  # noqa: E402

HCLTECH = Path("backend/data/filings/nse/hcltech-ifrs-2026-07.pdf")
TCS = Path("backend/data/filings/nse/tcs-outcome-2026-04.pdf")
INFOSYS = Path("backend/data/filings/infosys-fy26-q4-outcome.pdf")

needs_hcl = pytest.mark.skipif(not HCLTECH.exists(), reason="no HCLTech filing committed")
needs_tcs = pytest.mark.skipif(not TCS.exists(), reason="no TCS filing committed")
needs_infy = pytest.mark.skipif(not INFOSYS.exists(), reason="no Infosys filing committed")

DROPPED = "cannot represent"


def _parse(pdf: Path, index: int, company_id: str):
    return parse_predicted_statement_page(
        str(pdf), index, "BALANCE SHEET", "nse_filing", annual_only=False,
        company_id=company_id,
    )


def _capture_drop_warnings(fn) -> list[str]:
    records: list[logging.LogRecord] = []

    class _Handler(logging.Handler):
        def emit(self, record):
            records.append(record)

    from backend.data.parsers import pdf_tables as pt

    log = logging.getLogger(pt.__name__)
    handler = _Handler()
    log.addHandler(handler)
    previous = log.level
    log.setLevel(logging.WARNING)
    try:
        fn()
    finally:
        log.removeHandler(handler)
        log.setLevel(previous)
    return [r.getMessage() for r in records if DROPPED in r.getMessage()]


def _per_period_values(dps, caption: str) -> dict[str, set[float]]:
    out: dict[str, set[float]] = {}
    for d in dps:
        if d.metric_raw == caption:
            out.setdefault(d.period_label, set()).add(round(d.value, 1))
    return out


@needs_hcl
@pytest.mark.parametrize("index", [4, 5], ids=["printed-5", "printed-6"])
def test_one_period_never_holds_two_different_total_assets(index):
    """The property that was violated, now that it is fixed.

    `total_assets` used to arrive twice for FY26 -- 11,806 and 12,261 -- which are two different
    dates sharing one label. Whichever row a consumer picked, it was picking from an ambiguous set,
    and the comparative was simply gone.
    """
    dps = _parse(HCLTECH, index, "hcltech_hcltech")
    assert dps, "the page must still parse, or this proves nothing"

    for period, values in _per_period_values(dps, "TOTAL ASSETS").items():
        assert len(values) == 1, (
            f"printed page {index + 1}: TOTAL ASSETS holds {sorted(values)} for {period}. A caption "
            "and a period must identify one row."
        )


@needs_hcl
def test_the_kept_column_is_the_reporting_date():
    """Leftmost wins, which is the reporting date on both layouts.

    Getting this backwards would be worse than the original defect in one specific way: it would
    substitute a stale figure for a current one while looking perfectly labelled. So it is pinned to
    the page's own printed values, not to a magnitude.

    Pinned to printed page 5 because that is the page carrying TOTAL ASSETS. Page 6 is the
    liabilities half and prints TOTAL EQUITY AND LIABILITIES instead, so asserting this figure on
    both pages would be asserting against a caption the page does not carry.
    """
    values = _per_period_values(_parse(HCLTECH, 4, "hcltech_hcltech"), "TOTAL ASSETS")
    assert len(values) == 1, f"expected exactly one period for TOTAL ASSETS, got {values}"
    (kept,) = values.values()
    # Printed: "TOTAL ASSETS 11,806 12,261". 11,806 is the reporting date, leftmost.
    assert kept == {11_806.0}, (
        f"kept {kept}; the page prints 11,806 first and 12,261 second, so the reporting date is "
        "the one that must survive"
    )


@needs_hcl
@pytest.mark.parametrize("index", [4, 5], ids=["printed-5", "printed-6"])
def test_the_dropped_column_is_reported_not_silent(index):
    """A lost period is a real loss, and silence is what the defect looked like.

    Without this, the drop is indistinguishable from the filing having printed one column -- which is
    exactly the failure that let a double-counting balance sheet look correct.
    """
    messages = _capture_drop_warnings(
        lambda: _parse(HCLTECH, index, "hcltech_hcltech")
    )
    assert messages, (
        f"printed page {index + 1} drops a column and said nothing. A dropped comparative is a "
        "period the filing prints and the model does not have, and it must not read as though the "
        "filing only showed one period."
    )
    assert "figure(s) came from a second printed column" in messages[0], (
        f"the warning must say how much was dropped, not only that something was: {messages[0]!r}"
    )


@needs_hcl
def test_the_figures_are_untouched_by_the_drop():
    """Dropping a column must not change any figure that was kept.

    A fix for a labelling defect that also moved a number would be a different change wearing this
    one's description, and every measurement taken against these pages would stop describing them.
    """
    dps = _parse(HCLTECH, 4, "hcltech_hcltech")
    figures = {d.metric_raw: d.value for d in dps}
    # Printed on page 5, verbatim: "Goodwill 2,519 2,519" and "Cash and cash equivalents 971 872".
    assert figures.get("Goodwill") == pytest.approx(2_519.0), (
        f"Goodwill is {figures.get('Goodwill')}, and the page prints 2,519"
    )
    assert figures.get("Cash and cash equivalents") == pytest.approx(971.0), (
        f"Cash is {figures.get('Cash and cash equivalents')}, and the page prints 971 first"
    )


@needs_tcs
@pytest.mark.parametrize("index", [10, 19], ids=["printed-11", "printed-20"])
def test_two_distinct_years_still_produce_two_labels(index):
    """The control, and the reason the fix is narrow.

    TCS compares March 2026 with March 2025. Distinct YEAR tokens, so the columns were always
    distinguishable and always must be. A change that collapsed every page to one label would pass
    every HCLTech assertion above while quietly destroying the cases that work.
    """
    labels = {d.period_label for d in _parse(TCS, index, "tcs_tcs")}
    assert len(labels) >= 2, (
        f"TCS printed page {index + 1} compares March 2026 with March 2025 and must produce two "
        f"period labels, got {labels}. The drop must apply only to columns that genuinely collide."
    )


@needs_tcs
@pytest.mark.parametrize("index", [10, 19], ids=["printed-11", "printed-20"])
def test_a_page_with_distinct_years_drops_nothing(index):
    """The counterpart: no collision, no warning, nothing lost."""
    assert not _capture_drop_warnings(lambda: _parse(TCS, index, "tcs_tcs")), (
        f"TCS printed page {index + 1} compares two genuinely different years, so nothing should "
        "be dropped. A warning here means the fix is firing on same-column rows."
    )


@needs_tcs
def test_a_caption_printed_in_both_halves_keeps_both_rows():
    """The regression the first attempt caused, asserted so it cannot recur.

    A caption appearing in both the current and the non-current half of one page prints twice in the
    SAME column. Both are real, `bs_half` disambiguates them, and dropping either loses a figure --
    which is exactly what happened: eleven TCS captions vanished before the control above caught it.
    """
    dps = _parse(TCS, 10, "tcs_tcs")

    both_halves = {}
    for d in dps:
        if d.bs_half in ("current", "noncurrent"):
            both_halves.setdefault(d.metric_raw, set()).add(d.bs_half)

    duplicated = {c for c, halves in both_halves.items() if len(halves) == 2}
    assert duplicated, (
        "TCS printed page 11 prints captions in both halves, so this fixture no longer exercises "
        "the case it was written for. Re-pick the page rather than deleting the test."
    )

    lost = []
    for caption in duplicated:
        values = _per_period_values(dps, caption)
        for period, vs in values.items():
            if len(vs) < 2:
                lost.append((caption, period, sorted(vs)))
    assert not lost, (
        f"{len(lost)} caption(s) printed in both halves now hold one value, so a figure was "
        f"discarded: {lost[:3]}"
    )


@needs_infy
def test_an_indian_filer_keeps_both_of_its_years():
    """The ordinary case, unaffected. Infosys printed 100 compares March 2026 with March 2025."""
    labels = {d.period_label for d in _parse(INFOSYS, 99, "infy_infy")}
    assert len(labels) >= 2, (
        f"Infosys printed 100 must keep both years, got {labels}. This is the common layout and a "
        "regression here would affect every Indian filer."
    )
    assert not _capture_drop_warnings(lambda: _parse(INFOSYS, 99, "infy_infy")), (
        "Infosys printed 100 compares two distinct years, so nothing should be dropped"
    )