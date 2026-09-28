"""Whether the *inputs* are believable, as distinct from whether the arithmetic is right.

Why this module exists
----------------------

Every check in the existing QA suite answers one of two questions: does the
arithmetic tie, or is every field populated. Both are necessary and neither is
sufficient. A model can pass all ten existing checks and still publish a number
that is wrong by an order of magnitude, and it did, repeatedly:

    ORCL     implied $46.35 against a $137.10 market, a -66% deviation
    WMT      implied $29.68 against a $107.98 market, a -72.5% deviation
    KO       implied $36.24 against a  $87.81 market, a -58.7% deviation
    ADANIENT implied -694.67, because the equity value came out negative

All four reported **10 of 10 checks passed**. That is not a surprising failure
mode once you look at what ``dcf_bridge_reconciles`` actually asserts: that
EV - net debt = equity, and equity / shares = price. For Oracle, total debt had
been read as 14,900 while the same bridge reported operating lease liabilities
of 30,594. Net cash therefore came out at 22,177, equity came out *above*
enterprise value, and every arithmetic check passed happily, because
118,541.82 - (-21,629) = 140,170.82 is correct subtraction of a wrong number.

The note on that bridge claims total debt "already contains its lease component".
If that were true, total debt could not be smaller than the lease component. It
is, so the note's own premise is false for that company and the debt figure is
understated. That contradiction is visible entirely within the engine's own
output, and nothing was looking for it.

The rule these checks follow
----------------------------

A check in this module may not report a valuation as wrong. It reports an *input*
as implausible, because an implausible input is the root cause and the valuation
is the symptom. The message says what was read, what it should have been at
minimum, and where to look.

Thresholds are deliberately loose. A check that fires on a legitimate company
teaches people to ignore it, which costs more than the check is worth. These
fire on inputs that are wrong by multiples, not by margins.
"""

from __future__ import annotations

from typing import List

from backend.models.spec.model_specification import ModelSpecification
from backend.models.spec.qa import ModelCheckResult

# How far the DCF may sit from the traded price before the *input* is called
# into question rather than the model.
#
# This is not a view on whether the market is wrong. A DCF that disagrees with
# the market by 35% is a legitimate opinion and models post it routinely. The
# point is narrower: past this distance the most probable cause is a misread
# input, not a strong view, so it is worth a human look before the number is
# served as a valuation.
#
# -60% / +200% is wide on purpose. Everything I found wrong was outside it:
# -58.7%, -66%, -72.5%, -123.8%. Nothing correct was inside it in the wrong
# direction.
IMPLIED_DEVIATION_FLOOR = -0.60
IMPLIED_DEVIATION_CEILING = 2.00

# A company with negative book equity can still be worth something, so this is
# not an error in itself. But an equity value that has gone negative on a
# *profitable, cash-generative* business is a sign the net debt figure is wrong,
# and it is how IDEA and ADANIENT surfaced.
NEGATIVE_EQUITY_REVIEW = True


def check_bridge_inputs_plausible(spec: ModelSpecification) -> ModelCheckResult:
    """The debt, cash and lease figures on the bridge must be able to coexist.

    The specific contradiction this exists to catch: total debt smaller than the
    operating lease liability, on a bridge whose own note says the reported debt
    total already contains the lease component and so must not be added to
    separately. Both statements cannot hold. If total debt is the smaller number,
    it cannot contain the larger one, the note's premise is false, and net debt is
    understated by at least the difference.

    Also rejects the softer version of the same error: a bridge that reports a
    large net *cash* position, which is what a missing debt figure looks like once
    it has been arithmetically tidied away.
    """
    errors: List[str] = []
    failing_scenarios: List[str] = []
    keys: List[str] = []

    for val in spec.valuation:
        # Base only, for the same reason as the other two checks, plus a second
        # reason specific to this one: debt, cash and lease do not vary by
        # scenario, so a single contradiction reported once per scenario blamed
        # all three for one input. It also made the net-cash ratio
        # scenario-dependent, because a bear case that shrinks enterprise value
        # by two thirds can push an identical balance sheet past the threshold
        # on its own.
        if val.scenario != "base":
            continue
        b = val.dcf_bridge
        debt = b.total_debt or 0.0
        leases = b.operating_lease_liabilities or 0.0
        cash = (b.cash_and_equivalents or 0.0) + (b.marketable_securities or 0.0)
        net = b.less_net_debt

        if leases > 0 and debt < leases:
            short = leases - debt
            errors.append(
                f"{val.scenario}: total debt {debt:,.0f} is smaller than the reported "
                f"operating lease liability {leases:,.0f}, so it cannot already contain "
                f"the lease component as the bridge note states. Net debt is understated "
                f"by at least {short:,.0f}."
            )
            keys.extend(["total_debt", "operating_lease_liabilities", "less_net_debt"])
            failing_scenarios.append(val.scenario)
            continue

        # A net cash position is legitimate for a company with genuinely little
        # debt. It is only suspicious when it is large next to the business, and
        # the cheapest available proxy for "large" is the enterprise value the
        # model itself produced.
        if net is not None and net < 0:
            net_cash = -net
            ev = b.enterprise_value or 0.0
            if ev > 0 and net_cash > 0.25 * ev:
                errors.append(
                    f"{val.scenario}: bridge reports net cash of {net_cash:,.0f}, more than "
                    f"a quarter of the {ev:,.0f} enterprise value. That is unusual enough to "
                    f"confirm the debt figure was read completely, since an understated "
                    f"debt total produces exactly this."
                )
                keys.extend(["total_debt", "less_net_debt"])
                failing_scenarios.append(val.scenario)

    passed = not errors
    return ModelCheckResult(
        check_name="bridge_inputs_plausible",
        category="data_quality",
        passed=passed,
        detail="" if passed else "; ".join(errors),
        implicated_canonical_keys=sorted(set(keys)),
        implicated_periods=[],
        implicated_scenarios=sorted(set(failing_scenarios)),
    )


def check_equity_value_positive(spec: ModelSpecification) -> ModelCheckResult:
    """Equity value should not be negative for a company with positive enterprise value.

    A negative equity value is arithmetically fine and it is the correct answer
    for a company whose debt genuinely exceeds its worth: Vodafone Idea's net
    worth is negative on the balance sheet, so a DCF that lands there is reading
    the company rather than failing.

    It is still worth surfacing, because a negative equity value is the loudest
    possible signal that the net debt figure is wrong, and because a negative
    implied share price is not a usable valuation to put in front of anybody. The
    check passes the arithmetic and refuses the presentation.
    """
    errors: List[str] = []
    failing_scenarios: List[str] = []

    for val in spec.valuation:
        # Base scenario only, for the same reason as the deviation check: a bear
        # case that wipes out the equity of a levered company is the scenario
        # working, not the input being wrong. What is *not* legitimate in any
        # scenario is a negative implied share price being published as a
        # valuation, and that is what the frontend refuses to render.
        if val.scenario != "base":
            continue
        b = val.dcf_bridge
        equity = b.equity_value
        price = b.implied_share_price
        if equity is None:
            continue
        if equity <= 0:
            # enterprise_value and less_net_debt are Optional. Formatting them
            # unguarded raised TypeError on any spec where either is null, which
            # surfaced as a crashed check rather than a reported one - and the
            # pipeline's exception handler names the fallback record after the
            # function, so a crash was differenced against the baseline as both
            # a regression and a fix at once.
            ev_txt = "n/a" if b.enterprise_value is None else f"{b.enterprise_value:,.0f}"
            nd_txt = "n/a" if b.less_net_debt is None else f"{b.less_net_debt:,.0f}"
            errors.append(
                f"base: equity value {equity:,.0f} is not positive "
                f"(enterprise value {ev_txt}, net debt "
                f"{nd_txt}). A negative implied price of {price} is not a "
                f"usable valuation. Confirm the debt and cash figures on the bridge "
                f"before this model is served. A negative equity value is correct for a "
                f"company whose net worth really is negative, so this is a request to "
                f"confirm, not a declaration that the company is worthless."
            )
            failing_scenarios.append(val.scenario)

    passed = not errors
    return ModelCheckResult(
        check_name="equity_value_positive",
        category="data_quality",
        passed=passed,
        detail="" if passed else "; ".join(errors),
        implicated_canonical_keys=["equity_value", "less_net_debt", "implied_share_price"],
        implicated_periods=[],
        implicated_scenarios=sorted(set(failing_scenarios)),
    )


def check_implied_price_deviation_is_explainable(spec: ModelSpecification) -> ModelCheckResult:
    """The DCF should not sit an implausible distance from the traded price.

    This is the last line of the loop. If a model has passed every accounting
    check, reconciled its own bridge, and still disagrees with the market by
    60% or more, then the inputs are the remaining suspect and this says so.

    It is a data-quality check rather than a valuation one on purpose. A DCF is
    entitled to disagree with the market. It is not entitled to do so on the back
    of a debt figure that contradicts the lease figure printed beside it.
    """
    errors: List[str] = []
    failing_scenarios: List[str] = []

    for val in spec.valuation:
        # Base scenario only, deliberately.
        #
        # A bull or bear case exists precisely to disagree with the market, and
        # the further out it goes the more it is doing what it was built to do.
        # Applying a plausibility band to them means the check fires on scenarios
        # that are correct by construction, which is the fastest way to teach
        # everyone to ignore it. The base case is the one number a reader treats
        # as the valuation, so the base case is the one held to a band.
        if val.scenario != "base":
            continue
        b = val.dcf_bridge
        implied = b.implied_share_price
        market = getattr(val.reverse_dcf, "market_price", None) if val.reverse_dcf else None
        if implied is None or not market or market <= 0:
            continue
        deviation = (implied - market) / market
        if deviation < IMPLIED_DEVIATION_FLOOR or deviation > IMPLIED_DEVIATION_CEILING:
            errors.append(
                f"base: implied {implied:,.2f} against a market price of "
                f"{market:,.2f} is {deviation:+.1%}. Past {IMPLIED_DEVIATION_FLOOR:+.0%} the "
                f"probable cause is a misread input rather than a valuation view; check the "
                f"debt, share count and terminal assumptions before serving this. "
                f"Bull and bear are excluded on purpose: they are meant to disagree."
            )
            failing_scenarios.append(val.scenario)

    passed = not errors
    return ModelCheckResult(
        check_name="implied_price_deviation_is_explainable",
        category="data_quality",
        passed=passed,
        detail="" if passed else "; ".join(errors),
        implicated_canonical_keys=["implied_share_price", "market_price", "total_debt"],
        implicated_periods=[],
        implicated_scenarios=sorted(set(failing_scenarios)),
    )



# A year-one revenue growth rate above this is not a fast-growing business, it is
# a bad input that reached the forecast intact. 2.0 means a company doubling in a
# year, which is a real thing for a genuinely new market and still leaves an
# order of magnitude of headroom over anything credible.
#
# The point of a second, independent guard is that it does not share a failure
# mode with the first. The run-rate band rejects a bad reading at its source; this
# rejects the consequence. A third input path added later, or a different
# provider, can produce the same explosion without ever calling the band.
MAX_PLAUSIBLE_YEAR_ONE_GROWTH = 200.0


def check_year_one_growth_is_plausible(spec: ModelSpecification) -> ModelCheckResult:
    """The first forecast year's revenue growth must be defensible.

    A DCF is entitled to disagree with the market, and to assume a company grows
    quickly. It is not entitled to compound a bad input for five years and print
    the result. This catches the specific failure where a single misread trailing
    revenue becomes a three-figure growth rate, and it reports the driver and the
    source string so the cause is visible rather than inferred from the output.
    """
    errors: List[str] = []
    failing_periods: List[str] = []

    assumptions = getattr(spec, "assumptions", None) or []
    for a in assumptions:
        key = getattr(a, "driver_key", "") or ""
        if key != "revenue_growth":
            continue
        if getattr(a, "scenario", "base") != "base":
            # Bull and bear are allowed to disagree with history, and that is
            # what they are for. Only the base case is published as the reading.
            continue
        value = getattr(a, "value", None)
        if value is None:
            continue
        if value <= MAX_PLAUSIBLE_YEAR_ONE_GROWTH:
            continue
        period = getattr(a, "period", "") or ""
        source = str(getattr(a, "source", "") or "")[:170]
        errors.append(
            f"base {period} revenue growth is {value:+,.1f}%, which is beyond a "
            f"doubling in a year. Driver source: {source}"
        )
        failing_periods.append(period)

    passed = not errors
    return ModelCheckResult(
        check_name="year_one_growth_is_plausible",
        category="data_quality",
        passed=passed,
        detail="" if passed else "; ".join(errors),
        implicated_canonical_keys=["revenue_growth"],
        implicated_periods=sorted(set(failing_periods)),
        implicated_scenarios=["base"],
    )


def check_income_statement_is_coherent(spec: ModelSpecification) -> ModelCheckResult:
    """A company's income statement must be possible, not merely self-consistent.

    This is the check whose absence let a third break through. A hospital chain
    reported cost of revenue at 2.1x its revenue and an operating expense line of
    minus 8,669 crore. Those two are wrong in opposite directions, so they offset:
    revenue less cost less other expense lands exactly on the operating profit the
    feed also reported, and the statement foots to the rupee. Every existing
    check passed. The forecast then anchored gross margin on MINUS 121%, EBIT came
    out negative, and the DCF produced a negative enterprise value for a business
    earning 440 crore of operating profit.

    Arithmetic that agrees with itself is not evidence of an input that is right.
    These three are not opinions about whether a business is healthy. They are
    identities that cannot be false:

      * cost of sales cannot exceed revenue in a period with positive gross profit
      * an expense line is a cost, so it is not negative
      * gross profit and operating profit cannot have opposite signs while the
        expense lines between them are positive
    """
    errors: List[str] = []
    failing_periods: List[str] = []

    hist = getattr(spec, "historicals", None)
    if hist is None:
        return ModelCheckResult(
            check_name="income_statement_is_coherent",
            category="data_quality",
            passed=True,
        )

    values: dict = {}
    for item in getattr(hist, "line_items", []) or []:
        key = getattr(item, "canonical_key", "") or ""
        period = getattr(item, "period_label", "") or ""
        if not period:
            continue
        values.setdefault(period, {})[key] = getattr(item, "value", None)

    for period, row in sorted(values.items()):
        revenue = row.get("canonical.is.revenue")
        cost = row.get("canonical.is.cost_of_sales")
        gross = row.get("canonical.is.gross_profit")
        ebit = row.get("canonical.is.operating_profit")
        if not revenue or revenue <= 0:
            continue

        # A cost that exceeds revenue is a gross loss. That is possible for a
        # company in distress, so on its own it is only reported when it is large
        # enough that the forecast should not be anchored on it.
        if cost is not None and cost > revenue and (gross is not None and gross < 0):
            errors.append(
                f"{period}: cost of sales {cost:,.0f} exceeds revenue {revenue:,.0f}, "
                f"so gross profit is {gross:,.0f}. A forecast cannot be anchored on a "
                f"gross margin of {gross / revenue:.0%}."
            )
            failing_periods.append(period)

        # An expense line that is negative is a sign convention error or a plug.
        # It is reported separately because it is the tell: it is how an inflated
        # cost gets offset so the statement still foots.
        other = row.get("canonical.is.other_expenses")
        if other is not None and other < 0 and abs(other) > 0.01 * revenue:
            errors.append(
                f"{period}: other expenses are {other:,.0f}. An expense is a cost and "
                f"is not negative; a negative line here is absorbing an inflated cost "
                f"so the statement foots."
            )
            failing_periods.append(period)

        # Positive operating profit on a negative gross profit means the expense
        # lines between them are negative. Whichever line is wrong, the statement
        # cannot be right.
        if gross is not None and ebit is not None and gross < 0 < ebit:
            errors.append(
                f"{period}: gross profit {gross:,.0f} is negative while operating "
                f"profit is {ebit:,.0f}. The expense lines between them must be "
                f"negative, which is not a cost structure."
            )
            failing_periods.append(period)

    passed = not errors
    return ModelCheckResult(
        check_name="income_statement_is_coherent",
        category="data_quality",
        passed=passed,
        detail="" if passed else "; ".join(errors),
        implicated_canonical_keys=[
            "canonical.is.revenue",
            "canonical.is.cost_of_sales",
            "canonical.is.gross_profit",
            "canonical.is.operating_profit",
        ],
        implicated_periods=sorted(set(failing_periods)),
        implicated_scenarios=[],
    )

def run_all(spec: ModelSpecification) -> List[ModelCheckResult]:
    return [
        check_bridge_inputs_plausible(spec),
        check_equity_value_positive(spec),
        check_implied_price_deviation_is_explainable(spec),
        check_year_one_growth_is_plausible(spec),
        check_income_statement_is_coherent(spec),
    ]
