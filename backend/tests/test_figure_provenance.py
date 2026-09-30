"""A computed figure must not arrive wearing a filed figure's label.

8.7% of the canonical datapoints in this engine are derived: gross profit, EBITDA,
subtotals, and the filer catch-alls the engine computes by subtraction. Every one
of them reached the model specification, the compiled snapshot, the workbook and
the site labelled `status: "reported"` with no derivation rule, because the spec
builder hardcoded that status for every line except EBITDA.

So a reader of a product whose entire claim is that every published number matches
an official filing had no way to tell which numbers were read out of a filing and
which were worked out here. And the check written to catch it,
`historicals_are_reported`, could not fail, because the status it read had already
been overwritten upstream of it: the builder's constant was the only thing it ever
saw.

The provenance now travels with the value, from the canonical datapoint through the
statement line item into the specification, and the check states the proportion of
the statement that is computed and names the keys.
"""

from __future__ import annotations

import datetime as dt

import pytest

from backend.models.spec.historicals import HistoricalLineItem, Historicals
from backend.models.spec.metadata import ModelMetadata
from backend.models.spec.model_specification import ModelSpecification
from backend.validation.data_quality import check_historicals_are_reported

_PERIOD = "FY25"
_END = dt.date(2025, 12, 31)


def _line(key: str, value: float, status: str = "reported", rule: str | None = None):
    return HistoricalLineItem(
        canonical_key=key,
        period_label=_PERIOD,
        period_end_date=_END,
        value=value,
        currency="USD",
        units="millions",
        status=status,
        source_datapoint_ids=[f"{key}-{_PERIOD}"],
        derivation_rule=rule,
    )


def _spec(lines: list) -> ModelSpecification:
    return ModelSpecification(
        metadata=ModelMetadata(
            company_id="p_us",
            ticker="P",
            name="Provenance Co",
            market="us",
            currency="USD",
            units="millions",
            fiscal_year_end="December 31",
        ),
        historicals=Historicals(periods=[_PERIOD], line_items=lines),
    )


class TestTheCheckCanSeeWhatIsComputed:
    def test_a_wholly_filed_statement_passes_and_says_so(self):
        res = check_historicals_are_reported(
            _spec([
                _line("canonical.is.revenue", 1_000.0),
                _line("canonical.bs.total_assets", 2_000.0),
            ])
        )
        assert res.passed
        assert "read from a filing" in res.detail

    def test_a_computed_line_is_counted_and_named_without_failing(self):
        """A derived gross profit is a presentational fact, not a broken model."""
        res = check_historicals_are_reported(
            _spec([
                _line("canonical.is.revenue", 1_000.0),
                _line("canonical.is.gross_profit", 400.0, "derived",
                      "gross_profit = revenue - cost_of_sales"),
            ])
        )
        assert res.passed, res.detail
        assert "1 of 2 published historical figures" in res.detail
        assert "50.0%" in res.detail
        assert "canonical.is.gross_profit" in res.detail

    def test_a_computed_anchor_line_fails(self):
        """Revenue is a different claim when it is computed rather than filed.

        The valuation's growth anchor is computed from these years, so a revenue
        figure the engine worked out is not a restatement of the accounts.
        """
        res = check_historicals_are_reported(
            _spec([
                _line("canonical.is.revenue", 1_000.0, "derived", "revenue = something else"),
                _line("canonical.bs.cash_and_bank", 300.0),
            ])
        )
        assert not res.passed
        assert "ANCHOR LINES ARE COMPUTED" in res.detail
        assert "canonical.is.revenue" in res.detail

    def test_an_invented_period_still_fails(self):
        """The original purpose is intact, not replaced by the new one."""
        res = check_historicals_are_reported(
            _spec([_line("canonical.is.revenue", 1_000.0, "estimated")])
        )
        assert not res.passed
        assert "hand-entered or derived" in res.detail


class TestProvenanceReachesTheSpecification:
    def test_the_builder_reads_the_recorded_status_rather_than_a_constant(self):
        """The defect was an overwrite upstream of the check, so it is tested there.

        Asserted against the source rather than by running a build, because the
        failure mode is precisely that a constant reappears and no test notices: the
        output would be identical for a model whose only line happens to be filed.
        """
        import inspect

        from backend.models.spec import model_specification as ms

        src = inspect.getsource(ms)
        assert 'status: str = "reported"' in src, (
            "the builder's fallback status should still exist as a default, but it "
            "must be overridden by what the ingestion recorded"
        )
        assert "status_by_period" in src, (
            "the builder no longer reads the recorded provenance, so every line "
            "reverts to a hardcoded reported status and the check goes blind again"
        )
        assert "derivation_rule_by_period" in src, (
            "the derivation rule is dropped again, so a computed figure is "
            "indistinguishable from a filed one in the workbook's derivation column"
        )

    @pytest.mark.parametrize("module", ["balance_sheet", "income_statement", "cash_flow"])
    def test_every_statement_model_carries_provenance(self, module):
        from backend.models.statements import balance_sheet, cash_flow, income_statement

        models = {
            "balance_sheet": balance_sheet.BalanceSheetLineItem,
            "income_statement": income_statement.IncomeStatementLineItem,
            "cash_flow": cash_flow.CashFlowLineItem,
        }
        fields = models[module].model_fields
        assert "status_by_period" in fields, f"{module} drops the recorded status"
        assert "derivation_rule_by_period" in fields, f"{module} drops the rule"
