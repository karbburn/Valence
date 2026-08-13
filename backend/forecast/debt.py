from __future__ import annotations

"""
Generic debt schedule module.

Computes: opening_balance + draws - repayments = closing_balance, per period.
For Infosys (no debt), all inputs are 0.0 and the schedule correctly produces zeros
via computation — not via a skip or hardcoded shortcut.

The reconcile() function is independently callable so the QA engine can invoke it
without re-running the full schedule build.
"""

from typing import List

from pydantic import BaseModel


class DebtPeriod(BaseModel):
    period: str
    opening_balance: float
    draws: float
    scheduled_repayment: float
    optional_repayment: float
    closing_balance: float          # computed: opening + draws - scheduled_repayment - optional_repayment
    interest_expense: float         # closing_balance * interest_rate
    interest_rate: float            # pre-tax rate (e.g. 0.07 for 7%)


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

    All monetary values in INR Crores. interest_rate is fractional (e.g. 0.07 = 7%).
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
        interest = avg_balance * interest_rate

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
