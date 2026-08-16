'use client'

import React from 'react'
import { Sparkles, ArrowUpRight, ArrowDownRight, Layers } from 'lucide-react'
import { ModelSpecification, ScenarioLabel } from '@/lib/types'
import { fmtNum, fmtPct, getCurrencySymbol } from '@/lib/formatters'

export interface QuickDCFViewProps {
  spec: ModelSpecification | null
  scenario: ScenarioLabel
}

export function QuickDCFView({ spec, scenario }: QuickDCFViewProps) {
  const valuation =
    spec?.valuation?.find((v) => v.scenario === scenario) || spec?.valuation?.[0]

  if (!valuation) {
    return (
      <div className="bg-surface border border-border rounded-[4px] p-8 text-center text-[#64748b] text-[13px]">
        No valuation data available for this scenario.
      </div>
    )
  }

  const currency = spec?.metadata?.currency || 'INR'
  const currencySym = getCurrencySymbol(currency)
  const bridge = valuation.dcf_bridge || {}
  const wacc = valuation.wacc || {}
  const tv = valuation.terminal_value || {}
  const revDcf = valuation.reverse_dcf || {}

  const impliedPrice = bridge.implied_share_price ?? null
  const marketPrice = revDcf.market_price ?? null

  let upsidePct: number | null = null
  if (impliedPrice != null && marketPrice != null && marketPrice > 0) {
    upsidePct = ((impliedPrice - marketPrice) / marketPrice) * 100
  }

  // Values from backend are already in percentage scale (e.g., 12.8, 4.0)
  const waccVal = wacc.wacc ?? null
  const terminalGrowthVal = tv.terminal_growth_rate ?? 4.0
  const impliedGVal = revDcf.implied_terminal_growth ?? null

  const sensTable = valuation.sensitivity_tables?.[0]
  const rowVals = sensTable?.row_values || []
  const colVals = sensTable?.col_values || []
  const grid = sensTable?.results_grid || []

  return (
    <div className="max-w-4xl mx-auto space-y-6 select-none">
      {/* Hero 3-Column Valuation Strip */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Intrinsic Value Hero */}
        <div className="bg-surface border border-[#0ea5e9]/40 rounded-[4px] p-5 text-center flex flex-col justify-center items-center shadow-sm">
          <div className="flex items-center space-x-1.5 text-[11px] font-semibold uppercase tracking-[0.04em] text-[#94a3b8] mb-1">
            <Sparkles className="w-3.5 h-3.5 text-[#0ea5e9]" />
            <span>DCF Intrinsic Value</span>
          </div>
          <div className="font-mono font-bold text-[30px] text-[#7dd3fc]">
            {impliedPrice != null ? `${currencySym}${fmtNum(impliedPrice, 2)}` : '—'}
          </div>
          <div className="text-[11px] text-[#64748b] mt-1 font-mono">
            Per Share ({currency})
          </div>
        </div>

        {/* Current Market Price */}
        <div className="bg-surface border border-border rounded-[4px] p-5 text-center flex flex-col justify-center items-center shadow-sm">
          <div className="text-[11px] font-semibold uppercase tracking-[0.04em] text-[#94a3b8] mb-1">
            Current Market Price
          </div>
          <div className="font-mono font-bold text-[26px] text-[#f8fafc]">
            {marketPrice != null ? `${currencySym}${fmtNum(marketPrice, 2)}` : '—'}
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
                  <ArrowUpRight className="w-6 h-6 shrink-0" />
                ) : (
                  <ArrowDownRight className="w-6 h-6 shrink-0" />
                )}
                <span>
                  {upsidePct >= 0 ? '+' : ''}
                  {fmtPct(upsidePct, 1)}
                </span>
              </>
            ) : (
              <span>—</span>
            )}
          </div>
          <div className="text-[11px] text-[#64748b] mt-1">
            Relative to Intrinsic DCF
          </div>
        </div>
      </div>

      {/* Key Valuation Drivers Summary Row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-[#080c14] border border-[#1e283d] rounded-[4px] p-4 flex flex-col justify-between">
          <span className="text-[12px] font-semibold text-[#64748b]">
            Discount Rate (WACC)
          </span>
          <div className="font-mono font-bold text-[20px] text-[#f8fafc] mt-1">
            {waccVal != null ? fmtPct(waccVal, 2) : '—'}
          </div>
          <span className="text-[11px] text-[#475569] mt-0.5">CAPM Matrix</span>
        </div>

        <div className="bg-[#080c14] border border-[#1e283d] rounded-[4px] p-4 flex flex-col justify-between">
          <span className="text-[12px] font-semibold text-[#64748b]">
            Terminal Growth Rate (g)
          </span>
          <div className="font-mono font-bold text-[20px] text-[#f8fafc] mt-1">
            {fmtPct(terminalGrowthVal, 2)}
          </div>
          <span className="text-[11px] text-[#475569] mt-0.5">Perpetual Gordon Growth</span>
        </div>

        <div className="bg-[#080c14] border border-[#1e283d] rounded-[4px] p-4 flex flex-col justify-between">
          <span className="text-[12px] font-semibold text-[#64748b]">
            Market Implied Growth (Reverse DCF)
          </span>
          <div className="font-mono font-bold text-[20px] text-[#f8fafc] mt-1">
            {impliedGVal != null ? fmtPct(impliedGVal, 2) : '—'}
          </div>
          <span className="text-[11px] text-[#475569] mt-0.5">Growth Priced by Market</span>
        </div>
      </div>

      {/* 2-Way Sensitivity Matrix Table */}
      {sensTable && (
        <div className="bg-surface border border-border rounded-[4px] p-5 shadow-sm space-y-3">
          <div className="flex items-center justify-between border-b border-border pb-3">
            <div className="flex items-center space-x-2">
              <Layers className="w-4 h-4 text-[#0ea5e9]" />
              <h3 className="font-bold text-[14px] text-text-main">
                Valuation Sensitivity Matrix
              </h3>
            </div>
            <span className="font-mono text-[10px] text-[#94a3b8]">
              WACC (Rows) vs Terminal Growth % (Cols) → Share Price ({currencySym})
            </span>
          </div>

          <div className="overflow-x-auto border border-[#1e283d] rounded-[4px]">
            <table className="w-full text-[11px] border-collapse">
              <thead>
                <tr className="bg-[#0d1220] border-b border-[#1e283d] h-9">
                  <th className="px-3 py-2 text-left font-semibold text-[#64748b]">
                    WACC \ g
                  </th>
                  {colVals.map((g) => {
                    const isBaseCol =
                      Math.abs(g - (tv.terminal_growth_rate || 4.0)) < 0.1
                    return (
                      <th
                        key={g}
                        className={`px-3 py-2 text-right font-mono font-bold ${
                          isBaseCol ? 'text-[#7dd3fc]' : 'text-[#94a3b8]'
                        }`}
                      >
                        {fmtPct(g, 1)}
                      </th>
                    )
                  })}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1e283d]/60 font-mono">
                {rowVals.map((w, ri) => {
                  const isBaseRow =
                    Math.abs(w - (wacc.wacc || 12.0)) < 0.1
                  return (
                    <tr
                      key={w}
                      className={
                        isBaseRow
                          ? 'bg-[#0ea5e9]/[0.06]'
                          : 'hover:bg-[#192030]/40 transition-colors'
                      }
                    >
                      <td
                        className={`px-3 py-2 ${
                          isBaseRow
                            ? 'text-[#7dd3fc] font-bold'
                            : 'text-[#64748b]'
                        }`}
                      >
                        {fmtPct(w, 1)}
                      </td>
                      {(grid[ri] || []).map((v, ci) => {
                        const isBaseCell =
                          isBaseRow &&
                          Math.abs(
                            colVals[ci] - (tv.terminal_growth_rate || 4.0)
                          ) < 0.1

                        let cellClass = 'text-[#94a3b8]'
                        if (isBaseCell) {
                          cellClass =
                            'bg-[#0ea5e9]/20 text-[#7dd3fc] font-bold border border-[#0ea5e9]/40'
                        } else if (v != null && marketPrice != null && marketPrice > 0) {
                          const cellUpside = ((v - marketPrice) / marketPrice) * 100
                          if (cellUpside > 10) cellClass = 'text-[#10b981] font-semibold'
                          else if (cellUpside >= 0) cellClass = 'text-[#f8fafc]'
                          else cellClass = 'text-[#ef4444]'
                        }

                        return (
                          <td
                            key={ci}
                            className={`px-3 py-2 text-right ${cellClass}`}
                          >
                            {v != null ? `${currencySym}${fmtNum(v, 0)}` : '—'}
                          </td>
                        )
                      })}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
