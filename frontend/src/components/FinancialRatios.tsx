'use client'

import React from 'react'
import { Activity, ShieldCheck, Zap } from 'lucide-react'
import { ModelSpecification, ScenarioLabel } from '@/lib/types'
import { fmtNum, fmtPct, getCurrencySymbol } from '@/lib/formatters'

export interface FinancialRatiosProps {
  spec: ModelSpecification | null
  scenario: ScenarioLabel
}

export function FinancialRatios({ spec, scenario }: FinancialRatiosProps) {
  const valuation =
    spec?.valuation?.find((v) => v.scenario === scenario) || spec?.valuation?.[0]

  if (!valuation) return null

  const currency = spec?.metadata?.currency || 'INR'
  const currencySym = getCurrencySymbol(currency)
  const wacc = valuation.wacc?.wacc ?? null
  const tv = valuation.terminal_value
  const bridge = valuation.dcf_bridge

  const roic = tv?.implied_roic ?? null
  const spread = roic != null && wacc != null ? roic - wacc : null

  // Calculate FCF Yield % (FCFF Yr 1 / Market Cap or Equity Value)
  const fcffYr1 = valuation.fcff_by_period?.[0]?.fcff ?? null
  const equityVal = bridge?.equity_value ?? null
  const fcfYield =
    fcffYr1 != null && equityVal != null && equityVal > 0
      ? (fcffYr1 / equityVal) * 100
      : null

  // EBIT & Net Debt
  const ebitYr1 = valuation.fcff_by_period?.[0]?.ebit ?? null
  const netDebt = bridge?.less_net_debt ?? 0

  // EV / EBIT multiple
  const ev = bridge?.enterprise_value ?? null
  const evEbit = ev != null && ebitYr1 != null && ebitYr1 > 0 ? ev / ebitYr1 : null

  return (
    <div className="bg-surface border border-border rounded-[4px] p-3.5 flex flex-col shadow-sm space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border pb-2.5">
        <div className="flex items-center space-x-2">
          <Activity className="w-4 h-4 text-[#0ea5e9]" />
          <h2 className="font-bold text-[14px] text-text-main">
            Return Metrics & Financial Health
          </h2>
        </div>
        <span className="font-mono text-[10px] text-[#94a3b8]">
          Capital Efficiency
        </span>
      </div>

      {/* Grid of Key Ratios */}
      <div className="grid grid-cols-2 gap-2.5 font-mono text-[11px]">
        {/* ROIC vs WACC Spread */}
        <div className="bg-[#0d1220] border border-[#1e283d] rounded-[4px] p-2.5 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-text-dim text-[10px] uppercase">Terminal ROIC</span>
            <ShieldCheck className="w-3.5 h-3.5 text-positive" />
          </div>
          <div className="font-bold text-[15px] text-[#f8fafc] mt-1">
            {fmtPct(roic, 1)}
          </div>
          <div className="text-[10px] mt-0.5">
            {spread != null ? (
              <span className={spread >= 0 ? 'text-positive' : 'text-negative'}>
                {spread >= 0 ? '+' : ''}{spread.toFixed(1)}% vs WACC
              </span>
            ) : (
              <span className="text-text-dim">Economic Moat</span>
            )}
          </div>
        </div>

        {/* FCF Yield */}
        <div className="bg-[#0d1220] border border-[#1e283d] rounded-[4px] p-2.5 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-text-dim text-[10px] uppercase">FCF Yield (Yr 1)</span>
            <Zap className="w-3.5 h-3.5 text-[#0ea5e9]" />
          </div>
          <div className="font-bold text-[15px] text-[#7dd3fc] mt-1">
            {fmtPct(fcfYield, 1)}
          </div>
          <div className="text-[10px] text-text-dim mt-0.5">
            FCFF / Equity Val
          </div>
        </div>

        {/* EV / EBIT Multiple */}
        <div className="bg-[#0d1220] border border-[#1e283d] rounded-[4px] p-2.5 flex flex-col justify-between">
          <span className="text-text-dim text-[10px] uppercase">Implied EV / EBIT</span>
          <div className="font-bold text-[15px] text-[#f8fafc] mt-1">
            {evEbit != null ? `${fmtNum(evEbit, 1)}x` : 'n/a'}
          </div>
          <div className="text-[10px] text-text-dim mt-0.5">
            Forward Multiple
          </div>
        </div>

        {/* Net Debt Status */}
        <div className="bg-[#0d1220] border border-[#1e283d] rounded-[4px] p-2.5 flex flex-col justify-between">
          <span className="text-text-dim text-[10px] uppercase">Net Debt Position</span>
          <div className={`font-bold text-[14px] mt-1 ${netDebt < 0 ? 'text-positive' : 'text-negative'}`}>
            {netDebt < 0 ? `+${currencySym}${fmtNum(Math.abs(netDebt))}` : `-${currencySym}${fmtNum(netDebt)}`}
          </div>
          <div className="text-[10px] text-text-dim mt-0.5">
            {netDebt < 0 ? 'Net Cash Balance' : 'Net Debt Obligations'}
          </div>
        </div>
      </div>
    </div>
  )
}
