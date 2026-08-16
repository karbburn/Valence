'use client'

import React, { useMemo } from 'react'
import { TrendingUp } from 'lucide-react'
import { ModelSpecification, ScenarioLabel } from '@/lib/types'
import { fmtNum, getCurrencySymbol, getCurrencyUnit } from '@/lib/formatters'

export interface ForecastTableProps {
  spec: ModelSpecification | null
  scenario: ScenarioLabel
}

export function ForecastTable({ spec, scenario }: ForecastTableProps) {
  const forecast = spec?.forecast
  const currency = spec?.metadata?.currency || 'INR'
  const currencySym = getCurrencySymbol(currency)
  const unit = getCurrencyUnit(currency)

  const periods = forecast?.periods || ['FY27', 'FY28', 'FY29', 'FY30', 'FY31']
  const lineItems = forecast?.line_items || []

  const rows = [
    { key: 'canonical.is.revenue', label: 'Revenue', bold: true },
    { key: 'canonical.is.ebitda', label: 'EBITDA', bold: false },
    { key: 'canonical.is.operating_profit', label: 'EBIT (Operating Profit)', bold: false },
    { key: 'canonical.is.net_profit', label: 'Net Profit (PAT)', bold: true },
    { key: 'canonical.is.depreciation_amortization', label: 'D&A', bold: false },
    { key: 'canonical.cf.capex', label: 'CapEx', bold: false, negate: true },
    { key: 'canonical.cf.operating_activities', label: 'Operating Cash Flow', bold: false },
  ]

  // Memoized lookup map to avoid O(rows * periods * N) linear searches on render
  const valMap = useMemo(() => {
    const map = new Map<string, number | null>()
    for (const li of lineItems) {
      map.set(`${li.canonical_key}:${li.period_label}:${li.scenario}`, li.value)
    }
    return map
  }, [lineItems])

  const getVal = (canonicalKey: string, period: string) => {
    return valMap.get(`${canonicalKey}:${period}:${scenario}`) ?? null
  }

  return (
    <div className="bg-surface border border-border rounded-[4px] p-4 flex flex-col shadow-sm select-none">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border pb-3 mb-3">
        <div className="flex items-center space-x-2">
          <TrendingUp className="w-4 h-4 text-[#0ea5e9]" />
          <h2 className="font-bold text-[14px] text-text-main">
            Financial Forecast Summary
          </h2>
        </div>
        <span className="font-mono text-[10px] text-[#94a3b8]">
          FY27–FY31 ({unit})
        </span>
      </div>

      {/* Table */}
      <div className="overflow-x-auto border border-[#1e283d] rounded-[4px]">
        <table className="w-full text-[11px] border-collapse">
          <thead>
            <tr className="bg-[#0d1220] border-b border-[#1e283d] h-9">
              <th className="px-3 py-2 text-left font-semibold text-[#94a3b8] uppercase tracking-[0.04em]">
                Line Item
              </th>
              {periods.map((p) => (
                <th
                  key={p}
                  className="px-3 py-2 text-right font-mono font-bold text-[#f8fafc] w-28"
                >
                  {p}
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
                    className={`px-3 py-2 ${
                      r.bold ? 'text-[#f8fafc]' : 'text-[#cbd5e1]'
                    }`}
                  >
                    {r.label}
                  </td>
                  {periods.map((p) => {
                    let val = getVal(r.key, p)
                    if (r.negate && val != null) val = Math.abs(val)

                    return (
                      <td
                        key={p}
                        className={`px-3 py-2 text-right ${
                          r.bold ? 'text-[#f8fafc]' : 'text-[#94a3b8]'
                        }`}
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
