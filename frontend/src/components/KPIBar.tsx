'use client'

import React from 'react'
import { ModelSpecification, ScenarioLabel } from '@/lib/types'
import { fmtMoney, fmtPct, fmtPrice } from '@/lib/formatters'

export interface KPIBarProps {
  spec: ModelSpecification | null
  scenario: ScenarioLabel
}

export function KPIBar({ spec, scenario }: KPIBarProps) {
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
  const marketPrice = reverseDcf?.market_price ?? null

  let upsidePct: number | null = null
  if (impliedPrice != null && marketPrice != null && marketPrice > 0) {
    upsidePct = ((impliedPrice - marketPrice) / marketPrice) * 100
  }

  const ev = bridge?.enterprise_value ?? null
  const equityVal = bridge?.equity_value ?? null
  const waccVal = waccObj?.wacc ?? null
  const terminalGrowthVal = tvObj?.terminal_growth_rate ?? null

  return (
    <div className="w-full bg-[#111622]/40 border-b border-[#1e283d] px-[14px] py-[8px]">
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2.5">
        {/* KPI 1: DCF Implied Price (Primary KPI) */}
        <div className="bg-[#111622] border border-[#0ea5e9]/40 rounded-[4px] px-3 py-2 flex flex-col justify-between shadow-sm">
          <span className="font-semibold text-[10.5px] uppercase tracking-[0.04em] text-[#94a3b8] whitespace-nowrap">
            DCF Implied Price
          </span>
          <div className="font-mono font-bold text-[16px] text-[#7dd3fc] mt-0.5 whitespace-nowrap">
            {impliedPrice != null ? fmtPrice(impliedPrice, currency, 2) : '—'}
          </div>
          <div className="text-[10px] font-semibold mt-0.5 whitespace-nowrap">
            {upsidePct != null ? (
              <span className={upsidePct >= 0 ? 'text-[#10b981]' : 'text-[#ef4444]'}>
                {upsidePct >= 0 ? '+' : ''}
                {fmtPct(upsidePct, 1)} vs mkt
              </span>
            ) : (
              <span className="text-[#64748b]">Intrinsic Value</span>
            )}
          </div>
        </div>

        {/* KPI 2: Market Price */}
        <div className="bg-[#111622] border border-[#1e283d] rounded-[4px] px-3 py-2 flex flex-col justify-between">
          <span className="font-semibold text-[10.5px] uppercase tracking-[0.04em] text-[#94a3b8] whitespace-nowrap">
            Market Price
          </span>
          <div className="font-mono font-bold text-[16px] text-[#f8fafc] mt-0.5 whitespace-nowrap">
            {marketPrice != null ? fmtPrice(marketPrice, currency, 2) : '—'}
          </div>
          <div className="text-[10px] font-semibold text-[#64748b] mt-0.5 whitespace-nowrap">
            Live / Benchmark
          </div>
        </div>

        {/* KPI 3: Enterprise Value */}
        <div className="bg-[#111622] border border-[#1e283d] rounded-[4px] px-3 py-2 flex flex-col justify-between">
          <span className="font-semibold text-[10.5px] uppercase tracking-[0.04em] text-[#94a3b8] whitespace-nowrap">
            Enterprise Value
          </span>
          <div className="font-mono font-bold text-[16px] text-[#f8fafc] mt-0.5 whitespace-nowrap">
            {ev != null ? fmtMoney(ev, currency) : '—'}
          </div>
          <div className="text-[10px] font-semibold text-[#64748b] mt-0.5 whitespace-nowrap">
            PV FCFF + PV TV
          </div>
        </div>

        {/* KPI 4: Equity Value */}
        <div className="bg-[#111622] border border-[#1e283d] rounded-[4px] px-3 py-2 flex flex-col justify-between">
          <span className="font-semibold text-[10.5px] uppercase tracking-[0.04em] text-[#94a3b8] whitespace-nowrap">
            Equity Value
          </span>
          <div className="font-mono font-bold text-[16px] text-[#f8fafc] mt-0.5 whitespace-nowrap">
            {equityVal != null ? fmtMoney(equityVal, currency) : '—'}
          </div>
          <div className="text-[10px] font-semibold text-[#64748b] mt-0.5 whitespace-nowrap">
            Net Debt Adjusted
          </div>
        </div>

        {/* KPI 5: WACC */}
        <div className="bg-[#111622] border border-[#1e283d] rounded-[4px] px-3 py-2 flex flex-col justify-between">
          <span className="font-semibold text-[10.5px] uppercase tracking-[0.04em] text-[#94a3b8] whitespace-nowrap">
            WACC
          </span>
          <div className="font-mono font-bold text-[16px] text-[#f8fafc] mt-0.5 whitespace-nowrap">
            {waccVal != null ? fmtPct(waccVal, 2) : '—'}
          </div>
          <div className="text-[10px] font-semibold text-[#64748b] mt-0.5 whitespace-nowrap">
            CAPM / Capital Cost
          </div>
        </div>

        {/* KPI 6: Terminal Growth (g) */}
        <div className="bg-[#111622] border border-[#1e283d] rounded-[4px] px-3 py-2 flex flex-col justify-between">
          <span className="font-semibold text-[10.5px] uppercase tracking-[0.04em] text-[#94a3b8] whitespace-nowrap">
            Terminal Growth (g)
          </span>
          <div className="font-mono font-bold text-[16px] text-[#f8fafc] mt-0.5 whitespace-nowrap">
            {terminalGrowthVal != null ? fmtPct(terminalGrowthVal, 2) : '—'}
          </div>
          <div className="text-[10px] font-semibold text-[#64748b] mt-0.5 whitespace-nowrap">
            Gordon Growth
          </div>
        </div>
      </div>
    </div>
  )
}
