'use client'

import React from 'react'
import { Modal } from './Modal'
import { Info, CheckCircle2, ShieldCheck, Scale } from 'lucide-react'
import { ModelSpecification, ScenarioLabel } from '@/lib/types'
import { fmtNum, fmtPct, getCurrencySymbol } from '@/lib/formatters'

export interface MethodologyModalProps {
  open: boolean
  onClose: () => void
  spec: ModelSpecification | null
  scenario: ScenarioLabel
}

export function MethodologyModal({
  open,
  onClose,
  spec,
  scenario,
}: MethodologyModalProps) {
  const valuation =
    spec?.valuation?.find((v) => v.scenario === scenario) || spec?.valuation?.[0]
  const currency = spec?.metadata?.currency || 'INR'
  const currencySym = getCurrencySymbol(currency)

  const bridge = valuation?.dcf_bridge
  const waccObj = valuation?.wacc
  const impliedPrice = bridge?.implied_share_price ?? null
  const waccVal = waccObj?.wacc ?? 12.42

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Valuation Methodology & Model Transparency"
      maxWidth="max-w-2xl"
    >
      <div className="space-y-4 text-sans text-[12px]">
        {/* Banner Explanation */}
        <div className="bg-[#0ea5e9]/10 border border-[#0ea5e9]/30 rounded-[4px] p-3.5 flex items-start space-x-3">
          <ShieldCheck className="w-5 h-5 text-[#0ea5e9] shrink-0 mt-0.5" />
          <div className="space-y-1">
            <h4 className="font-bold text-[#7dd3fc] text-[13px]">
              Institutional FCFF Model (Wall Street Standard)
            </h4>
            <p className="text-[#94a3b8] leading-relaxed text-[11.5px]">
              Valence uses <strong className="text-[#f8fafc]">Unlevered Free Cash Flow to Firm (FCFF)</strong> discounted at the <strong className="text-[#f8fafc]">Weighted Average Cost of Capital (WACC)</strong>. Retail platforms (like AlphaSpread) often use simplified Net Income / FCFE models discounted at Cost of Equity ($K_e$), which omit CapEx and Working Capital reinvestment drag.
            </p>
          </div>
        </div>

        {/* Side-by-Side Comparison Table */}
        <div className="border border-[#1e283d] rounded-[4px] overflow-hidden">
          <table className="w-full text-left text-[11px] border-collapse font-mono">
            <thead>
              <tr className="bg-[#0d1220] border-b border-[#1e283d] text-[#94a3b8]">
                <th className="p-2.5 font-semibold">Valuation Factor</th>
                <th className="p-2.5 font-bold text-[#0ea5e9] bg-[#0ea5e9]/5 border-r border-[#1e283d] w-5/12">
                  Valence (Institutional FCFF)
                </th>
                <th className="p-2.5 font-semibold text-[#94a3b8] w-5/12">
                  Retail Models (AlphaSpread Net Income)
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1e283d]/60">
              <tr>
                <td className="p-2.5 font-semibold text-[#f8fafc]">Cash Flow Base</td>
                <td className="p-2.5 bg-[#0ea5e9]/5 border-r border-[#1e283d] text-[#7dd3fc]">
                  <strong>FCFF</strong> (NOPAT + D&A − CapEx − ΔNWC)
                </td>
                <td className="p-2.5 text-[#94a3b8]">
                  Net Income or Unadjusted FCFE
                </td>
              </tr>

              <tr>
                <td className="p-2.5 font-semibold text-[#f8fafc]">Discount Rate</td>
                <td className="p-2.5 bg-[#0ea5e9]/5 border-r border-[#1e283d] text-[#7dd3fc]">
                  <strong>WACC ({fmtPct(waccVal, 2)})</strong> (Equity + Debt Capital Cost)
                </td>
                <td className="p-2.5 text-[#94a3b8]">
                  Cost of Equity ($K_e \approx 10.9\%$)
                </td>
              </tr>

              <tr>
                <td className="p-2.5 font-semibold text-[#f8fafc]">Reinvestment Drag</td>
                <td className="p-2.5 bg-[#0ea5e9]/5 border-r border-[#1e283d] text-[#7dd3fc]">
                  Explicit CapEx & Working Capital deducted
                </td>
                <td className="p-2.5 text-[#94a3b8]">
                  Omitted or zero reinvestment assumed
                </td>
              </tr>

              <tr>
                <td className="p-2.5 font-semibold text-[#f8fafc]">Capital Structure</td>
                <td className="p-2.5 bg-[#0ea5e9]/5 border-r border-[#1e283d] text-[#7dd3fc]">
                  Enterprise Value $\rightarrow$ Net Cash/Debt $\rightarrow$ Equity Value
                </td>
                <td className="p-2.5 text-[#94a3b8]">
                  Direct Equity Value shortcut
                </td>
              </tr>

              <tr className="bg-[#0d1220]">
                <td className="p-2.5 font-bold text-[#f8fafc]">Model Valuation Output</td>
                <td className="p-2.5 bg-[#0ea5e9]/10 border-r border-[#0ea5e9]/30 font-bold text-[#7dd3fc]">
                  {impliedPrice != null ? `${currencySym}${fmtNum(impliedPrice, 2)}` : '—'} / share
                </td>
                <td className="p-2.5 text-[#94a3b8] font-semibold">
                  Typically higher (ignores CapEx drag)
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Why FCFF Matters */}
        <div className="bg-[#111622] border border-[#1e283d] rounded-[4px] p-3 space-y-2">
          <div className="flex items-center space-x-2 text-[#f8fafc] font-semibold text-[12px]">
            <Scale className="w-4 h-4 text-[#0ea5e9]" />
            <span>Why Institutional Investors Use FCFF</span>
          </div>
          <p className="text-[#94a3b8] text-[11px] leading-relaxed">
            Net income does not represent cash available to investors because companies must spend real cash on Capital Expenditures (CapEx) to maintain growth and tie up capital in inventory and receivables (ΔNWC). Valence deducts these real cash drags, preventing false over-optimism.
          </p>
        </div>

        {/* Modal Footer */}
        <div className="flex justify-end pt-1">
          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-[#0ea5e9] hover:bg-[#38bdf8] text-white text-[12px] font-semibold rounded-[4px] transition-colors cursor-pointer"
          >
            Got it
          </button>
        </div>
      </div>
    </Modal>
  )
}
