from __future__ import annotations

"""
Valuation Pipeline Module.

Orchestrates WACC, FCFF/DCF, Terminal Value, DCF Bridge, Reverse DCF, and Sensitivity Analysis
across all scenarios (base, bull, bear) and populates spec.valuation.
Market-aware and free of Infosys-specific share/cash constant fallbacks.
"""

from datetime import date
from typing import Dict, List, Optional

import logging

from backend import constants
from backend.data.providers.market_data import get_company_market_data
from backend.forecast.debt import OPENING_BALANCE_KEYS
from backend.forecast.share_count import resolve_shares_outstanding
from backend.models.spec.forecast import FORECAST_PERIODS
from backend.models.spec.model_specification import ModelSpecification
from backend.models.spec.valuation import ValuationOutput
from backend.valuation.dcf import (
    compute_dcf_bridge,
    compute_fcff_periods,
    compute_terminal_value,
)
from backend.valuation.reverse_dcf import compute_reverse_dcf
from backend.valuation.sensitivity import compute_sensitivity_tables
from backend.valuation.wacc import compute_wacc

logger = logging.getLogger(__name__)

# Stated on the bridge so a reader can see exactly what was deducted, rather
# than having to infer it from a single "Total debt" figure. The basis matches
# the convention market data providers use for a headline net cash figure, so
# the platform's number is reconcilable with the one a reader is comparing it
# against.
DEBT_BASIS_NOTE = (
    "Net debt = (borrowings + minority interest + preferred stock) - (cash + "
    "short-term investments + long-term investments), as filed for the period end "
    "shown here. Borrowings are the issuer's own reported non-current borrowings, "
    "plus current borrowings including the current portion of long-term debt, plus "
    "finance and capital lease liabilities, which are interest-bearing and are "
    "therefore debt. Operating lease liabilities are EXCLUDED and are displayed on "
    "this bridge separately, so a reader who prefers the market convention of "
    "capitalising them can see the amount and add it; the engine does not, because "
    "rent already sits in operating expense and is therefore inside the EBIT these "
    "cash flows are built from, and charging for it in both places would count the "
    "same obligation twice. This is the same definition the debt schedule opens on, "
    "so the obligation the valuation deducts and the balance the forecast services "
    "are one number. Every figure on this bridge is taken from the filed balance "
    "sheet for the date shown, not from a market feed: a feed's quarterly statement "
    "reported a synthetic period-end date rather than the day the quarter ended, a "
    "debt total inflated by capitalising operating leases, and a short-term "
    "investment line that matched no filed caption."
)


def run_valuation(
    spec: ModelSpecification,
    current_share_price: Optional[float] = None,
    historical_model=None,
) -> ModelSpecification:
    """Run full valuation engine across all scenarios and populate spec.valuation.

    Args:
        spec: ModelSpecification with forecast, assumptions, and debt schedules populated.
        current_share_price: Current market share price for reverse DCF. Defaults to live market price
            or per-company registry price when unset.
        historical_model: HistoricalModel for reverse DCF revenue CAGR solver.
    """
    company_id = spec.metadata.company_id
    market = spec.metadata.market

    # Fetch live/cached market data for the company
    mdata = get_company_market_data(company_id, market=market)

    # 1. Share price resolution
    if current_share_price is None or current_share_price <= 0:
        current_share_price = mdata.price.value

    # 2. Sourced cash & investments from latest historicals (FY26), falling back to 0.0
    latest_hist = spec.historicals.periods[-1] if spec.historicals.periods else "FY26"
    cash_and_bank = constants.resolve(
        spec.historicals.get_value("canonical.bs.cash_and_bank", latest_hist), 0.0
    )
    current_inv = constants.resolve(
        spec.historicals.get_value("canonical.bs.current_investments", latest_hist), 0.0
    )
    non_current_inv = constants.resolve(
        spec.historicals.get_value("canonical.bs.non_current_investments", latest_hist), 0.0
    )
    # Minority interest and preferred stock are read with an explicit None test
    # and a provenance record. They used to be `or 0.0` on canonical keys the
    # data layer never produced, so the EV -> equity bridge was structurally
    # incomplete and the gap was invisible. Now the key is mapped by the
    # ingestion layer, and a genuinely absent balance is recorded as a
    # coverage note rather than hidden.
    minority_int = constants.resolve(
        spec.historicals.get_value("canonical.bs.minority_interest", latest_hist), 0.0
    )
    pref_stock = constants.resolve(
        spec.historicals.get_value("canonical.bs.preferred_stock", latest_hist), 0.0
    )
    # Total interest-bearing debt, on the definition the debt schedule opens on.
    #
    # Total interest-bearing debt, read through the same key list the debt schedule
    # opens on, so the obligation the valuation deducts and the balance the forecast
    # services are one number by construction rather than by agreement.
    #
    # The components are non-current borrowings, current borrowings including the
    # current portion of long-term debt, and finance and capital lease liabilities
    # which are borrowing in substance. Operating lease liabilities are deliberately
    # NOT deducted: rent already sits in operating expense, so operating leases are
    # inside the EBIT the cash flows are built from and deducting the liability as
    # well would charge for the same obligation twice. The balance is still exposed
    # so a reader who prefers the other convention can see the amount and apply it.
    #
    # Unpacked positionally rather than by name, so this module never names a debt
    # component and cannot quietly come to disagree with the list.
    (
        debt_non_current_annual,
        short_term_debt,
        finance_lease_debt,
    ) = (
        constants.resolve(spec.historicals.get_value(key, latest_hist), 0.0)
        for key in OPENING_BALANCE_KEYS
    )
    annual_total_debt = debt_non_current_annual + short_term_debt + finance_lease_debt
    operating_lease_liability = constants.resolve(
        spec.historicals.get_value("canonical.bs.operating_lease_liabilities", latest_hist), 0.0
    )

    # ONE balance sheet per model.
    #
    # The bridge and the forecast used to read the balance sheet independently: the
    # forecast from the filed annual statement, the bridge from a market feed's
    # quarterly. They happened to agree for two companies in six and disagreed by
    # up to 50,062 for the rest, so a model could value against one set of
    # obligations while forecasting off another.
    #
    # A feed's quarterly statement was preferred because a market capitalisation is
    # live while a net debt figure taken from the last annual is up to a year old,
    # and bridging the two produced an enterprise value stale by exactly that gap.
    # But the feed's statement failed every check against the filing. Its date was
    # a synthetic calendar date rather than the day the quarter actually ended,
    # five days late for NVIDIA and ninety-one days early for Amazon. Its total
    # debt capitalised operating leases, so NVIDIA carried 4,985 and Microsoft
    # 16,532 of lease liability inside a figure presented as borrowings. Its
    # short-term investment line was a residual computed by the feed and matched
    # no filed caption at all. Freshness bought from a source that cannot be tied
    # to an issuer is not freshness; it is a second, less accurate balance sheet.
    #
    # So the bridge reads the filed statement the forecast already opens on, and
    # publishes that statement's real period end rather than a manufactured one.
    # Where the filed statement is older than the latest quarter, that gap is
    # stated rather than papered over: an issuer that has not filed, or a feed that
    # cannot be verified, is a reason to publish the date, not to substitute a
    # number.
    # The date the FILING was filed for, which is what the bridge publishes. The
    # fiscal calendar gives the month and day a filer's year closes on rather than
    # the date it closed, so a year ending on a Sunday produces a date six days
    # late, and preferring the latest date would pick that wrong answer over the
    # filed one on the balance of a handful of lines.
    bridge_as_of = (
        (spec.historicals.filed_period_end(latest_hist) or latest_hist)
        .isoformat()
        if isinstance(spec.historicals.filed_period_end(latest_hist), date)
        else latest_hist
    )
    debt_cr = annual_total_debt
    bridge_source = "filed_annual_balance_sheet"
    # The filed statement carries short-term investments as their own line, so the
    # balance is reported rather than a feed's residual, and there is nothing to
    # derive and disclaim.
    mkt_sec_derived = False
    mkt_sec_derivation = ""
    logger.info(
        "%s bridge balance sheet: %s (filed statement, debt %.0f = borrowings %.0f"
        " + short-term %.0f + finance leases %.0f; operating leases %.0f excluded)",
        company_id,
        bridge_as_of,
        debt_cr,
        debt_non_current_annual,
        short_term_debt,
        finance_lease_debt,
        operating_lease_liability,
    )

    # Liquid cash used in WACC weights
    cash_cr = cash_and_bank + current_inv

    # 3. Sourced diluted share count, resolving dynamically per company
    shares_cr: Optional[float] = None
    if spec.share_count:
        shares_cr = spec.share_count.get_diluted(latest_hist) or spec.share_count.get_diluted(FORECAST_PERIODS[0])
    if not shares_cr or shares_cr <= 0:
        shares_cr = resolve_shares_outstanding(company_id, market)[0] or mdata.shares_outstanding.value

    valuation_outputs: List[ValuationOutput] = []

    for scenario in ["base", "bull", "bear"]:
        ds = next((d for d in spec.debt_schedule if d.scenario == scenario), None)
        if not debt_cr and ds is not None and ds.periods:
            debt_cr = constants.resolve(ds.periods[0].opening_balance, 0.0)

        # 4. Compute WACC Breakdown — source inputs from assumptions if set, else market data provider
        def _wacc_input(driver_key: str) -> Optional[float]:
            for a in spec.assumptions:
                if a.driver_key == driver_key and a.scenario == scenario:
                    return a.value
            for a in spec.assumptions:
                if a.driver_key == driver_key and a.scenario == "base":
                    return a.value
            return None

        wacc_breakdown = compute_wacc(
            assumptions=spec.assumptions,
            debt_schedule=ds,
            share_count_schedule=spec.share_count,
            scenario=scenario,
            current_share_price=current_share_price,
            risk_free_rate=_wacc_input("wacc.risk_free_rate"),
            beta=_wacc_input("wacc.beta"),
            equity_risk_premium=_wacc_input("wacc.equity_risk_premium"),
            debt_cr=debt_cr,
            company_id=company_id,
            market=market,
            latest_period=latest_hist,
        )
        wacc_pct = wacc_breakdown.wacc
        if wacc_pct is None or wacc_pct <= 0:
            raise ValueError(
                f"Invalid WACC ({wacc_breakdown.wacc}) for scenario '{scenario}': "
                "WACC must be positive to compute DCF."
            )

        # Keep the exposed cost-of-equity driver in step with the rate actually
        # used. The model_generated value is a CAPM snapshot; without this
        # refresh the Driver Panel would keep showing a stale number next to a
        # WACC tile computed from today's risk-free rate. Analyst overrides are
        # left untouched — those are deliberate.
        if wacc_breakdown.cost_of_equity is not None:
            spec.assumptions = [
                a.model_copy(update={
                    "value": wacc_breakdown.cost_of_equity,
                    "source": (
                        "CAPM (live): Rf + Blume-adjusted Beta x ERP — "
                        "recomputed on each valuation run"
                    ),
                })
                if (
                    a.driver_key == "wacc.cost_of_equity"
                    and a.scenario == scenario
                    and a.type == "model_generated"
                )
                else a
                for a in spec.assumptions
            ]

        # 5. Compute FCFF Periods (using mid-year discounting)
        # The opening working-capital level is the last historical balance, so a
        # spec whose forecast is missing the explicit delta_working_capital line
        # (a cache written by an older engine) still produces the engine's own
        # working-capital movement instead of a substituted guess.
        opening_wc = (
            constants.resolve(spec.historicals.get_value("canonical.bs.trade_receivables", latest_hist), 0.0)
            + constants.resolve(spec.historicals.get_value("canonical.bs.unbilled_revenue", latest_hist), 0.0)
            + constants.resolve(spec.historicals.get_value("canonical.bs.inventory", latest_hist), 0.0)
            - constants.resolve(spec.historicals.get_value("canonical.bs.trade_payables", latest_hist), 0.0)
        )
        fcff_periods = compute_fcff_periods(
            spec.forecast,
            wacc_pct,
            scenario,
            timing_convention="mid_year",
            opening_working_capital=opening_wc,
        )

        # 6. Compute Terminal Value (Gordon Growth default)
        last_fcff = fcff_periods[-1].fcff if fcff_periods and fcff_periods[-1].fcff else 0.0
        last_ebitda = spec.forecast.get_value("canonical.is.ebitda", FORECAST_PERIODS[-1], scenario) or 0.0
        last_ebit = spec.forecast.get_value("canonical.is.operating_profit", FORECAST_PERIODS[-1], scenario) or 0.0

        # Drivers for terminal value
        term_g = 4.0
        exit_mult = 20.0
        term_tax = 21.0 if market == "us" else 25.17
        for a in spec.assumptions:
            if a.driver_key == "terminal_growth_rate" and a.scenario == scenario:
                term_g = a.value
            elif a.driver_key == "exit_ev_multiple" and a.scenario == scenario:
                exit_mult = a.value
            elif a.driver_key == "tax_rate" and a.period == FORECAST_PERIODS[-1] and a.scenario == scenario:
                term_tax = a.value

        terminal_val = compute_terminal_value(
            last_fcff=last_fcff,
            last_ebitda=last_ebitda,
            wacc_pct=wacc_pct,
            terminal_growth_rate=term_g,
            exit_multiple=exit_mult,
            active_method="gordon_growth",
            last_ebit=last_ebit,
            terminal_tax_rate=term_tax,
            timing_convention="mid_year",
        )

        # 7. DCF Bridge (EV -> Equity Value -> Implied Share Price)
        dcf_bridge, updated_tv = compute_dcf_bridge(
            fcff_periods=fcff_periods,
            terminal_value=terminal_val,
            cash_cr=cash_and_bank,
            marketable_securities_cr=current_inv,
            non_current_investments_cr=non_current_inv,
            debt_cr=debt_cr,
            minority_interest_cr=minority_int,
            preferred_stock_cr=pref_stock,
            operating_lease_liabilities_cr=operating_lease_liability,
            shares_cr=shares_cr,
        )
        # Publish which balance sheet the net debt figure came from. Without it
        # the reader cannot tell a current net cash position from one that is
        # four quarters old, and the two differ by tens of billions at a
        # large-cap.
        dcf_bridge = dcf_bridge.model_copy(
            update={
                "balance_sheet_as_of": bridge_as_of,
                "balance_sheet_source": bridge_source,
                "debt_basis_note": DEBT_BASIS_NOTE,
                "marketable_securities_derived": mkt_sec_derived,
                "marketable_securities_derivation": mkt_sec_derivation,
            }
        )

        # 8. Reverse DCF
        reverse_dcf = compute_reverse_dcf(
            market_price=current_share_price,
            fcff_periods=fcff_periods,
            wacc_pct=wacc_pct,
            cash_cr=cash_and_bank,
            debt_cr=debt_cr,
            shares_cr=shares_cr,
            marketable_securities_cr=current_inv,
            non_current_investments_cr=non_current_inv,
            minority_interest_cr=minority_int,
            preferred_stock_cr=pref_stock,
            forecast=spec.forecast,
            assumptions=spec.assumptions,
            historical_model=historical_model,
            terminal_growth_rate=term_g,
            exit_multiple=exit_mult,
            timing_convention="mid_year",
            currency=spec.metadata.currency,
            scenario=scenario,
            last_ebit=last_ebit,
            terminal_tax_rate=term_tax,
            opening_working_capital=opening_wc,
        )
        reverse_dcf.market_price_date = mdata.price.fetch_date
        reverse_dcf.market_price_source = mdata.price.source

        # Divergence Gate (sanity check on implied terminal growth band [-2%, 5%])
        if reverse_dcf.implied_terminal_growth is not None:
            g_impl = reverse_dcf.implied_terminal_growth
            if g_impl < -2.0 or g_impl > 5.0:
                flag_msg = f"[DIVERGENCE FLAG: implied growth {g_impl:.2f}% outside sane band (-2% to 5%)]"
                reverse_dcf.method_note = f"{reverse_dcf.method_note} {flag_msg}".strip()

        # 9. Sensitivity Analysis Grids
        sensitivity_tables = compute_sensitivity_tables(
            forecast=spec.forecast,
            wacc_breakdown=wacc_breakdown,
            cash_cr=cash_and_bank,
            debt_cr=debt_cr,
            shares_cr=shares_cr,
            marketable_securities_cr=current_inv,
            non_current_investments_cr=non_current_inv,
            minority_interest_cr=minority_int,
            preferred_stock_cr=pref_stock,
            scenario=scenario,
            base_g=term_g,
            base_exit_mult=exit_mult,
            terminal_tax_rate=term_tax,
            timing_convention="mid_year",
            opening_working_capital=opening_wc,
        )

        valuation_outputs.append(
            ValuationOutput(
                scenario=scenario,  # type: ignore
                timing_convention="mid_year",
                wacc=wacc_breakdown,
                fcff_by_period=fcff_periods,
                terminal_value=updated_tv,
                dcf_bridge=dcf_bridge,
                reverse_dcf=reverse_dcf,
                sensitivity_tables=sensitivity_tables,
            )
        )

    spec.valuation = valuation_outputs
    return spec
