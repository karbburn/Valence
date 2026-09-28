from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel

CheckCategory = Literal["accounting", "valuation", "data_quality"]


class ModelCheckResult(BaseModel):
    """Single QA check result.

    Carries enough context for both the web UI (navigate to offending item)
    and the Excel renderer (hyperlink to cell) to surface failures precisely.
    No renderer-specific fields here — that mapping is the renderer's job.
    """
    check_name: str                             # e.g. "Balance Sheet Balances"
    category: CheckCategory
    passed: bool
    detail: str = ""                            # human-readable failure reason; "" if passed
    implicated_canonical_keys: List[str] = []   # which line items are involved
    implicated_periods: List[str] = []          # which periods
    implicated_scenarios: List[str] = []        # which scenarios


# check registry.
# These are the structural slots.
V1_CHECK_NAMES = [
    ("balance_sheet_balances", "accounting", "Assets = Liabilities + Equity, every period."),
    ("cash_flow_reconciles", "accounting", "CF ending cash ties to BS cash line."),
    ("debt_schedule_reconciles", "accounting", "Opening + draws − repayments = closing debt."),
    ("share_count_consistent", "accounting", "Diluted share count used consistently across EPS and valuation."),
    ("dcf_bridge_reconciles", "valuation", "EV → Equity Value → Implied Share Price ties out exactly."),
    ("wacc_valid", "valuation", "WACC > 0, weights sum to 100%, no negative component costs."),
    ("terminal_growth_lt_wacc", "valuation", "Terminal growth rate < WACC (Gordon Growth requirement)."),
    ("no_missing_critical_inputs", "data_quality", "Every driver has an assumption object — no silent null."),
    ("data_provenance_quality", "data_quality", "Every historical line item carries a non-empty provenance status."),
    (
        "historicals_are_reported",
        "data_quality",
        "Every historical period traces to a figure that was actually published, "
        "not to a hand-entered projection.",
    ),
    (
        "bridge_inputs_plausible",
        "data_quality",
        "Debt, cash and lease figures on the bridge can coexist; total debt is not "
        "smaller than a lease component the note says it already contains.",
    ),
    (
        "equity_value_positive",
        "data_quality",
        "Equity value is positive, so the model does not publish a negative implied "
        "share price as if it were a valuation.",
    ),
    (
        "income_statement_is_coherent",
        "data_quality",
        "The income statement is possible: cost of sales does not exceed revenue, "
        "expense lines are not negative, and gross and operating profit do not "
        "have opposite signs.",
    ),
    (
        "year_one_growth_is_plausible",
        "data_quality",
        "The first forecast year's revenue growth is defensible, so a misread "
        "trailing revenue cannot be compounded into the published model.",
    ),
    (
        "implied_price_deviation_is_explainable",
        "data_quality",
        "Implied price is not an implausible distance from the traded price, which "
        "would point at a misread input rather than a valuation view.",
    ),
]


class QAResults(BaseModel):
    """Collection of all QA check results for a model.

    Populated by the QA Engine.
    """
    checks: List[ModelCheckResult] = []

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    @property
    def summary_label(self) -> str:
        """The string shown prominently in both renderers."""
        if not self.checks:
            return "NOT RUN"
        if self.all_passed:
            if any(c.passed and c.detail.startswith("SKIPPED:") for c in self.checks):
                return "MODEL VALID (WITH WARNINGS)"
            return "MODEL VALID"
        n = self.failed_count
        return f"{n} CHECK{'S' if n != 1 else ''} FAILED"

    @classmethod
    def empty(cls) -> "QAResults":
        """Structurally complete but un-run QA section."""
        return cls(checks=[])
