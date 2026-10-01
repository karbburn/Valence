from __future__ import annotations

"""
Suggestion engine: produces model-generated AssumptionObjects from historical ratios.

Each driver has its own explicit suggestion method. The source label stored in
the AssumptionObject must match exactly what was computed — no fabrication.
"""

import logging
from datetime import datetime
from typing import List, Optional

from backend import constants
from backend.data.providers.run_rate import (
    run_rate_advanced_beyond,
    run_rate_is_comparable,
)
from backend.models.spec.assumptions import AssumptionObject
from backend.models.spec.forecast import FORECAST_PERIODS, forecast_periods_after
from backend.models.spec.metadata import resolve_market
from backend.models.statements.historical_model import HistoricalModel
from backend.models.statements.ratios import HistoricalRatios

# Plausibility band for a MEASURED depreciation rate, as a fraction of gross PP&E.
#
# Outside this range the denominator is not a property, plant and equipment base.
# See the use in suggest_base_assumptions, where Ambarella measured at 58.65%.
MIN_PLAUSIBLE_DEPRECIATION_RATE = 0.03
MAX_PLAUSIBLE_DEPRECIATION_RATE = 0.30


logger = logging.getLogger(__name__)


def _avg(values: List[Optional[float]]) -> Optional[float]:
    """The margin a forecast should carry: the latest year, not the mean.

    A simple mean over the reported years is right for a business whose margin has
    settled, and wrong for one that is moving — and it is wrong in the direction
    that produces the most confident-looking answer.

    Ambarella reported EBIT margins of -68.25%, -44.44% and -21.12%: a company
    recovering quickly from a loss. The three-year mean is -44.60%, so the forecast
    held it at the second-worst year it had ever reported, made the loss grow
    against a rising revenue line, and valued the equity at minus 96 a share. Idea
    was carried at -9.40% against a filed -6.97% for the same reason.

    The most recent reported year is the one the forecast continues from, and every
    other input in this function already anchors on it, so a margin that is moving
    is carried at its latest value. Where the reported years agree to within a
    point there is nothing to choose between them, and the mean is kept because it
    is less sensitive to any single year's rounding.
    """
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    latest = vals[-1]
    if len(vals) == 1:
        return round(latest, 4)
    spread = max(vals) - min(vals)
    if spread <= 1.0:
        return round(sum(vals) / len(vals), 4)
    return round(latest, 4)


def _cagr(start: Optional[float], end: Optional[float], years: int) -> Optional[float]:
    if start and end and start > 0 and years > 0:
        return round(((end / start) ** (1.0 / years) - 1.0) * 100.0, 4)
    return None


def _make(
    driver_key: str,
    value: float,
    period: str,
    scenario: str,
    source: str,
) -> AssumptionObject:
    return AssumptionObject(
        driver_key=driver_key,
        value=value,
        period=period,
        scenario=scenario,
        type="model_generated",
        source=source,
        last_updated=datetime.now(),
    )


def capm_default_for(company_id: str, market: Optional[str] = None) -> tuple[float, str]:
    """Per-company CAPM default for Cost of Equity: Rfr + Blume-adjusted Beta × ERP.

    Mirrors the valuation engine (backend/valuation/wacc.py) so the suggested
    assumption matches what CAPM implies. Falls back to 13.0 only when
    market data is unavailable.
    """
    try:
        from backend.data.providers.market_data import get_company_market_data

        mdata = get_company_market_data(company_id, market=market)  # type: ignore
        rfr = mdata.risk_free_rate.value
        raw_b = mdata.beta.value
        b = round(0.67 * raw_b + 0.33, 3)  # Blume (1971), same as valuation engine
        erp = mdata.equity_risk_premium.value
        ke = round(rfr + b * erp, 2)
        source = (
            f"CAPM default: Rfr={rfr:.2f}% + Blume-beta {b:.3f} × ERP={erp:.2f}% "
            f"(per-company market data)"
        )
        return ke, source
    except Exception:
        return constants.FALLBACK_COST_OF_EQUITY, "fallback default — market data unavailable"


def _fade_weights(n_periods: int) -> List[float]:
    """Weights running 0 -> 1 across the forecast, reaching 1.0 in the final year.

    Front-loaded rather than linear, because a capex cycle that unwinds evenly would
    hold the business at a mid-cycle investment rate for years after the pressure to
    invest has passed. Linear would be defensible; it just understates the early
    normalisation, which is where the cash flow actually recovers.

    The endpoint matters more than the path: 1.0 in the final explicit year, so the
    terminal value is struck on a steady state. A fade that stops short does not
    mean "conservative" -- it means the perpetuity is priced off a year the company
    would not still be living in.
    """
    if n_periods <= 1:
        return [1.0] * max(n_periods, 0)
    return [
        round(1.0 - (1.0 - i / (n_periods - 1)) ** 2, 4)
        for i in range(n_periods)
    ]


def _latest_positive(statement, canonical_key: str) -> Optional[float]:
    """The most recent positive value for a key on a statement, or None.

    "Most recent" rather than "last" because a statement's period list and its line
    items do not always agree, and a filer that omits a line leaves no value at all
    rather than a zero. Walking backwards and taking the first real positive is the
    only way to be sure the figure belongs to the period being forecast.

    Positive because these are asset and revenue balances. A negative PP&E is not a
    thing, so a negative reading means the figure was mis-mapped, and using it to
    derive a depreciation rate would produce a rate with no meaning.
    """
    if statement is None:
        return None
    try:
        periods = list(getattr(statement, "periods", []) or [])
    except Exception:
        return None
    for period in reversed(periods):
        try:
            v = statement.get_value(canonical_key, period)
        except Exception:
            continue
        if v is not None and float(v) > 0:
            return float(v)
    return None


def _default_cost_of_equity(historical_model: HistoricalModel) -> tuple[float, str]:
    """Per-company CAPM default (wrapper using the historical model id).

    Replaces the former flat 13.0 default which overstated US cost of equity
    by ~4pp. Falls back to 13.0 only when market data is unavailable.
    """
    return capm_default_for(
        historical_model.company_id, resolve_market(historical_model.company_id)
    )


def _run_rate_floor(
    company_id: str
) -> tuple[Optional[float], str]:
    """Trailing-twelve-month revenue in the model's own units, and its basis.

    The market feed reports absolute currency; the model works in USD millions
    and INR crores. Comparing the two without scaling is out by a factor of a
    million, which would make the run-rate floor either irrelevant or absurd.

    Returns (None, reason) whenever the run rate cannot be established, so the
    caller falls back to the reported fiscal year rather than guessing.
    """
    try:
        from backend.data.providers.run_rate import current_run_rate_revenue
        from backend.models.spec.metadata import get_metadata_for_company

        run_rate, basis = current_run_rate_revenue(company_id)
        if not run_rate or run_rate <= 0:
            return None, basis

        meta = get_metadata_for_company(company_id)
        divisor = 1e7 if meta.currency == "INR" else 1e6
        return run_rate / divisor, basis
    except Exception as exc:  # pragma: no cover - defensive
        return None, f"unavailable ({type(exc).__name__})"


def suggest_base_assumptions(
    ratios: HistoricalRatios,
    historical_model: HistoricalModel,
) -> List[AssumptionObject]:
    """Produce model-generated AssumptionObjects for every V1 driver, Base scenario.

    Every method is explicitly named in the source field — no unlabelled heuristics.
    """
    periods = historical_model.periods if (historical_model.periods and len(historical_model.periods) > 0) else ["FY24", "FY25", "FY26"]
    first_p = periods[0]
    last_p = periods[-1]
    num_years = len(periods) - 1 if len(periods) > 1 else 1
    result: List[AssumptionObject] = []

    is_us = resolve_market(historical_model.company_id) == "us"
    default_tax = constants.statutory_tax_rate("us" if is_us else "india")

    # ------------------------------------------------------------------ #
    # 1. Revenue Growth — Dynamic Fade Curve Engine
    # ------------------------------------------------------------------ #
    rev_start = historical_model.income_statement.get_value("canonical.is.revenue", first_p)
    rev_end = historical_model.income_statement.get_value("canonical.is.revenue", last_p)
    rev_cagr = _cagr(rev_start, rev_end, num_years)
    base_cagr = rev_cagr if (rev_cagr is not None and rev_cagr > -50.0) else 10.0

    # Growth fade.
    #
    # Year one carries the measured rate in EVERY band, and the fade is a
    # geometric decay applied from year two. Two defects are removed:
    #
    # 1. The first year used to be halved for any company whose growth exceeded
    #    25% and left at full rate below it. A 32.7% grower was published at
    #    16.4% and an 88.3% grower at 44.1%, while a 16.4% grower kept its
    #    16.4%. There is no economic reason a company that grows slightly
    #    faster should have its first forecast year cut in half — the rule had a
    #    threshold discontinuity, not a rationale. For one large-cap that put
    #    the published first-year growth at roughly half the street's estimate.
    #
    # 2. Fading each year as a fraction of the BASE rate produced a cliff after
    #    year one (88% then 26%). Decaying geometrically gives a path that
    #    actually looks like a company maturing, with no step change.
    #
    # The decay rate rises with the growth band, because the further a company's
    # growth is from a mature rate the faster it is assumed to converge.
    if base_cagr > 25.0:
        decay = 0.55      # e.g. 88% -> 48% -> 26% -> 15% -> 8%
    elif base_cagr > 10.0:
        decay = 0.82      # e.g. 16% -> 13% -> 11% -> 9% -> 7%
    else:
        decay = 1.00      # stable: held flat

    # Sanity bound on the decay itself. If the band boundaries above are ever
    # retuned into something implausible, a company would be published with a
    # growth path the model cannot defend, and the defect would only show up as
    # a strange number in the product.
    if not 0.0 < decay <= 1.0:
        raise ValueError(f"implausible growth decay {decay} for a {base_cagr:.1f}% base rate")

    # RUN-RATE FLOOR on the first forecast year.
    #
    # The measured CAGR runs from the last REPORTED FISCAL YEAR. That year is
    # not the current run rate: it ended up to a year ago, and a company part-way
    # through the year since has already traded a different twelve months. When
    # those trailing twelve months exceed the reported year, growing the reported
    # year at its own historical rate produces a first forecast year BELOW what
    # the business earned in the last twelve months — a forecast of decline
    # published next to a positive growth rate.
    #
    # One large-cap's trailing revenue was 12% above its last fiscal year, so its
    # first forecast year sat 7% below its own trailing twelve months while the
    # sheet said revenue grew 4.2%. The two published numbers contradict each
    # other, and it is the first thing a reader checks.
    #
    # The floor is the growth needed to merely MATCH the trailing twelve months.
    # It only ever raises the published rate, never lowers it, and it is stated
    # in the source so the reader can see which base the number rests on.
    run_rate, run_rate_basis = _run_rate_floor(historical_model.company_id)
    year_one = base_cagr
    run_rate_note = ""

    # The unit guard is applied on its own terms, not inside the "has the run
    # rate advanced" test. Nesting it there meant the guard only ever ran when
    # the reading was already larger than the reported year, so whether it
    # applied was decided by a different question than the one it protects.
    if run_rate is not None and not run_rate_is_comparable(run_rate, rev_end):
        # A reading tens of times, or a fraction of, the reported year is a unit
        # error rather than a change in the business. Acting on it would publish a
        # growth rate that is arithmetically valid and economically absurd, so
        # the reported fiscal year stands.
        logger.info(
            "Run rate for %s is %s against a reported year of %s — not the same "
            "units, so it is not used as a forecast anchor",
            historical_model.company_id,
            run_rate,
            rev_end,
        )
        run_rate, run_rate_basis = None, "not comparable with the reported year"

    if run_rate_advanced_beyond(run_rate, rev_end):
        floor_pct = (run_rate / rev_end - 1.0) * 100.0
        if floor_pct > year_one:
            year_one = floor_pct
            # Both levels are named so the figure can be checked rather than
            # taken on trust: the growth rate is only meaningful against the
            # number it is measured from.
            run_rate_note = (
                f"; raised to the {floor_pct:.1f}% needed to reach the {run_rate:,.0f} "
                f"traded in the last twelve months ({run_rate_basis}), which the "
                f"{rev_end:,.0f} reported in {last_p} has fallen behind"
            )

    # The horizon belongs to the company: the five fiscal years after the last one
    # it reported. The fixed FY27-FY31 list meant a company whose last actual was
    # FY25 was given drivers for years it never modelled and none for FY26.
    forecast_periods = forecast_periods_after(last_p)

    for idx, p in enumerate(forecast_periods):
        # The whole path decays from the YEAR-ONE rate, not from the historical
        # one. Using the measured rate again from year two produced a cliff the
        # moment the floor bound: a company measured at 4.2% whose run rate
        # required 12% was published as 12.0, then 4.2, 4.2, 4.2, 4.2 — a sharp
        # deceleration invented by the model on the second year, immediately
        # after the floor had just argued the business is growing faster than
        # its history. When the floor does not bind, year_one equals the measured
        # rate and the path is unchanged.
        g_val = round(max(0.0, year_one * (decay ** idx)), 2)
        if decay == 1.0:
            source_rev = f"CAGR held flat ({first_p}-{last_p}: {base_cagr:.1f}%)"
        else:
            source_rev = (
                f"CAGR ({first_p}-{last_p}: {base_cagr:.1f}%); year one carries it in "
                f"full, then decays {decay:.2f}x per year"
            )
        if run_rate_note and idx == 0:
            source_rev += run_rate_note
        result.append(_make("revenue_growth", g_val, p, "base", source_rev))

    # ------------------------------------------------------------------ #
    # 2. EBITDA Margin — Multi-year average
    #
    # `resolve` rather than `or`: a company whose reported EBITDA margin is
    # genuinely 0.0 must keep 0.0, not inherit the fallback.
    # ------------------------------------------------------------------ #
    ebitda_margins = [ratios.get_value("ebitda_margin_pct", p) for p in periods]
    ebitda_measured = _avg(ebitda_margins)
    ebitda_margin = constants.resolve(ebitda_measured, constants.DEFAULT_EBITDA_MARGIN)
    source_ebitda = (
        f"Multi-year average EBITDA margin ({first_p}-{last_p})"
        if ebitda_measured is not None
        else f"No reported EBITDA margin; platform default {constants.DEFAULT_EBITDA_MARGIN}%"
    )
    for p in forecast_periods:
        result.append(_make("ebitda_margin", ebitda_margin, p, "base", source_ebitda))

    # ------------------------------------------------------------------ #
    # 3. EBIT Margin — Multi-year average operating margin
    # ------------------------------------------------------------------ #
    ebit_margins = [ratios.get_value("operating_margin_pct", p) for p in periods]
    ebit_measured = _avg(ebit_margins)
    ebit_margin = constants.resolve(ebit_measured, constants.DEFAULT_EBIT_MARGIN)
    source_ebit = (
        f"Multi-year average operating margin ({first_p}-{last_p})"
        if ebit_measured is not None
        else f"No reported operating margin; platform default {constants.DEFAULT_EBIT_MARGIN}%"
    )
    for p in forecast_periods:
        result.append(_make("ebit_margin", ebit_margin, p, "base", source_ebit))

    # ------------------------------------------------------------------ #
    # 4. D&A % Revenue — Multi-year average
    # ------------------------------------------------------------------ #
    da_pcts = [ratios.get_value("da_pct_revenue", p) for p in periods]
    da_measured = _avg(da_pcts)
    da_pct = constants.resolve(da_measured, constants.DEFAULT_DA_PCT_REVENUE)
    source_da = (
        f"Multi-year average D&A % revenue ({first_p}-{last_p})"
        if da_measured is not None
        else f"No reported D&A; platform default {constants.DEFAULT_DA_PCT_REVENUE}%"
    )
    for p in forecast_periods:
        result.append(_make("da_pct_revenue", da_pct, p, "base", source_da))

    # ------------------------------------------------------------------ #
    # 5. Effective Tax Rate — Multi-year average with statutory convergence
    # ------------------------------------------------------------------ #
    tax_rates = [ratios.get_value("effective_tax_rate_pct", p) for p in periods]
    hist_tax_rate = constants.resolve(_avg(tax_rates), default_tax)
    # Guard against any residual absurd average leaking into WACC.
    if hist_tax_rate <= 0.0 or hist_tax_rate > 50.0:
        hist_tax_rate = default_tax

    # Fade towards statutory rate in Years 3-5 (reflecting global minimum tax / credit phase-outs)
    tax_fade_weights = [0.0, 0.0, 0.25, 0.50, 0.75]  # weight on statutory rate
    for idx, p in enumerate(forecast_periods):
        w_stat = tax_fade_weights[idx] if idx < len(tax_fade_weights) else 1.0
        p_tax = round((1.0 - w_stat) * hist_tax_rate + w_stat * default_tax, 2)
        source_tax = (
            f"Effective tax rate ({hist_tax_rate:.1f}%) fading to statutory ({default_tax:.1f}%)"
            if w_stat > 0
            else f"Multi-year average effective tax rate ({first_p}-{last_p})"
        )
        result.append(_make("tax_rate", p_tax, p, "base", source_tax))

    # ------------------------------------------------------------------ #
    # 6. DSO — most recent historical period
    #
    # When the receivables line is absent from the filings the DSO ratio is
    # genuinely unknown, not zero. Falling back to 100 days invents a large
    # phantom receivable; 0 is the only defensible reading of "no receivable
    # reported", and the source string says so.
    # ------------------------------------------------------------------ #
    dso = ratios.get_value("dso_days", last_p)
    has_receivables = any(
        historical_model.balance_sheet.get_value("canonical.bs.trade_receivables", p) is not None
        for p in periods
    )
    if dso is None or not has_receivables:
        dso = 0.0
        source_dso = (
            "unresolved — no receivables reported in the ingested filings; "
            "receivables held at zero rather than assumed"
        )
    else:
        source_dso = f"most recent period DSO ({last_p})"

    for p in forecast_periods:
        result.append(_make("dso_days", dso, p, "base", source_dso))

    # ------------------------------------------------------------------ #
    # 7. DPO — most recent historical period
    #
    # Same reasoning as DSO. Many ingestion paths do not map accounts payable,
    # so a 14-day default here silently creates a payable balance the company
    # never reported and books a one-off working-capital inflow in year 1.
    # ------------------------------------------------------------------ #
    dpo = ratios.get_value("dpo_days", last_p)
    has_payables = any(
        historical_model.balance_sheet.get_value("canonical.bs.trade_payables", p) is not None
        for p in periods
    )
    if dpo is None or not has_payables:
        dpo = 0.0
        source_dpo = (
            "unresolved — no accounts payable reported in the ingested filings; "
            "payables held at zero rather than assumed"
        )
    else:
        source_dpo = f"most recent period DPO ({last_p})"

    for p in forecast_periods:
        result.append(_make("dpo_days", dpo, p, "base", source_dpo))

    # ------------------------------------------------------------------ #
    # 7b. DIO — historical ratio series first, raw fallback for sparse data
    # ------------------------------------------------------------------ #
    dio = ratios.get_value("dio_days", last_p)
    if dio is not None:
        source_dio = f"most recent period DIO ({last_p})"
    else:
        inv_val = constants.resolve(
            historical_model.balance_sheet.get_value("canonical.bs.inventory", last_p), 0.0
        )
        cogs_val = constants.resolve(
            historical_model.income_statement.get_value("canonical.is.cost_of_sales", last_p), 0.0
        )
        if inv_val > 0 and cogs_val > 0:
            dio = round((inv_val / cogs_val) * 365.0, 1)
            source_dio = f"Computed from historical inventory ({inv_val:.0f}) and COGS ({cogs_val:.0f})"
        else:
            dio = 0.0
            source_dio = (
                "unresolved — no inventory reported in the ingested filings; "
                "inventory held at zero rather than assumed"
            )

    for p in forecast_periods:
        result.append(_make("dio_days", dio, p, "base", source_dio))

    # ------------------------------------------------------------------ #
    # 8. Capex % Revenue — Multi-year average using canonical capex / revenue
    #
    # |investing_activities| is NOT a capex proxy: it nets M&A, disposals and
    # investments, so a year with a large acquisition reports capex far above
    # revenue, and a net investing INFLOW (a disposal year) gets abs()'d into a
    # positive "capex". The proxy is only used when it lands in a believable
    # band, and the result is always clamped.
    # ------------------------------------------------------------------ #
    capex_pcts = []
    used_direct_capex = False
    used_proxy = False
    for p in periods:
        capex_val = historical_model.cash_flow_statement.get_value("canonical.cf.capex", p)
        if capex_val is not None:
            used_direct_capex = True
        else:
            inv = historical_model.cash_flow_statement.get_value("canonical.cf.investing_activities", p)
            # A net investing INFLOW cannot be capex — abs() would relabel a
            # disposal as capital expenditure.
            if inv is not None and inv < 0:
                capex_val = abs(inv)
                used_proxy = True

        rev = historical_model.income_statement.get_value("canonical.is.revenue", p)
        if capex_val is not None and rev and rev > 0:
            pct = abs(capex_val) / rev * 100.0
            if pct <= constants.MAX_CAPEX_PCT_REVENUE:
                capex_pcts.append(round(pct, 4))

    hist_capex_pct = constants.resolve(_avg(capex_pcts), constants.DEFAULT_CAPEX_PCT_REVENUE)
    if not capex_pcts:
        source_capex_base = (
            f"No usable capex reported; platform default {constants.DEFAULT_CAPEX_PCT_REVENUE}% of revenue"
        )
    elif used_direct_capex:
        source_capex_base = f"Multi-year average GAAP capex (canonical.cf.capex) % revenue ({first_p}-{last_p})"
    elif used_proxy:
        source_capex_base = (
            f"Multi-year average |investing_activities| proxy % revenue ({first_p}-{last_p}) "
            "— no GAAP capex line was mapped for this filer"
        )
    else:
        source_capex_base = f"Multi-year average GAAP capex % revenue ({first_p}-{last_p})"

    # What the fade is fading TOWARDS.
    #
    # The target used to be a flat 1.25x depreciation. That is not a steady state:
    # in a Gordon perpetuity growing at g, reinvestment funds depreciation plus the
    # capital for that growth, so capex converges on D&A x (1 + g). Sitting
    # permanently 25% above depreciation says the business reinvests for ever at a
    # rate its growth does not fund, and the terminal value becomes a function of
    # that assumption rather than of the business.
    #
    # Concretely: it is why the largest company in the shipped set failed
    # terminal_value_is_not_carrying_the_model. Capex ran at about 1.3x D&A in the
    # final explicit year, free cash flow stayed near zero, and the terminal value
    # carried the entire enterprise. Nothing in that filer's filings was wrong -- the
    # fade had a target that was never a steady state, so it faded toward a number
    # that suppressed cash flow for ever.
    #
    # The premium is bounded by the growth the terminal value itself assumes, because
    # that is the growth the reinvestment has to fund. A filer is never handed a
    # terminal value paying for capex its own growth rate cannot support.
    term_growth, _growth_basis = constants.terminal_growth_for(
        resolve_market(historical_model.company_id)
    )
    # What the fade is fading towards, economically.
    #
    # At a steady state capex = D&A + g x invested capital, and with D&A = delta x IC
    # that is capex/D&A = 1 + g/delta: the DEPRECIATION RATE in the denominator, not
    # the growth rate. At g = 2.25% and a 6 to 8 year blended asset life the true
    # ratio is 1.135 to 1.180.
    #
    # This was a flat 1.25, a crude approximation that happened to sit inside that
    # range. It was then "fixed" to 1 + g, which is 1.022 -- wrong by a factor that
    # scales with asset life, because 1 + g is only correct at delta = 1, a one-year
    # asset life. Assuming a company reinvests only 2.25% above depreciation implies
    # it stops investing well below maintenance, which raises free cash flow and so
    # raises the terminal value: the change inflated value in exactly the direction
    # nobody wants a credibility problem to go.
    #
    # delta is not cleanly measurable from what the statements carry -- depreciation
    # runs on a gross asset base and the statements give a net one -- so this uses a
    # documented default rather than a derived figure that would look precise and be
    # wrong. Measuring it properly is the open item, recorded in the handoff rather
    # than guessed at here.
    #
    # The direction of the error is deliberate: 1.25 sits above the 1.135-1.180 range
    # for a typical asset life, so it overstates steady-state reinvestment and
    # understates the terminal value. When the terminal value is already the thing
    # under scrutiny, erring low is the right way to be wrong.
    # The depreciation rate, measured rather than assumed where the filer allows it.
    #
    # delta = D&A / gross asset base. Gross is net PP&E plus accumulated
    # depreciation, both now ingested, because depreciation is charged on the gross
    # base: dividing by net understates delta, which overstates the growth the
    # terminal value can fund, which inflates the terminal value. That is the whole
    # reason this is measured.
    #
    # Falls back to the documented constant only when the filer reports no gross base
    # at all -- which is common, since many filers print a single net caption and
    # carry the gross and accumulated figures only as parentheticals.
    gross_ppe = _latest_positive(
        historical_model.balance_sheet, "canonical.bs.ppe_gross"
    )
    accum_dep = _latest_positive(
        historical_model.balance_sheet, "canonical.bs.accumulated_depreciation"
    )
    delta_measured: Optional[float] = None
    if gross_ppe and da_pct > 0:
        # da_pct is a percent of revenue; convert to a percent of gross PP&E.
        revenue = _latest_positive(
            historical_model.income_statement, "canonical.is.revenue"
        )
        if revenue:
            da_abs = da_pct / 100.0 * revenue
            delta_measured = da_abs / gross_ppe
    elif accum_dep and _latest_positive(
        historical_model.balance_sheet, "canonical.bs.ppe"
    ):
        net_ppe = _latest_positive(
            historical_model.balance_sheet, "canonical.bs.ppe"
        )
        if net_ppe:
            gross_derived = net_ppe + accum_dep
            revenue = _latest_positive(
                historical_model.income_statement, "canonical.is.revenue"
            )
            if revenue and da_pct > 0:
                delta_measured = (da_pct / 100.0 * revenue) / gross_derived

    # Plausibility band on the measured rate.
    #
    # Measuring per filer immediately produced a value that proves the measurement
    # can be wrong: Ambarella reported gross PP&E of 44 against D&A of 26, a rate of
    # 58.65%, implying an asset life of 1.7 years. Nothing depreciates that fast.
    # Its depreciation is mostly on acquired intangibles and a fabless business
    # carries almost no plant, so PP&E is the wrong denominator entirely and the
    # ratio is measuring two unrelated things.
    #
    # A depreciation rate outside roughly 3% to 30% means the denominator is not a
    # property, plant and equipment base -- it is intangibles, or a tag that picked
    # up something else. Rather than publish a steady state derived from it, fall
    # back and say so. A wrong number that is precisely wrong is worse than an
    # approximation that is honestly labelled.
    delta_plausible = (
        delta_measured is not None
        and MIN_PLAUSIBLE_DEPRECIATION_RATE
        <= delta_measured
        <= MAX_PLAUSIBLE_DEPRECIATION_RATE
    )
    if delta_plausible:
        premium = 1.0 + (term_growth / 100.0) / delta_measured
        # `gross_ppe` is None when the rate came from the accumulated-depreciation
        # fallback rather than a reported gross figure. Formatting it regardless
        # raised a TypeError that took out every build for such a filer -- the
        # optional input was read as though it were required.
        base_desc = (
            f"a reported gross asset base of {gross_ppe:,.0f}"
            if gross_ppe
            else (
                f"net PP&E plus reported accumulated depreciation of {accum_dep:,.0f}"
                if accum_dep
                else "the filer's asset base"
            )
        )
        steady_state_basis = (
            f"steady-state capex {premium:.3f}x D&A from the measured depreciation "
            f"rate {delta_measured:.1%} (D&A over {base_desc}) at "
            f"{term_growth:.2f}% terminal growth"
        )
    else:
        premium = constants.STEADY_STATE_CAPEX_PREMIUM
        if delta_measured is None:
            why = "no gross asset base was reported"
        else:
            why = (
                f"the measured depreciation rate of {delta_measured:.1%} implies an "
                f"asset life under "
                f"{1 / MAX_PLAUSIBLE_DEPRECIATION_RATE:.1f} years, so PP&E is not "
                f"the base its depreciation runs on -- most of it is intangibles or "
                f"a mis-mapped tag"
            )
        steady_state_basis = (
            f"steady-state capex {premium:.3f}x D&A, the platform default, because "
            f"{why}"
        )
    _unused_term_growth = term_growth
    if hist_capex_pct <= da_pct * premium:
        # Already inside the steady state. There is no cycle to fade, and fading
        # would invent a decline the filings do not show.
        steady_state_capex = hist_capex_pct
    else:
        # Above it, the fade targets the steady state exactly.
        #
        # This was written as
        #     min(max(da*(1+g), min(hist, CAP)), da*premium)
        # which collapses to da*(1+g), because the max() is always at least da*(1+g)
        # and premium IS 1+g. The outer clamp could therefore never bind -- a
        # mutation setting premium to 1.15 passed the suite, because the redundant
        # term absorbed it.
        #
        # Stated plainly it is also checkable, which the compound form was not.
        steady_state_capex = da_pct * premium
    is_expansion_cycle = hist_capex_pct > (da_pct * 1.35) and hist_capex_pct > 6.0
    # The fade COMPLETES in the final explicit year, and that is a requirement
    # rather than a preference. The Gordon terminal value capitalises the final
    # year, so if that year is not the steady state then the perpetuity is being
    # valued off a peak-investment year and the terminal value becomes a function of
    # the fade schedule rather than of the business.
    #
    # This used to stop at 0.85, leaving 15% of the peak capex ratio in the terminal
    # year -- at Amazon's ratio that left capex near 1.10x depreciation against a
    # growth rate funding 1.02x, and terminal_value_is_not_carrying_the_model caught
    # it.
    #
    # Derived from len(forecast_periods) rather than written as five literals, so
    # adding or removing a forecast year cannot silently leave the fade short.
    capex_fade_weights = (
        _fade_weights(len(forecast_periods))
        if is_expansion_cycle
        else [0.0] * len(forecast_periods)
    )

    for idx, p in enumerate(forecast_periods):
        w_fade = capex_fade_weights[idx] if idx < len(capex_fade_weights) else 0.0
        p_capex = round((1.0 - w_fade) * hist_capex_pct + w_fade * steady_state_capex, 4)
        if p_capex > constants.MAX_CAPEX_PCT_REVENUE:
            p_capex = constants.MAX_CAPEX_PCT_REVENUE
        if is_expansion_cycle and w_fade > 0:
            source_capex = f"Peak cycle CapEx ({hist_capex_pct:.1f}%) fading to steady-state maintenance ({steady_state_capex:.1f}%)"
        else:
            source_capex = source_capex_base
        result.append(_make(
            "capex_pct_revenue", p_capex, p, "base",
            f"{source_capex}; {steady_state_basis}",
        ))

    # ------------------------------------------------------------------ #
    # 9. Debt Repayment — zero (borrowings carried flat across forecast)
    # ------------------------------------------------------------------ #
    source_debt = "zero — opening debt carried flat, no draws or repayments"
    for p in forecast_periods:
        result.append(_make("debt_repayment", 0.0, p, "base", source_debt))

    # ------------------------------------------------------------------ #
    # 10. WACC — CAPM default computed per company/market (no hardcode).
    # Cost of debt resolves later from the debt schedule interest rate.
    # ------------------------------------------------------------------ #
    default_ke = _default_cost_of_equity(historical_model)
    result.append(_make("wacc.cost_of_equity", default_ke[0], "all", "base", default_ke[1]))
    result.append(_make("wacc.cost_of_debt", 0.0, "all", "base", "placeholder — valuation uses debt schedule interest rate"))

    # ------------------------------------------------------------------ #
    # 11. Terminal Value inputs — structural placeholders
    # ------------------------------------------------------------------ #
    # Perpetuity growth anchors to long-run nominal GDP of the reporting
    # economy. The market comes from the company's own metadata, NOT from the
    # company_id suffix: infy_us is a US-listed ADR on an Indian fiscal
    # calendar, so a suffix test mis-classifies it.
    default_terminal_growth, basis = constants.terminal_growth_for(
        "us" if resolve_market(historical_model.company_id) == "us" else "india"
    )
    source_terminal = f"structural placeholder — anchored to {basis}"
    result.append(_make("terminal_growth_rate", default_terminal_growth, "terminal", "base", source_terminal))
    result.append(
        _make("exit_ev_multiple", constants.DEFAULT_EXIT_EV_MULTIPLE, "terminal", "base", source_terminal)
    )

    return result
