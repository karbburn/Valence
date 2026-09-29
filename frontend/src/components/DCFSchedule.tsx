'use client'

import React from 'react'
import { TableProperties, Info } from 'lucide-react'
import { ModelSpecification, ScenarioLabel } from '@/lib/types'
import { fmtNum, fmtMoney, fmtPct, getCurrencySymbol } from '@/lib/formatters'
import { NO_VALUE } from '@/lib/noValue'

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
      <div className="bg-surface border border-border rounded-[4px] p-6 text-center text-text-dim text-[12px]">
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

  const ROW_TOOLTIPS: Record<string, { desc: string; formula: string }> = {
    'EBIT (Operating Profit)': {
      desc: 'Earnings Before Interest and Taxes: core operating profitability before capital structure and taxes.',
      formula: 'Revenue - COGS - Operating Expenses - D&A',
    },
    'Tax Rate %': {
      desc: 'Effective corporate tax rate applied to operating earnings for NOPAT calculation.',
      formula: 'Taxes / PBT',
    },
    'NOPAT': {
      desc: 'Net Operating Profit After Tax: un-levered profit generated purely by core operations.',
      formula: 'EBIT × (1 - Effective Tax Rate)',
    },
    '+ D&A': {
      desc: 'Depreciation & Amortization added back because it is a non-cash accounting expense.',
      formula: 'Cash Flow Statement D&A Add-back',
    },
    '− CapEx': {
      desc: 'Capital Expenditures: net cash spent on property, plant, equipment, and intangible assets.',
      formula: 'Cash Flow Statement Capital Investments',
    },
    '± ΔNWC': {
      desc: 'Change in Non-Cash Operating Working Capital: cash invested or freed up in working capital.',
      formula: '− (Δ Receivables + Δ Inventory − Δ Payables)',
    },
    '− Stock Comp': {
      desc: 'Stock-based compensation deducted as a real economic cost even though non-cash under accounting rules.',
      formula: 'Cash Flow Statement SBC (when reported)',
    },
    '= FCFF (Free Cash Flow)': {
      desc: 'Free Cash Flow to Firm: unlevered cash flow available to all debt and equity capital providers.',
      formula: 'NOPAT + D&A − CapEx − ΔNWC − Stock Comp',
    },
    'Discount Factor (Mid-Year)': {
      desc: 'Mid-year discount factor assuming cash flows arrive continuously throughout the year.',
      formula: '1 / (1 + WACC)^(t - 0.5)',
    },
    'PV(FCFF)': {
      desc: 'Present Value of Free Cash Flow discounted back to current fiscal year.',
      formula: 'FCFF × Mid-Year Discount Factor',
    },
  }

  const rows = [
    { label: 'EBIT (Operating Profit)', fn: (p: typeof fcffs[0]) => fmtNum(p.ebit), bold: false, total: false },
    { label: 'Tax Rate %', fn: (p: typeof fcffs[0]) => fmtPct(p.tax_rate, 1), bold: false, total: false },
    { label: 'NOPAT', fn: (p: typeof fcffs[0]) => fmtNum(p.nopat), bold: true, total: false },
    { label: '+ D&A', fn: (p: typeof fcffs[0]) => fmtNum(p.da), bold: false, total: false },
    { label: '− CapEx', fn: (p: typeof fcffs[0]) => p.capex != null ? `(${fmtNum(Math.abs(p.capex))})` : NO_VALUE, bold: false, total: false },
    { label: '± ΔNWC', fn: (p: typeof fcffs[0]) => fmtNum(-(p.delta_working_capital || 0)), bold: false, total: false },
    ...fcffs.some((p) => (p.stock_compensation || 0) > 0)
      ? [{ label: '− Stock Comp', fn: (p: typeof fcffs[0]) => (p.stock_compensation || 0) > 0 ? `(${fmtNum(p.stock_compensation!)})` : NO_VALUE, bold: false, total: false }]
      : [],
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
              title="Methodology breakdown: FCFF at WACC"
            >
              <Info className="w-3 h-3 text-[#0ea5e9]" />
              <span>Methodology Details</span>
            </button>
          )}
        </div>

        {/* Inline DCF Bridge Strip */}
        <div className="flex items-center space-x-3 text-[11px] font-mono bg-[#0d1220] border border-[#1e283d] rounded-[4px] px-2.5 py-0.5 text-[#94a3b8]">
          <div>
            <span className="text-text-dim">PV FCFF: </span>
            <span className="text-[#f8fafc] font-semibold">{fmtMoney(bridge.sum_pv_fcff, currency)}</span>
          </div>
          <span className="text-[#374766]">|</span>
          <div>
            <span className="text-text-dim">PV TV: </span>
            <span className="text-[#f8fafc] font-semibold">{fmtMoney(bridge.pv_terminal_value, currency)}</span>
          </div>
          <span className="text-[#374766]">|</span>
          <div
            title={
              bridge.debt_basis_note ||
              'Net cash = cash and short-term investments less total debt.'
            }
          >
            <span className="text-text-dim">Net: </span>
            <span className={`font-semibold ${isNetCash ? 'text-positive' : 'text-negative'}`}>
              {isNetCash ? `+${currencySym}${fmtNum(Math.abs(netDebt))}` : `-${currencySym}${fmtNum(netDebt)}`}
            </span>
            {/*
              The net figure is only interpretable alongside the date of the
              balance sheet it came from. A live price paired with a year-old
              balance sheet produces an enterprise value that looks current and
              is not, and nothing else on the screen reveals it.
            */}
            {bridge.balance_sheet_as_of && (
              <span className="text-text-dim ml-1">@ {bridge.balance_sheet_as_of}</span>
            )}
          </div>
          <span className="text-[#374766]">|</span>
          <div>
            <span className="text-text-dim">Price: </span>
            <span className="text-[#7dd3fc] font-bold">{currencySym}{fmtNum(bridge.implied_share_price, 2)}</span>
          </div>
        </div>
      </div>

      {/* FCFF Matrix Table */}
      <div className="overflow-x-auto border border-border rounded-sm">
        <table className="w-full text-[11px] border-collapse">
          <caption className="sr-only">
            Five-year FCFF build-up with mid-year discounting and the enterprise-to-equity bridge
          </caption>
          <thead>
            <tr className="bg-surface-3 border-b border-border h-8">
              <th
                scope="col"
                className="sticky-col-deep px-3 py-1.5 text-left font-semibold text-text-muted uppercase tracking-[0.04em]"
              >
                DCF Line Item (Mid-Year)
              </th>
              {fcffs.map((p) => (
                <th
                  key={p.period}
                  scope="col"
                  className="px-3 py-1.5 text-right font-mono font-bold text-text-main w-28"
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
                    } ${r.total ? 'sticky-col-total' : 'sticky-col'}`}
                  >
                    <div className="group relative inline-flex items-center space-x-1.5">
                      <span>{r.label}</span>
                      {ROW_TOOLTIPS[r.label] && (
                        <>
                          <button
                            type="button"
                            tabIndex={0}
                            aria-label={`${r.label}: ${ROW_TOOLTIPS[r.label].desc} Formula: ${ROW_TOOLTIPS[r.label].formula}`}
                            className="cursor-help text-accent group-hover:text-accent-hover group-focus-visible:text-accent-hover transition-colors"
                          >
                            <Info className="w-3 h-3 shrink-0" aria-hidden />
                          </button>
                          <div
                            role="tooltip"
                            className="pointer-events-none absolute left-0 top-full mt-1.5 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 w-80 p-3 bg-surface-2 border border-accent-border rounded-sm shadow-pop z-50 text-[11.5px] font-sans text-text-main leading-normal"
                          >
                            <div className="font-bold text-[12px] text-accent-hover mb-1 flex items-center justify-between">
                              <span>{r.label}</span>
                              <span className="text-[10px] font-mono uppercase bg-accent-subtle text-accent-hover border border-accent-border px-1.5 py-0.5 rounded-sm">Definition</span>
                            </div>
                            <div className="text-[#cbd5e1] font-normal mb-2 leading-snug">{ROW_TOOLTIPS[r.label].desc}</div>
                            <div className="font-mono text-[10.5px] font-semibold text-accent-hover bg-canvas border border-border-interactive px-2 py-1 rounded-sm">
                              <span className="text-text-muted mr-1 font-sans font-normal">Formula:</span> {ROW_TOOLTIPS[r.label].formula}
                            </div>
                          </div>
                        </>
                      )}
                    </div>
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
              <td className="sticky-col-deep px-3 py-1.5 text-text-muted font-semibold">
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
              <td className="sticky-col-deep px-3 py-1.5 text-text-muted font-semibold">
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
              <td className="sticky-col-total px-3 py-1.5 font-bold text-accent-hover">
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
              <td className="sticky-col-deep px-3 py-1.5 text-text-muted font-semibold">
                {isNetCash ? '+ Net Cash & Liquid Assets' : '− Total Net Debt'}
              </td>
              <td
                colSpan={fcffs.length}
                className={`px-3 py-1.5 text-right font-bold ${
                  isNetCash ? 'text-positive' : 'text-negative'
                }`}
              >
                {isNetCash ? `+ ${currencySym}` : `- ${currencySym}`}
                {fmtNum(Math.abs(netDebt))}
              </td>
            </tr>

            <tr className="bg-positive-subtle border-t border-positive">
              <td className="sticky-col px-3 py-1.5 font-bold text-[#6ee7b7]">
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
            Terminal ROIC: {tv.implied_roic.toFixed(1)}% (Reinvest {tv.reinvestment_rate != null ? `${tv.reinvestment_rate.toFixed(1)}%` : NO_VALUE})
          </div>
        )}
      </div>
    </div>
  )
}
