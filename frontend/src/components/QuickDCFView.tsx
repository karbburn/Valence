'use client'

import React from 'react'
import { Sparkles, ArrowUpRight, ArrowDownRight, Layers, Info } from 'lucide-react'
import { ModelSpecification, ScenarioLabel } from '@/lib/types'
import { fmtNum, fmtPct, fmtPrice, getCurrencySymbol } from '@/lib/formatters'

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
      <div className="bg-surface border border-border rounded-[4px] p-6 text-center text-[#64748b] text-[12px]">
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

  let upsidePct: number | null = null
  if (impliedPrice != null && marketPrice != null && marketPrice > 0) {
    upsidePct = ((impliedPrice - marketPrice) / marketPrice) * 100
  }

  const grid = sensTable?.results_grid || []

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Hero 3-Column Valuation Strip */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Intrinsic Value Hero */}
        <div className="bg-surface border border-[#0ea5e9]/40 rounded-[4px] p-5 text-center flex flex-col justify-center items-center shadow-sm relative">
          <div className="flex items-center space-x-1.5 text-[11px] font-semibold uppercase tracking-[0.04em] text-[#94a3b8] mb-1">
            <Sparkles className="w-3.5 h-3.5 text-[#0ea5e9]" />
            <span>DCF Intrinsic Value</span>
            {onOpenMethodology && (
              <button
                onClick={onOpenMethodology}
                className="text-[#0ea5e9] hover:text-[#7dd3fc] transition-colors p-0.5 ml-1 cursor-pointer"
                title="Methodology breakdown vs retail screeners (AlphaSpread)"
              >
                <Info className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
          <div className="font-mono font-bold text-[30px] text-[#7dd3fc]">
            {impliedPrice != null ? fmtPrice(impliedPrice, currency, 2) : '—'}
          </div>
          <div className="text-[11px] text-[#64748b] mt-1 font-mono">
            Per Share ({currency}) · FCFF @ WACC
          </div>
        </div>

        {/* Current Market Price */}
        <div className="bg-surface border border-border rounded-[4px] p-5 text-center flex flex-col justify-center items-center shadow-sm">
          <div className="text-[11px] font-semibold uppercase tracking-[0.04em] text-[#94a3b8] mb-1">
            Current Market Price
          </div>
          <div className="font-mono font-bold text-[26px] text-[#f8fafc]">
            {marketPrice != null ? fmtPrice(marketPrice, currency, 2) : '—'}
          </div>
          <div className="text-[11px] text-[#64748b] mt-1">
            Benchmark Quote
          </div>
        </div>

        {/* Implied Upside / Downside */}
        <div className="bg-surface border border-border rounded-[4px] p-5 text-center flex flex-col justify-center items-center shadow-sm">
          <div className="text-[11px] font-semibold uppercase tracking-[0.04em] text-[#94a3b8] mb-1">
            Implied Upside / Downside
          </div>
          <div
            className={`font-mono font-bold text-[30px] flex items-center space-x-1 ${
              upsidePct != null && upsidePct >= 0
                ? 'text-[#10b981]'
                : 'text-[#ef4444]'
            }`}
          >
            {upsidePct != null ? (
              <>
                {upsidePct >= 0 ? (
                  <ArrowUpRight className="w-6 h-6 text-[#10b981]" />
                ) : (
                  <ArrowDownRight className="w-6 h-6 text-[#ef4444]" />
                )}
                <span>
                  {upsidePct >= 0 ? '+' : ''}
                  {fmtPct(upsidePct, 1)}
                </span>
              </>
            ) : (
              '—'
            )}
          </div>
          <div className="text-[11px] text-[#64748b] mt-1">
            vs Current Market Quote
          </div>
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
              <span>Why Valence vs AlphaSpread?</span>
            </button>
          )}
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-mono text-[12px]">
          <div className="bg-[#0d1220] border border-[#1e283d] rounded-[4px] p-2.5">
            <div className="text-[10px] text-[#64748b] uppercase tracking-[0.04em]">
              WACC (Discount Rate)
            </div>
            <div className="font-bold text-[#f8fafc] mt-0.5">
              {fmtPct(wacc.wacc, 2)}
            </div>
          </div>

          <div className="bg-[#0d1220] border border-[#1e283d] rounded-[4px] p-2.5">
            <div className="text-[10px] text-[#64748b] uppercase tracking-[0.04em]">
              Terminal Growth (g)
            </div>
            <div className="font-bold text-[#f8fafc] mt-0.5">
              {fmtPct(tv.terminal_growth_rate, 2)}
            </div>
          </div>

          <div className="bg-[#0d1220] border border-[#1e283d] rounded-[4px] p-2.5">
            <div className="text-[10px] text-[#64748b] uppercase tracking-[0.04em]">
              Implied Terminal g
            </div>
            <div className="font-bold text-[#7dd3fc] mt-0.5">
              {reverseDcf.implied_terminal_growth != null
                ? fmtPct(reverseDcf.implied_terminal_growth, 2)
                : '—'}
            </div>
          </div>

          <div className="bg-[#0d1220] border border-[#1e283d] rounded-[4px] p-2.5">
            <div className="text-[10px] text-[#64748b] uppercase tracking-[0.04em]">
              Model Template
            </div>
            <div className="font-bold text-[#10b981] mt-0.5">
              FCFF (Wall St Std)
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
              <p className="text-[11px] text-[#64748b]">
                Implied Share Price ({currency}) across WACC vs Terminal Growth ($g$)
              </p>
            </div>
            <div className="font-mono text-[10px] text-[#0ea5e9] bg-[#0ea5e9]/10 border border-[#0ea5e9]/20 px-2 py-0.5 rounded-[3px]">
              Base: {currencySym}{fmtNum(impliedPrice, 2)}
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-center text-[11px] font-mono border-collapse">
              <thead>
                <tr className="bg-[#0d1220]">
                  <th className="p-2 border border-[#1e283d] text-left text-[#64748b]">
                    WACC \ g
                  </th>
                  {sensTable.col_values?.map((gVal) => (
                    <th
                      key={gVal}
                      className="p-2 border border-[#1e283d] text-[#94a3b8]"
                    >
                      {gVal.toFixed(1)}%
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sensTable.row_values?.map((waccVal, rIdx) => (
                  <tr key={waccVal}>
                    <td className="p-2 border border-[#1e283d] font-bold text-left bg-[#0d1220] text-[#94a3b8]">
                      {waccVal.toFixed(1)}%
                    </td>
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
        </div>
      )}
    </div>
  )
}
