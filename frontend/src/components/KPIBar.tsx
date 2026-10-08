'use client'

import React, { useSyncExternalStore } from 'react'
import { ModelSpecification, ScenarioLabel } from '@/lib/types'
import { fmtMoney, fmtPct, fmtPrice } from '@/lib/formatters'
import { NO_VALUE } from '@/lib/noValue'
import { mayPublishPrice, withheldReason } from '@/lib/publication'
import {
  baseQuoteSource,
  classifyQuote,
  quoteCaption,
  quoteIsFlagged,
  quoteTitle,
} from '@/lib/quoteLabel'
import { provenanceLabel, provenanceTitleText, provenanceTone } from '@/lib/provenance'

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

  // The server decides what may be called a valuation and returns that verdict.
  // This used to keep its own list of the defect-check names, five of them, and
  // had already fallen behind the server's eight, so a model failing only a newer
  // check would have shown its price in a headline while the API called it
  // opinion_only. One list, on the server.
  const publishable = mayPublishPrice(spec)
  const publicationTitle =
    withheldReason(spec) || 'The engine could not verify the inputs to this model.'

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
  // The share of enterprise value the terminal value accounts for, read off the
  // same bridge the DCF schedule prints it from. Shown even when the price is
  // withheld: the gate nulls only the implied share price, so EV and PV TV
  // survive and this ratio stays evidence rather than conclusion.
  const tvPv = bridge?.pv_terminal_value ?? null
  const tvPct =
    ev != null && ev !== 0 && tvPv != null ? (tvPv / ev) * 100 : null
  const waccVal = waccObj?.wacc ?? null
  const terminalGrowthVal = tvObj?.terminal_growth_rate ?? null

  const priceSource = reverseDcf?.market_price_source ?? null
  // One definition of what the quote is, in lib/quoteLabel, because this logic
  // was duplicated here and in QuickDCFView and had drifted. A daily close is a
  // dated figure, not a live print, and the two sources that can only return a
  // close were being captioned "Live".
  const quoteKind = classifyQuote(priceSource, reverseDcf?.market_price_date)
  const isSuccessorQuote = quoteKind === 'successor'
  const priceSublabel = quoteCaption(quoteKind, reverseDcf?.market_price_date)
  const priceSublabelClass = quoteIsFlagged(quoteKind) ? 'text-warning' : 'text-text-dim'
  const priceTitle = quoteTitle(quoteKind, reverseDcf?.market_price_date, baseQuoteSource(priceSource))

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

  // Where the numbers came from, and whether that is the filer's own accounts.
  //
  // The product's claim is that every published figure matches an official filing.
  // That is true for nine of the twenty-three shipped companies and false for
  // thirteen, and a reader cannot weigh a claim they are not shown the terms of. The
  // tie-out has measured the cost of the other thirteen: the Infosys ADR publishes
  // 1,043 of current investments where its own 20-F says 1,365, and no non-current
  // investments where the filing says 942.
  //
  // So the source is stated, and it is stated from the ingestion's own record rather
  // than asserted. A company built from a market feed says so, because that is the
  // difference between "read out of the accounts" and "reported by a provider", and
  // only the reader can decide which one they need.
  const meta = spec?.metadata
  const provenance = provenanceLabel(meta?.filing_derived, meta?.filing_source, meta?.data_sources)
  const provenanceTitle = provenanceTitleText(meta)
  // Amber, not the muted default. A reader scanning the bar should notice that this
  // page's figures came from a provider rather than the accounts, without opening
  // anything.
  const provenanceClass =
    provenanceTone(meta?.filing_derived, meta?.filing_source) === 'filing'
      ? 'text-text-dim'
      : 'text-warning'

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
            {impliedPrice != null && publishable ? fmtPrice(impliedPrice, currency, 2) : NO_VALUE}
          </div>
          <div className="text-[10px] font-semibold mt-0.5 whitespace-nowrap">
            {!publishable ? (
              <>
                <span className="text-warning" title={publicationTitle}>
                  Inputs not verified
                </span>
                <div className="text-[10px] font-normal text-text-dim mt-0.5 whitespace-normal">
                  Models publish once a filing is in the store; where both exist the filing wins.
                </div>
              </>
            ) : isSuccessorQuote ? (
              <span className="text-warning" title={priceTitle}>
                Not comparable
              </span>
            ) : upsidePct != null ? (
              <span
                className={upsidePct >= 0 ? 'text-positive' : 'text-negative'}
                title={deviationFlagged ? deviationTitle : undefined}
              >
                {upsidePct >= 0 ? '+' : ''}
                {fmtPct(upsidePct, 1)} vs mkt
                {deviationFlagged && (
                  <span className="text-warning"> · check inputs</span>
                )}
              </span>
            ) : (
              <span className="text-text-dim">Intrinsic Value</span>
            )}
            {/* The source of the figures, always shown. The headline claim is that
                every number here matches an official filing, and for a company
                built from a market feed that is not true, so it says so rather than
                letting the claim stand unqualified. */}
            <div className={`text-[10px] mt-0.5 ${provenanceClass} whitespace-nowrap`} title={provenanceTitle}>
              {provenance}
            </div>
          </div>
        </div>

        {/* KPI 2: Market Price */}
        <div className="bg-[#111622] border border-[#1e283d] rounded-[4px] px-3 py-2 flex flex-col justify-between">
          <span className="font-semibold text-[10.5px] uppercase tracking-[0.04em] text-[#94a3b8] whitespace-nowrap">
            Market Price
          </span>
          <div className="font-mono font-bold text-[16px] text-[#f8fafc] mt-0.5 whitespace-nowrap">
            {marketPrice != null ? fmtPrice(marketPrice, currency, 2) : NO_VALUE}
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
            {statements.label ?? NO_VALUE}
          </div>
          <div
            className={`text-[10px] font-semibold mt-0.5 whitespace-nowrap ${
              statementsStale ? 'text-warning' : 'text-text-dim'
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
            {ev != null ? fmtMoney(ev, currency) : NO_VALUE}
          </div>
          <div className="text-[10px] font-semibold text-text-dim mt-0.5 whitespace-nowrap">
            PV FCFF + PV TV
          </div>
          {tvPct != null && (
            <div className="text-[10px] font-mono text-text-dim mt-0.5 whitespace-nowrap">
              Terminal value {fmtPct(tvPct, 1)} of EV
            </div>
          )}
        </div>

        {/* KPI 5: Equity Value */}
        <div className="bg-[#111622] border border-[#1e283d] rounded-[4px] px-3 py-2 flex flex-col justify-between">
          <span className="font-semibold text-[10.5px] uppercase tracking-[0.04em] text-[#94a3b8] whitespace-nowrap">
            Equity Value
          </span>
          <div className="font-mono font-bold text-[16px] text-[#f8fafc] mt-0.5 whitespace-nowrap">
            {equityVal != null ? fmtMoney(equityVal, currency) : NO_VALUE}
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
            {waccVal != null ? fmtPct(waccVal, 2) : NO_VALUE}
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
            {terminalGrowthVal != null ? fmtPct(terminalGrowthVal, 2) : NO_VALUE}
          </div>
          <div className="text-[10px] font-semibold text-text-dim mt-0.5 whitespace-nowrap">
            Gordon Growth
          </div>
        </div>
      </div>
    </div>
  )
}
