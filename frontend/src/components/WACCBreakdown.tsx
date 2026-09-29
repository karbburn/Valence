'use client'

import React from 'react'
import { Percent } from 'lucide-react'
import { ModelSpecification, ScenarioLabel } from '@/lib/types'
import { fmtPct } from '@/lib/formatters'
import { NO_VALUE } from '@/lib/noValue'

export interface WACCBreakdownProps {
  spec: ModelSpecification | null
  scenario: ScenarioLabel
}

export function WACCBreakdown({ spec, scenario }: WACCBreakdownProps) {
  const valuation =
    spec?.valuation?.find((v) => v.scenario === scenario) || spec?.valuation?.[0]
  const wacc = valuation?.wacc

  if (!wacc) return null

  // Rate values from backend are already in percentage scale (e.g. 7.1, 13.5, 12.8)
  const rf = wacc.risk_free_rate ?? null
  const beta = wacc.beta ?? null
  const erp = wacc.equity_risk_premium ?? null
  const ke = wacc.cost_of_equity ?? null
  const preTaxKd = wacc.pre_tax_cost_of_debt ?? null
  const taxRate = wacc.tax_rate ?? null
  const postTaxKd = wacc.cost_of_debt ?? null
  // Weights are fractions (e.g. 0.95 / 0.05)
  const eqWeight = wacc.equity_weight != null ? wacc.equity_weight * 100 : null
  const debtWeight = wacc.debt_weight != null ? wacc.debt_weight * 100 : null
  const waccVal = wacc.wacc ?? null

  return (
    <div className="bg-surface border border-border rounded-[4px] p-3.5 flex flex-col shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border pb-2.5 mb-2.5">
        <div className="flex items-center space-x-2">
          <Percent className="w-4 h-4 text-[#0ea5e9]" />
          <h2 className="font-bold text-[14px] text-text-main">
            WACC & Capital Cost
          </h2>
        </div>
        <span className="font-mono text-[10px] text-[#94a3b8]">
          CAPM Matrix
        </span>
      </div>

      {/* Flat 2-Column Table */}
      <div className="bg-[#0d1220] border border-[#1e283d] rounded-[4px] divide-y divide-[#1e283d] overflow-hidden text-[12px]">
        {/* Risk-Free Rate */}
        <div className="flex items-center justify-between px-[8px] py-[6px]">
          <span className="text-[#94a3b8]">Risk-Free Rate (Rf)</span>
          <span className="font-mono text-[#f8fafc]">{fmtPct(rf, 2)}</span>
        </div>

        {/* Beta */}
        <div className="flex items-center justify-between px-[8px] py-[6px]">
          <span className="text-[#94a3b8]">Beta (β)</span>
          <span className="font-mono text-[#f8fafc]">{beta != null ? beta.toFixed(2) : NO_VALUE}</span>
        </div>

        {/* Equity Risk Premium */}
        <div className="flex items-center justify-between px-[8px] py-[6px]">
          <span className="text-[#94a3b8]">Equity Risk Premium (ERP)</span>
          <span className="font-mono text-[#f8fafc]">{fmtPct(erp, 2)}</span>
        </div>

        {/* Cost of Equity (Highlight) */}
        <div className="flex items-center justify-between px-[8px] py-[6px] bg-[#111622]/60">
          <span className="font-semibold text-[#7dd3fc]">Cost of Equity (Ke)</span>
          <span className="font-mono font-bold text-[#7dd3fc]">{fmtPct(ke, 2)}</span>
        </div>

        {/* Pre-Tax Cost of Debt */}
        <div className="flex items-center justify-between px-[8px] py-[6px]">
          <span className="text-[#94a3b8]">Pre-Tax Cost of Debt (Kd)</span>
          <span className="font-mono text-[#f8fafc]">{fmtPct(preTaxKd, 2)}</span>
        </div>

        {/* Marginal Tax Rate */}
        <div className="flex items-center justify-between px-[8px] py-[6px]">
          <span className="text-[#94a3b8]">Effective Tax Rate (t)</span>
          <span className="font-mono text-[#f8fafc]">{fmtPct(taxRate, 2)}</span>
        </div>

        {/* After-Tax Cost of Debt */}
        <div className="flex items-center justify-between px-[8px] py-[6px]">
          <span className="text-[#94a3b8]">After-Tax Cost of Debt</span>
          <span className="font-mono text-[#f8fafc]">{fmtPct(postTaxKd, 2)}</span>
        </div>

        {/* Capital Weights */}
        <div className="flex items-center justify-between px-[8px] py-[6px]">
          <span className="text-[#94a3b8]">Weights (Equity / Debt)</span>
          <span className="font-mono text-[#94a3b8]">
            {fmtPct(eqWeight, 1)} / {fmtPct(debtWeight, 1)}
          </span>
        </div>

        {/* WACC Summary (Primary Highlight) */}
        <div className="flex items-center justify-between px-[8px] py-[7px] bg-[#0ea5e9]/10 border-t border-[#0ea5e9]/30">
          <span className="font-bold text-[12.5px] text-[#7dd3fc]">
            Weighted Average Cost of Capital
          </span>
          <span className="font-mono font-bold text-[13.5px] text-[#7dd3fc]">
            {fmtPct(waccVal, 2)}
          </span>
        </div>
      </div>

      {/* Footnote */}
      {wacc.source_notes && (
        <div className="text-[10px] font-mono text-text-faint mt-2 truncate">
          Source: {wacc.source_notes}
        </div>
      )}
    </div>
  )
}
