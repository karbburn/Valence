'use client'

import React, { useSyncExternalStore } from 'react'
import { ModelSpecification, ScenarioLabel } from '@/lib/types'
import { fmtMoney, fmtPct, fmtPrice } from '@/lib/formatters'

export interface KPIBarProps {
  spec: ModelSpecification | null
  scenario: ScenarioLabel
}

/**
 * Newest reported period the model was built from.
 *
 * Pure and clock-free, so it renders identically on the server and the client.
 * The age is deliberately not computed here: Date.now() during SSR bakes a value
 * into ISR-cached HTML that can be an hour old, which both mismatches on
 * hydration and can flip the "Behind" marker against the live clock. The age is
 * measured after mount instead.
 *
 * The statements are ANNUAL by construction, not by neglect. SEC ingestion
 * accepts only facts with fp == "FY" from annual forms and keeps only spans of
 * 330 to 400 days, so 10-Q quarters are never read. A fiscal year ends and the
 * next is not due for up to another twelve months, which means this date is
 * normally six to twelve months old and that is correct rather than stale.
 */
function statementsPeriod(spec: ModelSpecification | null): {
  label: string | null
  endDate: string | null
} {
  const items = spec?.historicals?.line_items ?? []
  let newest: { label: string; end: string; t: number } | null = null
  for (const li of items) {
    if (!li.period_end_date || !li.period_label) continue
    const parsed = Date.parse(li.period_end_date)
    if (Number.isNaN(parsed)) continue
    if (!newest || parsed > newest.t) {
      newest = { label: li.period_label, end: li.period_end_date, t: parsed }
    }
  }
  if (!newest) return { label: null, endDate: null }
  return { label: newest.label, endDate: newest.end }
}

/** Whole days between a period end and now. Floored at zero. */
function daysSince(endDate: string): number {
  const parsed = Date.parse(endDate)
  if (Number.isNaN(parsed)) return 0
  return Math.max(0, Math.floor((Date.now() - parsed) / 86_400_000))
}

// One annual cycle plus filing lag. Past this, the next annual report should
// already have landed and the snapshot has not been rebuilt.
const STATEMENTS_STALE_DAYS = 400

/** Nothing external changes here, so the subscription is a no-op by design. */
const noSubscription = () => () => {}

export function KPIBar({ spec, scenario }: KPIBarProps) {
  const statements = statementsPeriod(spec)

  // How old a period end is depends on the client clock, so it cannot be read
  // during SSR: the value would be baked into the ISR-cached HTML, could be an
  // hour stale by the time it is served, and would mismatch on hydration. The
  // server snapshot is null and the client snapshot is the real age, which
  // React resolves on commit without an effect or a second render pass.
  const statementAge = useSyncExternalStore(
    noSubscription,
    () => (statements.endDate ? daysSince(statements.endDate) : null),
    () => null,
  )

  if (!spec) return null

  const currency = spec.metadata?.currency || 'INR'

  // Find valuation output for active scenario
  const valuation =
    spec.valuation?.find((v) => v.scenario === scenario) || spec.valuation?.[0]

  const bridge = valuation?.dcf_bridge
  const waccObj = valuation?.wacc
  const tvObj = valuation?.terminal_value
  const reverseDcf = valuation?.reverse_dcf

  const impliedPrice = bridge?.implied_share_price ?? null

  // The same rule the API applies in its publication verdict, derived from the
  // checks this component is already given. Kept in step deliberately: the
  // server decides what may be called a valuation, and the client is only
  // choosing not to put a number in a headline.
  const INPUT_DEFECT_CHECKS = [
    'bridge_inputs_plausible',
    'income_statement_is_coherent',
    'year_one_growth_is_plausible',
    'terminal_value_is_not_carrying_the_model',
    'equity_value_positive',
  ]
  const publishable = !(spec.qa?.checks ?? []).some(
    (c) => INPUT_DEFECT_CHECKS.includes(c.check_name) && !c.passed,
  )
  const publicationTitle = (spec.qa?.checks ?? [])
    .filter((c) => INPUT_DEFECT_CHECKS.includes(c.check_name) && !c.passed)
    .map((c) => `${c.check_name}: ${c.detail}`)
    .join('\n\n') || 'The engine could not verify the inputs to this model.'

  // A valuation this far from the traded price is still an opinion and is still
  // shown, because disagreeing with the market is what the product is for. What
  // was missing is any signal that the engine itself wants a second look at where
  // the number came from, so a reader saw "+180.2% vs mkt" in green and took it
  // as a recommendation.
  //
  // The colour follows the sign, as it always has. This adds the caveat beside
  // it rather than changing what the number means, which is the line between
  // saying less about a valuation and saying something untrue about it.
  const deviationCheck = (spec.qa?.checks ?? []).find(
    (c) => c.check_name === 'implied_price_deviation_is_explainable',
  )
  const deviationFlagged = deviationCheck != null && !deviationCheck.passed
  const deviationTitle = deviationCheck?.detail || undefined
  const marketPrice = reverseDcf?.market_price ?? null

  let upsidePct: number | null = null
  if (impliedPrice != null && marketPrice != null && marketPrice > 0) {
    upsidePct = ((impliedPrice - marketPrice) / marketPrice) * 100
  }

  const ev = bridge?.enterprise_value ?? null
  const equityVal = bridge?.equity_value ?? null
  const waccVal = waccObj?.wacc ?? null
  const terminalGrowthVal = tvObj?.terminal_growth_rate ?? null

  const priceSource = reverseDcf?.market_price_source ?? null
  // Successor ticker: the quote belongs to a different listed entity than the
  // model's historical financials (demerger/restructuring). The price is real
  // but the vs-market % is not meaningful, so say so instead of printing it.
  const isSuccessorQuote = !!priceSource && priceSource.endsWith(':successor_ticker')
  const baseSource = isSuccessorQuote ? priceSource.slice(0, -':successor_ticker'.length) : priceSource
  const isLiveQuote =
    baseSource === 'yfinance' ||
    baseSource === 'yfinance_history' ||
    baseSource === 'yahoo_chart' ||
    baseSource === 'twelvedata'
  const isStaleQuote = !!baseSource && baseSource.startsWith('stale_cache')
  const isFallbackQuote =
    !!baseSource &&
    (baseSource === 'registry' ||
      baseSource === 'market_default' ||
      baseSource.startsWith('market_default'))
  const priceSublabel = isSuccessorQuote
    ? `As of ${reverseDcf?.market_price_date} · Successor ticker`
    : !reverseDcf?.market_price_date
      ? 'Live / Benchmark'
      : isLiveQuote
        ? `As of ${reverseDcf.market_price_date} · Live`
        : isStaleQuote
          ? `As of ${reverseDcf.market_price_date} · Stale`
          : isFallbackQuote
            ? `As of ${reverseDcf.market_price_date} · Benchmark`
            : `As of ${reverseDcf.market_price_date}`
  const priceSublabelClass =
    isStaleQuote || isFallbackQuote || isSuccessorQuote ? 'text-[#f59e0b]' : 'text-text-dim'
  const priceTitle = isSuccessorQuote
    ? 'The listed ticker was retired by a corporate action and this quote is the successor entity. It is not comparable with this model\'s historical financials, so the vs-market % is suppressed.'
    : isLiveQuote
      ? `Live quote from ${baseSource} on ${reverseDcf?.market_price_date}`
      : isStaleQuote
        ? 'Live quote failed: showing last cached close. Check connection, then reload.'
        : isFallbackQuote
          ? 'Live quote unavailable: showing benchmark fallback. Treat vs-mkt % with caution.'
          : undefined

  const statementsStale =
    statementAge != null && statementAge > STATEMENTS_STALE_DAYS
  const statementsTitle = !statements.endDate
    ? 'This model carries no historical statements.'
    : `Built on the ${statements.label} annual report, period ending ${statements.endDate}.` +
      (statementAge == null
        ? ''
        : ` That is ${statementAge} days old.` +
          (statementsStale
            ? ' The next annual report should have landed by now, so this snapshot is behind and wants a rebuild.'
            : ' The model reads annual filings only, so this is the most recent one on record and the age is expected.'))

  return (
    <div className="w-full bg-[#111622]/40 border-b border-[#1e283d] px-[14px] py-[8px]">
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-2.5">
        {/* KPI 1: DCF Implied Price (Primary KPI) */}
        <div className="bg-[#111622] border border-[#0ea5e9]/40 rounded-[4px] px-3 py-2 flex flex-col justify-between shadow-sm">
          <span className="font-semibold text-[10.5px] uppercase tracking-[0.04em] text-[#94a3b8] whitespace-nowrap">
            DCF Implied Price
          </span>
          <div className="font-mono font-bold text-[16px] text-[#7dd3fc] mt-0.5 whitespace-nowrap">
            {/* A model the engine will not stand behind does not get a headline
                price. The number is still in the workbench below, where the
                audit explains it, but presenting it here without qualification
                is the thing that puts a wrong figure in front of a reader. */}
            {impliedPrice != null && publishable ? fmtPrice(impliedPrice, currency, 2) : '—'}
          </div>
          <div className="text-[10px] font-semibold mt-0.5 whitespace-nowrap">
            {!publishable ? (
              <span className="text-[#f59e0b]" title={publicationTitle}>
                Inputs not verified
              </span>
            ) : isSuccessorQuote ? (
              <span className="text-[#f59e0b]" title={priceTitle}>
                Not comparable
              </span>
            ) : upsidePct != null ? (
              <span
                className={upsidePct >= 0 ? 'text-[#10b981]' : 'text-[#ef4444]'}
                title={deviationFlagged ? deviationTitle : undefined}
              >
                {upsidePct >= 0 ? '+' : ''}
                {fmtPct(upsidePct, 1)} vs mkt
                {deviationFlagged && (
                  <span className="text-[#f59e0b]"> · check inputs</span>
                )}
              </span>
            ) : (
              <span className="text-text-dim">Intrinsic Value</span>
            )}
          </div>
        </div>

        {/* KPI 2: Market Price */}
        <div className="bg-[#111622] border border-[#1e283d] rounded-[4px] px-3 py-2 flex flex-col justify-between">
          <span className="font-semibold text-[10.5px] uppercase tracking-[0.04em] text-[#94a3b8] whitespace-nowrap">
            Market Price
          </span>
          <div className="font-mono font-bold text-[16px] text-[#f8fafc] mt-0.5 whitespace-nowrap">
            {marketPrice != null ? fmtPrice(marketPrice, currency, 2) : '—'}
          </div>
          <div className={`text-[10px] font-semibold mt-0.5 whitespace-nowrap ${priceSublabelClass}`} title={priceTitle}>
            {priceSublabel}
          </div>
        </div>

        {/* KPI 3: Reporting period the statements come from */}
        <div className="bg-[#111622] border border-[#1e283d] rounded-[4px] px-3 py-2 flex flex-col justify-between">
          <span className="font-semibold text-[10.5px] uppercase tracking-[0.04em] text-[#94a3b8] whitespace-nowrap">
            Statements
          </span>
          <div className="font-mono font-bold text-[16px] text-[#f8fafc] mt-0.5 whitespace-nowrap">
            {statements.label ?? '—'}
          </div>
          <div
            className={`text-[10px] font-semibold mt-0.5 whitespace-nowrap ${
              statementsStale ? 'text-[#f59e0b]' : 'text-text-dim'
            }`}
            title={statementsTitle}
          >
            {!statements.endDate
              ? 'No statements'
              : statementAge == null
                ? `Ended ${statements.endDate}`
                : statementsStale
                  ? `Ended ${statements.endDate} · ${statementAge}d · Behind`
                  : `Ended ${statements.endDate} · ${statementAge}d`}
          </div>
        </div>

        {/* KPI 4: Enterprise Value */}
        <div className="bg-[#111622] border border-[#1e283d] rounded-[4px] px-3 py-2 flex flex-col justify-between">
          <span className="font-semibold text-[10.5px] uppercase tracking-[0.04em] text-[#94a3b8] whitespace-nowrap">
            Enterprise Value
          </span>
          <div className="font-mono font-bold text-[16px] text-[#f8fafc] mt-0.5 whitespace-nowrap">
            {ev != null ? fmtMoney(ev, currency) : '—'}
          </div>
          <div className="text-[10px] font-semibold text-text-dim mt-0.5 whitespace-nowrap">
            PV FCFF + PV TV
          </div>
        </div>

        {/* KPI 5: Equity Value */}
        <div className="bg-[#111622] border border-[#1e283d] rounded-[4px] px-3 py-2 flex flex-col justify-between">
          <span className="font-semibold text-[10.5px] uppercase tracking-[0.04em] text-[#94a3b8] whitespace-nowrap">
            Equity Value
          </span>
          <div className="font-mono font-bold text-[16px] text-[#f8fafc] mt-0.5 whitespace-nowrap">
            {equityVal != null ? fmtMoney(equityVal, currency) : '—'}
          </div>
          <div className="text-[10px] font-semibold text-text-dim mt-0.5 whitespace-nowrap">
            Net Debt Adjusted
          </div>
        </div>

        {/* KPI 6: WACC */}
        <div className="bg-[#111622] border border-[#1e283d] rounded-[4px] px-3 py-2 flex flex-col justify-between">
          <span className="font-semibold text-[10.5px] uppercase tracking-[0.04em] text-[#94a3b8] whitespace-nowrap">
            WACC
          </span>
          <div className="font-mono font-bold text-[16px] text-[#f8fafc] mt-0.5 whitespace-nowrap">
            {waccVal != null ? fmtPct(waccVal, 2) : '—'}
          </div>
          <div className="text-[10px] font-semibold text-text-dim mt-0.5 whitespace-nowrap">
            CAPM / Capital Cost
          </div>
        </div>

        {/* KPI 7: Terminal Growth (g) */}
        <div className="bg-[#111622] border border-[#1e283d] rounded-[4px] px-3 py-2 flex flex-col justify-between">
          <span className="font-semibold text-[10.5px] uppercase tracking-[0.04em] text-[#94a3b8] whitespace-nowrap">
            Terminal Growth (g)
          </span>
          <div className="font-mono font-bold text-[16px] text-[#f8fafc] mt-0.5 whitespace-nowrap">
            {terminalGrowthVal != null ? fmtPct(terminalGrowthVal, 2) : '—'}
          </div>
          <div className="text-[10px] font-semibold text-text-dim mt-0.5 whitespace-nowrap">
            Gordon Growth
          </div>
        </div>
      </div>
    </div>
  )
}
