"""A published total is not overwritten by components that are not there.

The balance sheet assembler reconciles total assets from the sum of the current
and non-current subtotals, because some sources publish a total that is net of
minority interest and never equals the assets side. The reconciliation is real
and stays: when both subtotals are present for a period, their sum is what the
assets line reports.

The defect is what it did with a period the subtotals do not describe. The sum
was built with absent-component defaults of zero and then assigned over the
whole line, so a period with no subtotals printed had its published total
replaced by 0.0. TCS carries that shape exactly: the filing's page 11 prints
total assets of 150,137 for FY24 with the current and non-current subtotals
printed only for FY25 and FY26, and the rebuilt snapshot published a zero
against the filing's own number, which then failed the balance check against
liabilities and equity that do foot to 150,137.

A missing component is the same trap by halves: one subtotal present is a
partial sum, and a partial sum is an undercount dressed as a correction. The
published total keeps the key unless both faces of the assets side are there
to contradict it.
"""
from datetime import date

from backend.models.statements.balance_sheet import assemble_balance_sheet
from backend.normalization.taxonomy.models import CanonicalDatapoint

COMPANY = "totals_co"


def _dp(key: str, period: str, value: float, status: str = "reported") -> CanonicalDatapoint:
    year = 2000 + int(period[2:])
    return CanonicalDatapoint(
        id=f"{COMPANY}-{key}-{period}",
        company_id=COMPANY,
        canonical_key=key,
        metric_raw=key.rsplit(".", 1)[-1],
        period_label=period,
        period_end_date=date(year, 3, 31),
        value=value,
        currency="INR",
        units="crores",
        status=status,
        source_datapoint_ids=[f"{COMPANY}-fixture"],
    )


def _total_assets(dps, period: str):
    sheet = assemble_balance_sheet(dps, target_periods=sorted({d.period_label for d in dps}))
    item = next(i for i in sheet.line_items if i.canonical_key == "canonical.bs.total_assets")
    return item.values_by_period.get(period)


def test_a_period_the_subtotals_do_not_describe_keeps_its_published_total():
    """TCS FY24: filed 150,137, subtotals printed for the other two years only."""
    dps = [
        _dp("canonical.bs.total_assets", "FY24", 150_137.0, status="estimated"),
        _dp("canonical.bs.total_assets", "FY25", 159_629.0),
        _dp("canonical.bs.total_current_assets", "FY25", 68_866.0),
        _dp("canonical.bs.total_non_current_assets", "FY25", 90_763.0),
    ]
    assert _total_assets(dps, "FY24") == 150_137.0, (
        "a published total was replaced by the sum of subtotals the period "
        "does not have, so a filed figure published as zero"
    )


def test_one_subtotal_is_not_enough_to_replace_a_published_total():
    """A partial sum is an undercount, not a correction.

    Both subtotals exist as lines, but only FY25 prints them: FY26 has the
    current face alone, and its published total must not become that face.
    """
    dps = [
        _dp("canonical.bs.total_assets", "FY25", 159_629.0),
        _dp("canonical.bs.total_assets", "FY26", 182_372.0, status="estimated"),
        _dp("canonical.bs.total_current_assets", "FY25", 68_866.0),
        _dp("canonical.bs.total_current_assets", "FY26", 73_894.0),
        _dp("canonical.bs.total_non_current_assets", "FY25", 90_763.0),
    ]
    assert _total_assets(dps, "FY26") == 182_372.0, (
        "one face of the assets side replaced the published total with the "
        "other face alone"
    )


def test_both_subtotals_present_reconcile_the_total():
    """The original purpose: a minority-netted total yields to the component sum."""
    dps = [
        _dp("canonical.bs.total_assets", "FY25", 150_000.0),
        _dp("canonical.bs.total_current_assets", "FY25", 68_866.0),
        _dp("canonical.bs.total_non_current_assets", "FY25", 90_763.0),
    ]
    assert _total_assets(dps, "FY25") == 159_629.0, (
        "the component sum must still replace a total the sources publish "
        "net of minority interest"
    )
