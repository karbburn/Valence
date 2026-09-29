"""The lines above the current-asset subtotal must add up to that subtotal.

The balance sheet can balance in total while the block printed above the
current-asset subtotal does not, and nothing in this codebase noticed for a long
time. Two opposite failures hide there, and both are perfectly self-consistent:

An OVER-count, when two of the lines are the same money viewed at two levels of
the taxonomy. Armstrong World Industries prints one line, "Other current assets
23.9", of which prepaid expenses are 22.5. Held as two separate figures the
itemised block summed to 414.0 against a filed 391.5, and because the investment
residual was clamped at zero, that 22.5 of overlap was reported by nothing at all —
no check, no warning, no field.

An UNDER-count, when the filer holds a current asset the engine never ingested.
Apple's vendor non-trade receivables are tens of billions of dollars that no line
above the subtotal accounts for, so the column falls short and the statement still
balances.

Both are invisible to the balance-sheet check, which reads the subtotals, and to
every plausibility check, which reads single fields. The numbers are each fine.
The only thing wrong is the relationship between them.
"""

from __future__ import annotations

import datetime as dt

from backend.models.spec.historicals import Historicals
from backend.models.spec.metadata import ModelMetadata
from backend.models.spec.model_specification import ModelSpecification
from backend.validation.accounting_checks import (
    CURRENT_ASSET_LINES,
    check_current_assets_reconcile,
)

_PERIODS = ["FY24", "FY25"]
_END = dt.date(2025, 12, 31)


def _line(key: str, value: float, period: str):
    from backend.models.spec.historicals import HistoricalLineItem

    return HistoricalLineItem(
        canonical_key=key,
        period_label=period,
        period_end_date=_END,
        value=value,
        currency="USD",
        units="millions",
        status="reported",
        source_datapoint_ids=[f"{key}-{period}"],
        derivation_rule=None,
    )


def _spec(rows: dict[str, list[tuple[str, float]]]) -> ModelSpecification:
    """Build a spec from {period: [(canonical_key, value), ...]}."""
    items = []
    for period, pairs in rows.items():
        items.extend(_line(k, v, period) for k, v in pairs)
    return ModelSpecification(
        metadata=ModelMetadata(
            company_id="t_us",
            ticker="T",
            name="Test Co",
            market="us",
            currency="USD",
            units="millions",
            fiscal_year_end="December 31",
        ),
        historicals=Historicals(periods=list(rows.keys()), line_items=items),
    )


def _current_assets(
    cash=112.7,
    securities=0.0,
    receivables=130.3,
    unbilled=0.0,
    inventory=124.6,
    catchall=23.9,
    subtotal=391.5,
) -> dict[str, list[tuple[str, float]]]:
    return {
        p: [
            ("canonical.bs.cash_and_bank", cash),
            ("canonical.bs.current_investments", securities),
            ("canonical.bs.trade_receivables", receivables),
            ("canonical.bs.unbilled_revenue", unbilled),
            ("canonical.bs.inventory", inventory),
            ("canonical.bs.prepayments_other_current_assets", catchall),
            ("canonical.bs.total_current_assets", subtotal),
        ]
        for p in _PERIODS
    }


class TestTheBlockReachesTheSubtotal:
    def test_a_filer_whose_lines_add_up_passes(self):
        # 112.7 + 130.3 + 124.6 + 23.9 = 391.5
        assert check_current_assets_reconcile(_spec(_current_assets())).passed

    def test_the_same_money_counted_twice_fails(self):
        # Two printed lines holding one amount: the same current assets arriving
        # under receivables and again inside the catch-all. This is not a
        # hypothetical — one feed-fed filer put the identical figure in both, which
        # is why its block over-summed by exactly the size of the catch-all and
        # nothing reported it.
        rows = _current_assets(receivables=130.3 + 23.9)
        res = check_current_assets_reconcile(_spec(rows))
        assert not res.passed
        # The detail rounds to whole units, so the 23.9 of overlap reads as +24.
        assert "gap +24" in res.detail, res.detail

    def test_a_missing_current_asset_fails(self):
        # Apple's case: the filer holds a large current asset the engine never read,
        # so everything above the subtotal falls short.
        rows = _current_assets(subtotal=391.5 + 31_477.0)
        res = check_current_assets_reconcile(_spec(rows))
        assert not res.passed
        assert "-" in res.detail

    def test_the_gap_is_signed_so_the_two_failures_read_differently(self):
        """A gap of plus three and a gap of minus three need opposite fixes."""
        over = check_current_assets_reconcile(
            _spec(_current_assets(subtotal=391.5 - 3.0))
        )
        under = check_current_assets_reconcile(
            _spec(_current_assets(subtotal=391.5 + 3.0))
        )
        assert not over.passed and not under.passed
        assert "+3" in over.detail
        assert "-3" in under.detail

    def test_a_period_with_no_itemised_lines_is_not_judged(self):
        # Nothing to add up is not a failure; it is a company whose current assets
        # were never ingested, which other checks report.
        rows = {
            p: [("canonical.bs.total_current_assets", 391.5)] for p in _PERIODS
        }
        assert check_current_assets_reconcile(_spec(rows)).passed


class TestTheCheckDescribesTheStatement:
    def test_every_rendered_current_asset_line_is_covered(self):
        """A line added to the workbook belongs in the sum, or the check is describing
        a different statement from the one a reader sees."""
        import re
        from pathlib import Path

        src = Path("backend/export/excel/render_hist.py").read_text(encoding="utf-8")
        block = src.split("bs_items = [", 1)[1].split("]", 1)[0]
        rendered = re.findall(r'\(\s*"(canonical\.bs\.[a-z_]+)"', block)
        # The rendered current-asset block runs from just after the non-current
        # subtotal to just before the current-asset subtotal.
        start = rendered.index("canonical.bs.total_non_current_assets") + 1
        end = rendered.index("canonical.bs.total_current_assets")
        printed = set(rendered[start:end])
        missing = printed - set(CURRENT_ASSET_LINES)
        assert not missing, (
            f"the workbook prints current-asset lines the check does not sum: {sorted(missing)}"
        )
