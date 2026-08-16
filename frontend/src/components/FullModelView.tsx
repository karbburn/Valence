'use client'

import React, { useState, useMemo } from 'react'
import { FileText, Landmark, Wallet } from 'lucide-react'
import { ModelSpecification, ScenarioLabel } from '@/lib/types'
import { fmtNum, getCurrencySymbol, getCurrencyUnit } from '@/lib/formatters'

export interface FullModelViewProps {
  spec: ModelSpecification | null
  scenario: ScenarioLabel
}

type StatementTab = 'is' | 'bs' | 'cf'

export function FullModelView({ spec, scenario }: FullModelViewProps) {
  const [activeTab, setActiveTab] = useState<StatementTab>('is')

  const currency = spec?.metadata?.currency || 'INR'
  const currencySym = getCurrencySymbol(currency)
  const unit = getCurrencyUnit(currency)

  const historicals = spec?.historicals
  const forecast = spec?.forecast

  const histPeriods = historicals?.periods || ['FY24', 'FY25', 'FY26']
  const fcastPeriods = forecast?.periods || ['FY27', 'FY28', 'FY29', 'FY30', 'FY31']

  const histLineItems = historicals?.line_items || []
  const fcastLineItems = forecast?.line_items || []

  // Memoized lookups for performance
  const histMap = useMemo(() => {
    const map = new Map<string, number | null>()
    for (const li of histLineItems) {
      map.set(`${li.canonical_key}:${li.period_label}`, li.value)
    }
    return map
  }, [histLineItems])

  const fcastMap = useMemo(() => {
    const map = new Map<string, number | null>()
    for (const li of fcastLineItems) {
      map.set(`${li.canonical_key}:${li.period_label}:${li.scenario}`, li.value)
    }
    return map
  }, [fcastLineItems])

  const rows = useMemo(() => {
    if (activeTab === 'is') {
      return [
        { key: 'canonical.is.revenue', label: 'Revenue', bold: true },
        { key: 'canonical.is.cost_of_sales', label: 'Cost of Sales', bold: false },
        { key: 'canonical.is.gross_profit', label: 'Gross Profit', bold: true },
        { key: 'canonical.is.ebitda', label: 'EBITDA', bold: true },
        { key: 'canonical.is.depreciation_amortization', label: 'D&A', bold: false },
        { key: 'canonical.is.operating_profit', label: 'EBIT (Operating Profit)', bold: true },
        { key: 'canonical.is.pbt', label: 'PBT', bold: false },
        { key: 'canonical.is.tax', label: 'Tax Provision', bold: false },
        { key: 'canonical.is.net_profit', label: 'Net Profit (PAT)', bold: true },
      ]
    }
    if (activeTab === 'bs') {
      return [
        { key: 'canonical.bs.borrowings', label: 'Total Debt / Borrowings', bold: false },
        { key: 'canonical.bs.cash_and_bank', label: 'Cash & Bank Balances', bold: false },
        { key: 'canonical.bs.trade_receivables', label: 'Trade Receivables', bold: false },
        { key: 'canonical.bs.inventory', label: 'Inventory', bold: false },
        { key: 'canonical.bs.trade_payables', label: 'Trade Payables', bold: false },
        { key: 'canonical.bs.ppe', label: 'PPE / Net Block', bold: false },
        { key: 'canonical.bs.total_equity', label: "Shareholders' Equity", bold: true },
      ]
    }
    return [
      { key: 'canonical.cf.operating_activities', label: 'Cash from Operations (CFO)', bold: true },
      { key: 'canonical.cf.capex', label: 'Capital Expenditure (CapEx)', bold: false, negate: true },
      { key: 'canonical.cf.investing_activities', label: 'Cash from Investing (CFI)', bold: false },
      { key: 'canonical.cf.financing_activities', label: 'Cash from Financing (CFF)', bold: false },
    ]
  }, [activeTab])

  const getHistoricalVal = (key: string, period: string) => {
    return histMap.get(`${key}:${period}`) ?? null
  }

  const getForecastVal = (key: string, period: string) => {
    return fcastMap.get(`${key}:${period}:${scenario}`) ?? null
  }

  return (
    <div className="bg-surface border border-border rounded-[4px] p-3.5 shadow-sm space-y-3.5 select-none">
      {/* Tab bar navigation & Unit Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b border-border pb-2.5 gap-2.5">
        <div className="flex items-center bg-[#111622] border border-[#1e283d] rounded-[6px] p-1 space-x-1">
          <button
            onClick={() => setActiveTab('is')}
            className={`flex items-center space-x-1.5 px-3 py-1 text-[12px] rounded-[4px] transition-colors ${
              activeTab === 'is'
                ? 'bg-[#0ea5e9] text-white font-semibold shadow-sm'
                : 'text-[#64748b] hover:text-[#f8fafc]'
            }`}
          >
            <FileText className="w-3.5 h-3.5" />
            <span>Income Statement</span>
          </button>
          <button
            onClick={() => setActiveTab('bs')}
            className={`flex items-center space-x-1.5 px-3 py-1 text-[12px] rounded-[4px] transition-colors ${
              activeTab === 'bs'
                ? 'bg-[#0ea5e9] text-white font-semibold shadow-sm'
                : 'text-[#64748b] hover:text-[#f8fafc]'
            }`}
          >
            <Landmark className="w-3.5 h-3.5" />
            <span>Balance Sheet</span>
          </button>
          <button
            onClick={() => setActiveTab('cf')}
            className={`flex items-center space-x-1.5 px-3 py-1 text-[12px] rounded-[4px] transition-colors ${
              activeTab === 'cf'
                ? 'bg-[#0ea5e9] text-white font-semibold shadow-sm'
                : 'text-[#64748b] hover:text-[#f8fafc]'
            }`}
          >
            <Wallet className="w-3.5 h-3.5" />
            <span>Cash Flow</span>
          </button>
        </div>

        <div className="text-[11px] font-mono text-[#64748b]">
          All figures in <span className="font-semibold text-[#f8fafc]">{unit}</span> · FY24–FY26 (Historical) / FY27–FY31 (Forecast: {scenario})
        </div>
      </div>

      {/* 3-Statement Data Table */}
      <div className="overflow-x-auto border border-[#1e283d] rounded-[4px]">
        <table className="w-full text-[11px] border-collapse">
          <thead>
            <tr className="bg-[#0d1220] border-b border-[#1e283d] h-8">
              <th className="px-3 py-1.5 text-left font-semibold text-[#94a3b8] uppercase tracking-[0.04em] w-56">
                Line Item
              </th>
              {/* Historical Columns Header */}
              {histPeriods.map((p) => (
                <th
                  key={p}
                  className="px-3 py-1.5 text-right font-mono font-semibold text-[#94a3b8] w-24"
                >
                  <div className="flex items-center justify-end space-x-1">
                    <span>{p}</span>
                    <span className="text-[10px] font-bold bg-[#192030] border border-[#1e283d] text-[#64748b] px-1 py-[1px] rounded-[2px]">
                      H
                    </span>
                  </div>
                </th>
              ))}
              {/* Forecast Columns Header (with visual separator on first column) */}
              {fcastPeriods.map((p, idx) => (
                <th
                  key={p}
                  className={`px-3 py-1.5 text-right font-mono font-bold text-[#f8fafc] w-24 ${
                    idx === 0 ? 'border-l-2 border-[#374766]' : ''
                  }`}
                >
                  <div className="flex items-center justify-end space-x-1">
                    <span>{p}</span>
                    <span className="text-[10px] font-bold bg-[#0ea5e9]/10 border border-[#0ea5e9]/30 text-[#7dd3fc] px-1 py-[1px] rounded-[2px]">
                      F
                    </span>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#1e283d]/60 font-mono">
            {rows.map((r, i) => {
              const rowStyle = r.bold
                ? 'bg-[#111622]/60 font-semibold'
                : 'hover:bg-[#192030]/40 transition-colors'

              return (
                <tr key={i} className={rowStyle}>
                  <td
                    className={`px-3 py-1.5 ${
                      r.bold ? 'text-[#f8fafc]' : 'text-[#cbd5e1]'
                    }`}
                  >
                    {r.label}
                  </td>
                  {/* Historical Values */}
                  {histPeriods.map((p) => {
                    let val = getHistoricalVal(r.key, p)
                    if (r.negate && val != null) val = Math.abs(val)
                    return (
                      <td
                        key={p}
                        className={`px-3 py-1.5 text-right ${
                          r.bold ? 'text-[#f8fafc]' : 'text-[#64748b]'
                        }`}
                      >
                        {val != null ? `${currencySym}${fmtNum(val)}` : '—'}
                      </td>
                    )
                  })}
                  {/* Forecast Values (with visual separator on first column) */}
                  {fcastPeriods.map((p, idx) => {
                    let val = getForecastVal(r.key, p)
                    if (r.negate && val != null) val = Math.abs(val)
                    return (
                      <td
                        key={p}
                        className={`px-3 py-1.5 text-right ${
                          idx === 0 ? 'border-l-2 border-[#374766]' : ''
                        } ${r.bold ? 'text-[#7dd3fc]' : 'text-[#94a3b8]'}`}
                      >
                        {val != null ? `${currencySym}${fmtNum(val)}` : '—'}
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
  )
}
