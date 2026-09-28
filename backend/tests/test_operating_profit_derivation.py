"""Operating profit must not count the same charge twice.

A filer that reports interest *inside* its "Other (income) expense, net" line
still has finance cost tagged separately in its XBRL. Adding finance cost back
on top of profit before tax to recover operating profit therefore counts the
interest twice, and only by the amount of the interest.

The result is arithmetically perfect, which is what let it survive. It became
visible only as a consequence: the margin it produced anchored a five-year
forecast, and the enterprise value came out nineteen times too small.

The figures below are from a large-cap pharmaceutical's filed income statement,
in millions, so the identity is checked against the filing rather than against
whatever the engine happened to produce. The tests call the real derivation
rather than restating its formula, so a regression in the implementation fails
here.
"""

import datetime as dt

import pytest

from backend.normalization.taxonomy.models import CanonicalDatapoint
from backend.normalization.financials.derivation import derive_canonical_metrics

# As filed, in millions. Interest expense of 1,271 is disclosed as a component of
# the (24) other (income) expense, net line, so it is already inside that block.
FILED = {
    "FY24": {
        "pbt": 19_936.0,
        "other_income": 24.0,
        "finance_cost": 1_271.0,
        "revenue": 64_168.0,
        "total_costs_and_expenses": 44_232.0,
    }
}

_PERIOD_END = dt.date(2024, 12, 31)


def _dp(company_id: str, key: str, value: float, period: str = "FY24") -> CanonicalDatapoint:
    return CanonicalDatapoint(
        company_id=company_id,
        canonical_key=key,
        metric_raw=key,
        period_label=period,
        period_end_date=_PERIOD_END,
        value=value,
        currency="USD",
        units="millions",
        status="reported",
        source_datapoint_ids=[f"{company_id}-{period}-{key}"],
        derivation_rule=None,
    )


def _derive_operating_profit(company_id: str, period: str = "FY24") -> float:
    f = FILED[period]
    inputs = [
        _dp(company_id, "canonical.is.pbt", f["pbt"], period),
        _dp(company_id, "canonical.is.other_income", f["other_income"], period),
        _dp(company_id, "canonical.is.finance_cost", f["finance_cost"], period),
    ]
    derived = derive_canonical_metrics(inputs)
    op = next(
        d for d in derived if d.canonical_key == "canonical.is.operating_profit"
    )
    return op.value


class TestOperatingProfitNotDoubleCounted:
    def test_derived_operating_profit_matches_the_filing(self):
        # Sales 64,168 less total costs and expenses 44,232 is 19,936 of profit
        # before taxes. The (24) credit in that 44,232 is not an operating cost,
        # so removing it gives operating profit of 19,912.
        assert _derive_operating_profit("a") == 19_912.0

    def test_interest_is_not_added_back_on_top(self):
        # The old form, pbt + finance_cost - other_income, returned 21,183. That
        # is 1,271 more than the filing supports, which is exactly the interest
        # charge that the other income line already contains.
        f = FILED["FY24"]
        naive = f["pbt"] + f["finance_cost"] - f["other_income"]
        assert naive == 21_183.0
        assert naive - _derive_operating_profit("a") == f["finance_cost"]

    def test_agrees_with_filed_total_costs(self):
        f = FILED["FY24"]
        from_costs = f["revenue"] - (f["total_costs_and_expenses"] + f["other_income"])
        assert from_costs == _derive_operating_profit("a")

    def test_records_a_formula_that_matches_what_it_did(self):
        f = FILED["FY24"]
        derived = derive_canonical_metrics(
            [
                _dp("a", "canonical.is.pbt", f["pbt"]),
                _dp("a", "canonical.is.other_income", f["other_income"]),
                _dp("a", "canonical.is.finance_cost", f["finance_cost"]),
            ]
        )
        rule = next(
            d for d in derived if d.canonical_key == "canonical.is.operating_profit"
        ).derivation_rule
        assert rule is not None
        assert "other_income" in rule
        assert "finance_cost" not in rule

    def test_no_operating_profit_is_derived_without_the_non_operating_block(self):
        # With profit before tax alone there is no way to separate the
        # non-operating items, so nothing may be derived. An earlier version
        # derived from pbt and finance cost alone, which silently treated a
        # missing other income line as a zero one and produced operating profit
        # for a filer that had not reported enough to support it.
        derived = derive_canonical_metrics(
            [
                _dp("a", "canonical.is.pbt", 19_936.0),
                _dp("a", "canonical.is.finance_cost", 1_271.0),
            ]
        )
        assert not [
            d for d in derived if d.canonical_key == "canonical.is.operating_profit"
        ]
