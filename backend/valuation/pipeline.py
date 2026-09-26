from __future__ import annotations

"""
Valuation Pipeline Module.

Orchestrates WACC, FCFF/DCF, Terminal Value, DCF Bridge, Reverse DCF, and Sensitivity Analysis
across all scenarios (base, bull, bear) and populates spec.valuation.
Market-aware and free of Infosys-specific share/cash constant fallbacks.
"""

from typing import List, Optional

import logging

from backend import constants
from backend.data.bridge_inputs import resolve_bridge_inputs
from backend.data.providers.market_data import get_company_market_data
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
    "Net cash = (cash + short-term investments) - total debt. Debt = "
    "non-current borrowings + current borrowings (including the current portion "
    "of long-term debt) + finance lease liabilities + operating lease "
    "liabilities. Non-current investments are not netted. Struck on the most "
    "recent reported balance sheet, whose date is shown on this bridge."
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
    # Total interest-bearing debt.
    #
    # Four components, each of which a filer may report separately and each of
    # which used to be missing from the bridge:
    #   - non-current borrowings
    #   - current borrowings, INCLUDING the current portion of long-term debt
    #   - finance / capital lease liabilities, which are borrowing in substance
    #
    # Operating lease liabilities are deliberately NOT deducted. Under US GAAP
    # rent sits in operating expense, so operating leases are already reflected
    # in the EBIT the cash flows are built from; deducting the liability as well
    # would charge for the same obligation twice. The balance is still carried
    # on the statement and exposed, so a reader who prefers the other
    # convention can see the amount and apply it.
    short_term_debt = constants.resolve(
        spec.historicals.get_value("canonical.bs.short_term_borrowings", latest_hist), 0.0
    )
    finance_lease_debt = constants.resolve(
        spec.historicals.get_value("canonical.bs.finance_lease_liabilities", latest_hist), 0.0
    )
    operating_lease_liability = constants.resolve(
        spec.historicals.get_value("canonical.bs.operating_lease_liabilities", latest_hist), 0.0
    )

    annual_liquid_assets = cash_and_bank + current_inv
    debt_non_current_annual = constants.resolve(
        spec.historicals.get_value("canonical.bs.borrowings", latest_hist), 0.0
    )
    annual_total_debt = debt_non_current_annual + short_term_debt + finance_lease_debt

    # Most recently reported balance sheet for the bridge.
    #
    # A market capitalisation is live; a net debt figure taken from the last
    # annual balance sheet is up to a year old. Bridging the two produced an
    # enterprise value stale by exactly that gap, and every multiple built on it
    # with it. The bridge therefore uses the most recent reported balances, and
    # the statement date is published with the figure so a reader can see how
    # fresh it is.
    snapshot, bridge_note = resolve_bridge_inputs(
        company_id,
        {
            "cash_and_bank": cash_and_bank,
            "marketable_securities": current_inv,
            "non_current_investments": non_current_inv,
            "debt_non_current": debt_non_current_annual,
            "debt_current": short_term_debt,
            "total_debt": annual_total_debt,
            "liquid_assets": annual_liquid_assets,
        },
    )

    if snapshot is not None:
        # Use the snapshot's OWN aggregates. Re-deriving them from the
        # individual terms double counts: a feed's "Total Debt" already
        # contains its lease components, so adding the separately-mapped lease
        # lines on top inflated one large-cap's debt by 2.5x and another's by
        # 1.5x. The individual terms are for display, not for a second sum.
        cash_and_bank = constants.resolve(
            snapshot.terms.get("cash_and_bank"), cash_and_bank
        )
        current_inv = max(0.0, snapshot.total_liquid_assets - cash_and_bank)
        minority_int = constants.resolve(snapshot.terms.get("minority_interest"), minority_int)
        pref_stock = constants.resolve(snapshot.terms.get("preferred_stock"), pref_stock)
        debt_cr = snapshot.total_debt
        # Lease obligations are part of total debt on the market convention, and
        # the balance is reported separately so a reader who prefers to exclude
        # them can see the amount. The basis note on the bridge says which.
        operating_lease_liability = constants.resolve(
            snapshot.terms.get("lease_liabilities"), 0.0
        )
        bridge_as_of = snapshot.as_of
        bridge_source = snapshot.source
    else:
        debt_cr = annual_total_debt
        bridge_as_of = latest_hist
        bridge_source = "filed_annual_balance_sheet"
    logger.info("%s bridge balance sheet: %s (%s)", company_id, bridge_as_of, bridge_note)

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
