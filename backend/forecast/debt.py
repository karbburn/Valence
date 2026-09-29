from __future__ import annotations

"""
Generic debt schedule module.

Computes: opening_balance + draws - repayments = closing_balance, per period.
For a zero-debt company, all inputs are 0.0 and the schedule correctly produces zeros
via computation — not via a skip or hardcoded shortcut.

The reconcile() function is independently callable so the QA engine can invoke it
without re-running the full schedule build.
"""

from typing import List

from pydantic import BaseModel


# The components of the debt this engine deducts from enterprise value, and which
# the debt schedule opens on.
#
# This is one tuple read by both sides of the model. It used to be two literal
# tuples in two modules that happened to agree, with a comment at the forecast
# site asserting they must: "Must match the definition the valuation bridge
# deducts, or the schedule's interest and the bridge's obligation are two
# different numbers for the same debt". Two lists cannot be kept in step by a
# comment, and they were not: the bridge took a market feed's total, which
# capitalises leases, so the schedule serviced 8,468 for NVIDIA while the
# valuation deducted 38,351, and Microsoft's schedule opened 50,062 above what
# the valuation charged for.
#
# Operating leases are absent and must stay absent. Rent already sits in
# operating expense under US GAAP, so it is inside the EBIT the cash flows are
# built from; deducting the liability as well charges for the same obligation
# twice. The balance is still reported on the bridge so a reader who prefers the
# market convention can see it and apply it.
OPENING_BALANCE_KEYS = (
    "canonical.bs.borrowings",
    "canonical.bs.short_term_borrowings",
    "canonical.bs.finance_lease_liabilities",
)


class DebtPeriod(BaseModel):
    period: str
    opening_balance: float
    draws: float
    scheduled_repayment: float
    optional_repayment: float
    closing_balance: float          # computed: opening + draws - scheduled_repayment - optional_repayment
    interest_expense: float         # avg_balance * (interest_rate / 100)
    interest_rate: float            # pre-tax rate in percent (e.g. 7.5 = 7.5%)


class DebtSchedule(BaseModel):
    scenario: str
    interest_rate: float
    periods: List[DebtPeriod]

    def closing(self, period: str) -> float:
        for p in self.periods:
            if p.period == period:
                return p.closing_balance
        return 0.0

    def interest(self, period: str) -> float:
        for p in self.periods:
            if p.period == period:
                return p.interest_expense
        return 0.0


def build_debt_schedule(
    opening_balance: float,
    interest_rate: float,
    draws_by_period: dict[str, float],
    scheduled_repayments_by_period: dict[str, float],
    optional_repayments_by_period: dict[str, float],
    periods: List[str],
    scenario: str,
) -> DebtSchedule:
    """Build a generic debt schedule for a single scenario.

    All monetary values in INR Crores. interest_rate is in percent (e.g. 7.5 = 7.5%).
    For a zero-debt company: pass opening_balance=0.0 and all period dicts as empty/zero —
    the schedule computes to zero correctly without any shortcut.
    """
    debt_periods: List[DebtPeriod] = []
    current_balance = opening_balance

    for p in periods:
        draws = draws_by_period.get(p, 0.0)
        sched_repay = scheduled_repayments_by_period.get(p, 0.0)
        opt_repay = optional_repayments_by_period.get(p, 0.0)
        closing = current_balance + draws - sched_repay - opt_repay
        closing = max(0.0, closing)  # debt cannot go negative
        avg_balance = (current_balance + closing) / 2.0
        interest = avg_balance * (interest_rate / 100.0)

        debt_periods.append(DebtPeriod(
            period=p,
            opening_balance=current_balance,
            draws=draws,
            scheduled_repayment=sched_repay,
            optional_repayment=opt_repay,
            closing_balance=closing,
            interest_expense=round(interest, 4),
            interest_rate=interest_rate,
        ))
        current_balance = closing

    return DebtSchedule(
        scenario=scenario,
        interest_rate=interest_rate,
        periods=debt_periods,
    )


def reconcile(schedule: DebtSchedule, tolerance: float = 0.01) -> bool:
    """Verify opening + draws - repayments == closing for every period.

    Independently callable by the QA engine. Returns False if any period fails.
    """
    for p in schedule.periods:
        expected_closing = p.opening_balance + p.draws - p.scheduled_repayment - p.optional_repayment
        expected_closing = max(0.0, expected_closing)
        if abs(expected_closing - p.closing_balance) > tolerance:
            return False
    return True
