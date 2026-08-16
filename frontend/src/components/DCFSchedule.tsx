'use client'

import React from 'react'
import { TableProperties, Info } from 'lucide-react'
import { ModelSpecification, ScenarioLabel } from '@/lib/types'
import { fmtNum, fmtMoney, fmtPct, getCurrencySymbol } from '@/lib/formatters'

export interface DCFScheduleProps {
  spec: ModelSpecification | null
  scenario: ScenarioLabel
  onOpenMethodology?: () => void
}

export function DCFSchedule({ spec, scenario, onOpenMethodology }: DCFScheduleProps) {
  const valuation =
    spec?.valuation?.find((v) => v.scenario === scenario) || spec?.valuation?.[0]

  if (!valuation) {
    return (
      <div className="bg-surface border border-border rounded-[4px] p-6 text-center text-[#64748b] text-[12px]">
        No valuation schedule available for this scenario.
      </div>
    )
  }

  const currency = spec?.metadata?.currency || 'INR'
  const currencySym = getCurrencySymbol(currency)
  const fcffs = valuation.fcff_by_period || []
  const bridge = valuation.dcf_bridge || {}
  const tv = valuation.terminal_value || {}
  const wacc = valuation.wacc || {}

  const rows = [
    { label: 'EBIT (Operating Profit)', fn: (p: typeof fcffs[0]) => fmtNum(p.ebit), bold: false, total: false },
    { label: 'Tax Rate %', fn: (p: typeof fcffs[0]) => fmtPct(p.tax_rate, 1), bold: false, total: false },
    { label: 'NOPAT', fn: (p: typeof fcffs[0]) => fmtNum(p.nopat), bold: true, total: false },
    { label: '+ D&A', fn: (p: typeof fcffs[0]) => fmtNum(p.da), bold: false, total: false },
    { label: '− CapEx', fn: (p: typeof fcffs[0]) => p.capex != null ? `(${fmtNum(Math.abs(p.capex))})` : '—', bold: false, total: false },
    { label: '± ΔNWC', fn: (p: typeof fcffs[0]) => fmtNum(-(p.delta_working_capital || 0)), bold: false, total: false },
    { label: '= FCFF (Free Cash Flow)', fn: (p: typeof fcffs[0]) => fmtNum(p.fcff), bold: true, total: true },
    { label: 'Discount Factor (Mid-Year)', fn: (p: typeof fcffs[0]) => (p.discount_factor || 0).toFixed(4), bold: false, total: false },
    { label: 'PV(FCFF)', fn: (p: typeof fcffs[0]) => fmtNum(p.pv_fcff), bold: true, total: false },
  ]

  const netDebt = bridge.less_net_debt || 0
  const isNetCash = netDebt < 0

  return (
    <div className="bg-surface border border-border rounded-[4px] p-3.5 flex flex-col shadow-sm">
      {/* Header & Bridge Summary */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between border-b border-border pb-2.5 mb-2.5 gap-2">
        <div className="flex items-center space-x-2">
          <TableProperties className="w-4 h-4 text-[#0ea5e9]" />
          <h2 className="font-bold text-[14px] text-text-main">
            FCFF & DCF Valuation Schedule
          </h2>
          {onOpenMethodology && (
            <button
              onClick={onOpenMethodology}
              className="flex items-center space-x-1 text-[10px] font-mono text-[#0ea5e9] bg-[#0ea5e9]/10 border border-[#0ea5e9]/20 hover:bg-[#0ea5e9]/20 rounded-[3px] px-2 py-0.5 transition-colors cursor-pointer ml-1"
              title="Methodology breakdown vs retail screeners (AlphaSpread)"
            >
              <Info className="w-3 h-3 text-[#0ea5e9]" />
              <span>FCFF vs AlphaSpread</span>
            </button>
          )}
        </div>

        {/* Inline DCF Bridge Strip */}
        <div className="flex items-center space-x-3 text-[11px] font-mono bg-[#0d1220] border border-[#1e283d] rounded-[4px] px-2.5 py-0.5 text-[#94a3b8]">
          <div>
            <span className="text-[#64748b]">PV FCFF: </span>
            <span className="text-[#f8fafc] font-semibold">{fmtMoney(bridge.sum_pv_fcff, currency)}</span>
          </div>
          <span className="text-[#374766]">|</span>
          <div>
            <span className="text-[#64748b]">PV TV: </span>
            <span className="text-[#f8fafc] font-semibold">{fmtMoney(bridge.pv_terminal_value, currency)}</span>
          </div>
          <span className="text-[#374766]">|</span>
          <div>
            <span className="text-[#64748b]">Net: </span>
            <span className={`font-semibold ${isNetCash ? 'text-[#10b981]' : 'text-[#ef4444]'}`}>
              {isNetCash ? `+${currencySym}${fmtNum(Math.abs(netDebt))}` : `-${currencySym}${fmtNum(netDebt)}`}
            </span>
          </div>
          <span className="text-[#374766]">|</span>
          <div>
            <span className="text-[#64748b]">Price: </span>
            <span className="text-[#7dd3fc] font-bold">{currencySym}{fmtNum(bridge.implied_share_price, 2)}</span>
          </div>
        </div>
      </div>

      {/* FCFF Matrix Table */}
      <div className="overflow-x-auto border border-[#1e283d] rounded-[4px]">
        <table className="w-full text-[11px] border-collapse">
          <thead>
            <tr className="bg-[#0d1220] border-b border-[#1e283d] h-8">
              <th className="px-3 py-1.5 text-left font-semibold text-[#94a3b8] uppercase tracking-[0.04em]">
                DCF Line Item (Mid-Year)
              </th>
              {fcffs.map((p) => (
                <th
                  key={p.period}
                  className="px-3 py-1.5 text-right font-mono font-bold text-[#f8fafc] w-28"
                >
                  {p.period}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#1e283d]/60 font-mono">
            {rows.map((r, i) => {
              let rowStyle = 'hover:bg-[#192030]/40 transition-colors'
              if (r.total) {
                rowStyle = 'bg-[#0ea5e9]/[0.08] border-t border-[#0ea5e9]/30 font-bold'
              } else if (r.bold) {
                rowStyle = 'bg-[#111622]/60 font-semibold'
              }

              return (
                <tr key={i} className={rowStyle}>
                  <td
                    className={`px-3 py-1.5 ${
                      r.bold ? 'text-[#f8fafc]' : 'text-[#cbd5e1]'
                    }`}
                  >
                    {r.label}
                  </td>
                  {fcffs.map((p) => (
                    <td
                      key={p.period}
                      className={`px-3 py-1.5 text-right ${
                        r.total
                          ? 'text-[#7dd3fc]'
                          : r.bold
                          ? 'text-[#f8fafc]'
                          : 'text-[#94a3b8]'
                      }`}
                    >
                      {r.fn(p)}
                    </td>
                  ))}
                </tr>
              )
            })}

            {/* Valuation Bridge Rows */}
            <tr className="bg-[#0d1220]/80 border-t-2 border-[#2a3652]">
              <td className="px-3 py-1.5 text-[#94a3b8] font-semibold">
                Σ PV of Explicit Forecasts (PV FCFF)
              </td>
              <td
                colSpan={fcffs.length}
                className="px-3 py-1.5 text-right font-bold text-[#f8fafc]"
              >
                {currencySym}{fmtNum(bridge.sum_pv_fcff)}
              </td>
            </tr>

            <tr className="bg-[#0d1220]/80">
              <td className="px-3 py-1.5 text-[#94a3b8] font-semibold">
                + PV of Terminal Value ({(tv.terminal_growth_rate || 4.0).toFixed(1)}% g, {(tv.tv_pct_of_ev || 0).toFixed(0)}% of EV)
              </td>
              <td
                colSpan={fcffs.length}
                className="px-3 py-1.5 text-right font-bold text-[#f8fafc]"
              >
                {currencySym}{fmtNum(bridge.pv_terminal_value)}
              </td>
            </tr>

            <tr className="bg-[#0ea5e9]/[0.08] border-t border-[#0ea5e9]/30">
              <td className="px-3 py-1.5 font-bold text-[#7dd3fc]">
                Enterprise Value (EV)
              </td>
              <td
                colSpan={fcffs.length}
                className="px-3 py-1.5 text-right font-bold text-[#7dd3fc]"
              >
                {currencySym}{fmtNum(bridge.enterprise_value)}
              </td>
            </tr>

            <tr className="bg-[#0d1220]/80">
              <td className="px-3 py-1.5 text-[#94a3b8] font-semibold">
                {isNetCash ? '+ Net Cash & Liquid Assets' : '− Total Net Debt'}
              </td>
              <td
                colSpan={fcffs.length}
                className={`px-3 py-1.5 text-right font-bold ${
                  isNetCash ? 'text-[#10b981]' : 'text-[#ef4444]'
                }`}
              >
                {isNetCash ? `+ ${currencySym}` : `- ${currencySym}`}
                {fmtNum(Math.abs(netDebt))}
              </td>
            </tr>

            <tr className="bg-[#10b981]/[0.08] border-t border-[#10b981]/30">
              <td className="px-3 py-1.5 font-bold text-[#6ee7b7]">
                Equity Value → DCF Implied Share Price
              </td>
              <td
                colSpan={fcffs.length}
                className="px-3 py-1.5 text-right font-bold text-[#6ee7b7]"
              >
                {currencySym}{fmtNum(bridge.equity_value)} → {currencySym}{fmtNum(bridge.implied_share_price, 2)} / share
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* WACC & ROIC Subtext Footer */}
      <div className="mt-2.5 px-3 py-1.5 bg-[#0d1220] border border-[#1e283d] rounded-[4px] text-[10px] font-mono text-[#94a3b8] flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center space-x-3">
          <span><strong className="text-[#f8fafc]">WACC:</strong> {fmtPct(wacc.wacc, 2)}</span>
          <span><strong className="text-[#f8fafc]">Cost of Equity:</strong> {fmtPct(wacc.cost_of_equity, 2)}</span>
          <span><strong className="text-[#f8fafc]">Cost of Debt:</strong> {fmtPct(wacc.cost_of_debt, 2)}</span>
          <span><strong className="text-[#f8fafc]">Equity Wt:</strong> {fmtPct(wacc.equity_weight != null ? wacc.equity_weight * 100 : null, 1)}</span>
        </div>
        {tv.implied_roic != null && (
          <div className="text-[#7dd3fc]">
            Terminal ROIC: {tv.implied_roic.toFixed(1)}% (Reinvest {tv.reinvestment_rate != null ? `${tv.reinvestment_rate.toFixed(1)}%` : '—'})
          </div>
        )}
      </div>
    </div>
  )
}
