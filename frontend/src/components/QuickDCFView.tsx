'use client'

import React from 'react'
import { ArrowUpRight, ArrowDownRight, Layers, Info, GitCompare } from 'lucide-react'
import { ModelSpecification, ScenarioLabel } from '@/lib/types'
import { fmtNum, fmtPct, fmtPrice, getCurrencySymbol, fmtMoney } from '@/lib/formatters'

export interface QuickDCFViewProps {
  spec: ModelSpecification | null
  scenario: ScenarioLabel
  onOpenMethodology?: () => void
}

export function QuickDCFView({ spec, scenario, onOpenMethodology }: QuickDCFViewProps) {
  const valuation =
    spec?.valuation?.find((v) => v.scenario === scenario) || spec?.valuation?.[0]

  if (!valuation) {
    return (
      <div className="bg-surface border border-border rounded-sm p-6 text-center text-text-dim text-[12px]">
        No valuation summary available for this scenario.
      </div>
    )
  }

  const currency = spec?.metadata?.currency || 'INR'
  const currencySym = getCurrencySymbol(currency)
  const bridge = valuation.dcf_bridge || {}
  const reverseDcf = valuation.reverse_dcf || {}
  const wacc = valuation.wacc || {}
  const tv = valuation.terminal_value || {}
  const sensTable = valuation.sensitivity_tables?.[0]

  const impliedPrice = bridge.implied_share_price ?? null
  const marketPrice = reverseDcf.market_price ?? null
  const priceSource = (reverseDcf as { market_price_source?: string | null }).market_price_source ?? null
  const priceDate = (reverseDcf as { market_price_date?: string | null }).market_price_date ?? null
  // Successor ticker (demerger/restructuring): the quote is a real price but for
  // a different listed entity than this model's financials, so the upside is
  // not meaningful and must not be presented as if it were.
  const isSuccessorQuote = !!priceSource && priceSource.endsWith(':successor_ticker')
  const baseSource = isSuccessorQuote ? priceSource.slice(0, -':successor_ticker'.length) : priceSource
  const isLiveQuote =
    baseSource === 'yfinance' ||
    baseSource === 'yfinance_history' ||
    baseSource === 'yahoo_chart' ||
    baseSource === 'twelvedata'
  const isStaleQuote = !!baseSource && baseSource.startsWith('stale_cache')
  const isFallbackQuote =
    !!baseSource && (baseSource === 'registry' || baseSource === 'market_default')
  const quoteLabel = isSuccessorQuote
    ? `Successor ticker · As of ${priceDate}`
    : !priceDate
      ? 'Benchmark quote'
      : isLiveQuote
        ? `Live quote · As of ${priceDate}`
        : isStaleQuote
          ? `Stale close · As of ${priceDate}`
          : isFallbackQuote
            ? `Benchmark · As of ${priceDate}`
            : `As of ${priceDate}`

  let upsidePct: number | null = null
  if (!isSuccessorQuote && impliedPrice != null && marketPrice != null && marketPrice > 0) {
    upsidePct = ((impliedPrice - marketPrice) / marketPrice) * 100
  }

  const grid = sensTable?.results_grid || []

  // All 3 Scenarios for comparison matrix
  const baseVal = spec?.valuation?.find((v) => v.scenario === 'base')
  const bullVal = spec?.valuation?.find((v) => v.scenario === 'bull')
  const bearVal = spec?.valuation?.find((v) => v.scenario === 'bear')

  const getUpside = (v?: typeof baseVal) => {
    if (isSuccessorQuote) return null
    const p = v?.dcf_bridge?.implied_share_price
    if (p != null && marketPrice != null && marketPrice > 0) {
      return ((p - marketPrice) / marketPrice) * 100
    }
    return null
  }

  const bullUpside = getUpside(bullVal)
  const bearDownside = getUpside(bearVal)
  const asymmetryRatio =
    bullUpside != null && bearDownside != null && bearDownside !== 0
      ? Math.abs(bullUpside / bearDownside)
      : null

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Hero 3-Column Valuation Strip */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Intrinsic Value Hero */}
        <div className="bg-surface border border-accent-border rounded-sm p-5 text-center flex flex-col justify-center items-center shadow-pop relative">
          <div className="flex items-center space-x-1.5 text-[11px] font-semibold uppercase tracking-[0.04em] text-text-muted mb-1">
            <span>DCF Intrinsic Value</span>
            {onOpenMethodology && (
              <button
                type="button"
                onClick={onOpenMethodology}
                aria-label="Open methodology breakdown"
                className="text-accent hover:text-accent-hover transition-colors p-0.5 ml-1 cursor-pointer"
                title="Methodology breakdown: FCFF at WACC"
              >
                <Info className="w-3.5 h-3.5" aria-hidden />
              </button>
            )}
          </div>
          <div className="font-mono font-bold text-[30px] text-accent-hover">
            {impliedPrice != null ? fmtPrice(impliedPrice, currency, 2) : '—'}
          </div>
          <div className="text-[11px] text-text-dim mt-1 font-mono">
            Per Share ({currency}) · FCFF @ WACC
          </div>
        </div>

        {/* Current Market Price */}
        <div className="bg-surface border border-border rounded-sm p-5 text-center flex flex-col justify-center items-center">
          <div className="text-[11px] font-semibold uppercase tracking-[0.04em] text-text-muted mb-1">
            Current Market Price
          </div>
          <div className="font-mono font-bold text-[26px] text-text-main">
            {marketPrice != null ? fmtPrice(marketPrice, currency, 2) : '—'}
          </div>
          <div
            className={`text-[11px] mt-1 ${isStaleQuote || isFallbackQuote || isSuccessorQuote ? 'text-[#f59e0b] font-semibold' : 'text-text-dim'}`}
            title={
              isSuccessorQuote
                ? 'The listed ticker was retired by a corporate action. This quote is the successor entity and is not comparable with this model’s financials.'
                : isStaleQuote
                  ? 'Live quote failed. Showing last cached close.'
                  : isFallbackQuote
                    ? 'Live quote unavailable. Showing benchmark fallback.'
                    : isLiveQuote
                      ? `Live quote from ${baseSource}.`
                      : undefined
            }
          >
            {quoteLabel}
          </div>
        </div>

        {/* Implied Upside / Downside */}
        <div className="bg-surface border border-border rounded-sm p-5 text-center flex flex-col justify-center items-center">
          <div className="text-[11px] font-semibold uppercase tracking-[0.04em] text-text-muted mb-1">
            Implied Upside / Downside
          </div>
          <div
            className={`font-mono font-bold text-[30px] flex items-center space-x-1 ${
              upsidePct != null && upsidePct >= 0
                ? 'text-positive'
                : 'text-negative'
            }`}
          >
            {upsidePct != null ? (
              <>
                {upsidePct >= 0 ? (
                  <ArrowUpRight className="w-6 h-6" aria-hidden />
                ) : (
                  <ArrowDownRight className="w-6 h-6" aria-hidden />
                )}
                <span aria-hidden>
                  {upsidePct >= 0 ? '+' : ''}
                  {fmtPct(upsidePct, 1)}
                </span>
                <span className="sr-only">
                  {upsidePct >= 0 ? 'upside' : 'downside'} of {fmtPct(Math.abs(upsidePct), 1)}
                </span>
              </>
            ) : (
              '—'
            )}
          </div>
          <div className="text-[11px] text-text-dim mt-1">vs current market quote</div>
        </div>
      </div>

      {/* Side-by-Side Scenario Comparison Matrix */}
      <div className="bg-surface border border-border rounded-sm p-4 space-y-3">
        <div className="flex items-center justify-between border-b border-border pb-2">
          <div className="font-semibold text-[13px] text-text-main flex items-center space-x-2">
            <GitCompare className="w-4 h-4 text-accent" aria-hidden />
            <span>Scenario matrix</span>
          </div>
          {asymmetryRatio != null && (
            <div
              className="font-mono text-[10px] text-accent-hover bg-accent-subtle border border-accent-border px-2 py-0.5 rounded-sm"
              title="Ratio of bull-case upside to bear-case downside"
            >
              Risk/reward asymmetry: {asymmetryRatio.toFixed(1)}x
            </div>
          )}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-[11px] font-mono border-collapse">
            <caption className="sr-only">Valuation outputs across base, bull and bear scenarios</caption>
            <thead>
              <tr className="bg-surface-3 border-b border-border text-text-muted">
                <th scope="col" className="p-2.5 font-semibold text-left">Metric</th>
                <th scope="col" className="p-2.5 font-bold text-text-main w-1/4 text-right">Base</th>
                <th scope="col" className="p-2.5 font-bold w-1/4 text-right">
                  <span className="inline-flex items-center gap-1.5 justify-end">
                    <span className="w-1.5 h-1.5 rounded-full bg-positive" aria-hidden />
                    Bull
                  </span>
                </th>
                <th scope="col" className="p-2.5 font-bold w-1/4 text-right">
                  <span className="inline-flex items-center gap-1.5 justify-end">
                    <span className="w-1.5 h-1.5 rounded-full bg-negative" aria-hidden />
                    Bear
                  </span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1e283d]/60">
              <tr>
                <td className="p-2.5 font-semibold text-[#cbd5e1]">DCF Share Price</td>
                <td className="p-2.5 font-bold text-text-main text-right">
                  {fmtPrice(baseVal?.dcf_bridge?.implied_share_price, currency, 2)}
                </td>
                <td className="p-2.5 font-bold text-positive text-right">
                  {fmtPrice(bullVal?.dcf_bridge?.implied_share_price, currency, 2)}
                </td>
                <td className="p-2.5 font-bold text-[#ef4444]">
                  {fmtPrice(bearVal?.dcf_bridge?.implied_share_price, currency, 2)}
                </td>
              </tr>
              <tr>
                <td className="p-2.5 font-semibold text-[#cbd5e1]">Implied Upside / Downside</td>
                <td className="p-2.5 font-semibold text-text-muted text-right">
                  {getUpside(baseVal) != null ? `${getUpside(baseVal)! >= 0 ? '+' : ''}${fmtPct(getUpside(baseVal), 1)}` : '—'}
                </td>
                <td className="p-2.5 font-semibold text-positive text-right">
                  {getUpside(bullVal) != null ? `${getUpside(bullVal)! >= 0 ? '+' : ''}${fmtPct(getUpside(bullVal), 1)}` : '—'}
                </td>
                <td className="p-2.5 font-semibold text-negative text-right">
                  {getUpside(bearVal) != null ? `${fmtPct(getUpside(bearVal), 1)}` : '—'}
                </td>
              </tr>
              <tr>
                <td className="p-2.5 font-semibold text-[#cbd5e1]">Enterprise Value</td>
                <td className="p-2.5 text-text-muted text-right">{fmtMoney(baseVal?.dcf_bridge?.enterprise_value, currency)}</td>
                <td className="p-2.5 text-text-muted text-right">{fmtMoney(bullVal?.dcf_bridge?.enterprise_value, currency)}</td>
                <td className="p-2.5 text-text-muted text-right">{fmtMoney(bearVal?.dcf_bridge?.enterprise_value, currency)}</td>
              </tr>
              <tr>
                <td className="p-2.5 font-semibold text-[#cbd5e1]">WACC (Discount Rate)</td>
                <td className="p-2.5 text-text-muted text-right">{fmtPct(baseVal?.wacc?.wacc, 2)}</td>
                <td className="p-2.5 text-text-muted text-right">{fmtPct(bullVal?.wacc?.wacc, 2)}</td>
                <td className="p-2.5 text-text-muted text-right">{fmtPct(bearVal?.wacc?.wacc, 2)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Methodology & Inputs Strip */}
      <div className="bg-surface border border-border rounded-[4px] p-4 space-y-3 shadow-sm">
        <div className="flex items-center justify-between border-b border-border pb-2">
          <div className="font-semibold text-[13px] text-text-main flex items-center space-x-2">
            <Layers className="w-4 h-4 text-[#0ea5e9]" />
            <span>Key Model Valuation Inputs</span>
          </div>
          {onOpenMethodology && (
            <button
              onClick={onOpenMethodology}
              className="text-[11px] text-[#0ea5e9] hover:underline flex items-center space-x-1 cursor-pointer font-mono"
            >
              <Info className="w-3.5 h-3.5" />
              <span>Methodology Details</span>
            </button>
          )}
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-mono text-[12px]">
          <div className="bg-[#0d1220] border border-[#1e283d] rounded-[4px] p-2.5">
            <div className="text-[10px] text-text-dim uppercase tracking-[0.04em]">
              WACC (Discount Rate)
            </div>
            <div className="font-bold text-[#f8fafc] mt-0.5">
              {fmtPct(wacc.wacc, 2)}
            </div>
          </div>

          <div className="bg-[#0d1220] border border-[#1e283d] rounded-[4px] p-2.5">
            <div className="text-[10px] text-text-dim uppercase tracking-[0.04em]">
              Terminal Growth (g)
            </div>
            <div className="font-bold text-[#f8fafc] mt-0.5">
              {fmtPct(tv.terminal_growth_rate, 2)}
            </div>
          </div>

          <div className="bg-[#0d1220] border border-[#1e283d] rounded-[4px] p-2.5">
            <div className="text-[10px] text-text-dim uppercase tracking-[0.04em]">
              Implied Terminal g
            </div>
            <div className="font-bold text-[#7dd3fc] mt-0.5">
              {reverseDcf.implied_terminal_growth != null
                ? fmtPct(reverseDcf.implied_terminal_growth, 2)
                : '—'}
            </div>
          </div>

          <div
            className="bg-surface-3 border border-border rounded-sm p-2.5"
            title={
              reverseDcf.implied_revenue_cagr != null
                ? `The revenue growth rate that would make this model reproduce the ${reverseDcf.market_price != null ? reverseDcf.market_price.toFixed(2) : 'market'} market price, holding every other assumption fixed.`
                : 'Not solvable. No revenue growth rate between -10% and +50% reproduces the market price under this model\'s margins and WACC, so the engine reports nothing rather than a number it cannot justify. Raise margins or lower the discount rate to bring the two into range.'
            }
          >
            <div className="text-[10px] text-text-dim uppercase tracking-[0.04em]">
              Implied Revenue CAGR
            </div>
            <div className="font-bold text-text-main mt-0.5">
              {reverseDcf.implied_revenue_cagr != null
                ? fmtPct(reverseDcf.implied_revenue_cagr, 1)
                : '—'}
            </div>
          </div>
        </div>
      </div>

      {/* 2-Way Sensitivity Table */}
      {sensTable && (
        <div className="bg-surface border border-border rounded-[4px] p-4 space-y-3 shadow-sm">
          <div className="flex items-center justify-between border-b border-border pb-2">
            <div>
              <h3 className="font-bold text-[13px] text-text-main">
                2-Way Sensitivity Matrix
              </h3>
              <p className="text-[11px] text-text-dim">
                Implied Share Price ({currency}) across WACC vs Terminal Growth (g)
              </p>
            </div>
            <div className="font-mono text-[10px] text-[#0ea5e9] bg-[#0ea5e9]/10 border border-[#0ea5e9]/20 px-2 py-0.5 rounded-[3px]">
              Base: {currencySym}{fmtNum(impliedPrice, 2)}
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-center text-[11px] font-mono border-collapse">
              <caption className="sr-only">
                Implied share price sensitivity across WACC rows and terminal growth columns
              </caption>
              <thead>
                <tr className="bg-surface-3">
                  <th scope="col" className="p-2 border border-border text-left text-text-dim font-semibold">
                    WACC \ Growth
                  </th>
                  {sensTable.col_values?.map((gVal) => (
                    <th
                      key={gVal}
                      scope="col"
                      className="p-2 border border-border text-text-muted"
                    >
                      {gVal.toFixed(1)}%
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sensTable.row_values?.map((waccVal, rIdx) => (
                  <tr key={waccVal}>
                    <th
                      scope="row"
                      className="p-2 border border-border font-bold text-left bg-surface-3 text-text-muted"
                    >
                      {waccVal.toFixed(1)}%
                    </th>
                    {grid[rIdx]?.map((val, cIdx) => {
                      const isBase =
                        Math.abs(waccVal - (wacc.wacc || 0)) < 0.6 &&
                        Math.abs((sensTable.col_values?.[cIdx] || 0) - (tv.terminal_growth_rate || 0)) < 0.6

                      let cellBg = 'bg-surface hover:bg-[#192030]'
                      if (isBase) {
                        cellBg = 'bg-[#0ea5e9]/20 border-2 border-[#0ea5e9] font-bold text-[#7dd3fc]'
                      } else if (marketPrice != null && val != null && val > marketPrice) {
                        cellBg = 'bg-[#10b981]/10 text-[#6ee7b7]'
                      } else if (marketPrice != null && val != null && val < marketPrice) {
                        cellBg = 'bg-[#ef4444]/10 text-[#fca5a5]'
                      }

                      return (
                        <td
                          key={cIdx}
                          className={`p-2 border border-[#1e283d] transition-colors ${cellBg}`}
                        >
                          {currencySym}{fmtNum(val, 0)}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Legend — color never carries meaning alone */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-text-dim">
            <span className="inline-flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-sm bg-positive-subtle border border-positive/40" aria-hidden />
              Above market price
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-sm bg-negative-subtle border border-negative/40" aria-hidden />
              Below market price
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-sm bg-accent-subtle border-2 border-accent" aria-hidden />
              Current base case
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
