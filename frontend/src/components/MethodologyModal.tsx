'use client'

import React from 'react'
import { Modal } from './Modal'
import { ShieldCheck, Scale } from 'lucide-react'
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
      <div className="space-y-4 text-sans text-[12.5px]">
        {/* Banner Explanation */}
        <div className="bg-accent-subtle border border-accent-border rounded-sm p-3.5 flex items-start space-x-3">
          <ShieldCheck className="w-5 h-5 text-accent shrink-0 mt-0.5" aria-hidden />
          <div className="space-y-1">
            <h4 className="font-bold text-accent-hover text-[13.5px]">
              Unlevered Free Cash Flow (FCFF) Model
            </h4>
            <p className="text-[#cbd5e1] leading-relaxed">
              Valence calculates intrinsic value using <strong className="text-text-main">Unlevered Free Cash Flow to Firm (FCFF)</strong> discounted at the <strong className="text-text-main">Weighted Average Cost of Capital (WACC)</strong>. Simplified Net Income or FCFE models often omit capital expenditures and working capital reinvestment drag.
            </p>
          </div>
        </div>

        {/* Side-by-Side Comparison Table */}
        <div className="border border-border rounded-sm overflow-hidden">
          <table className="w-full text-left text-[12px] border-collapse font-mono">
            <caption className="sr-only">
              How the Valence FCFF model compares with simplified net income or FCFE approaches
            </caption>
            <thead>
              <tr className="bg-surface-3 border-b border-border text-text-muted">
                <th scope="col" className="p-2.5 font-semibold">Valuation Factor</th>
                <th scope="col" className="p-2.5 font-bold text-accent-hover bg-accent-subtle border-r border-b border-accent-border w-5/12">
                  Valence FCFF Model
                </th>
                <th scope="col" className="p-2.5 font-semibold text-text-muted w-5/12">
                  Net Income / FCFE Models
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              <tr>
                <th scope="row" className="p-2.5 font-semibold text-text-main align-top text-left font-sans">Cash Flow Base</th>
                <td className="p-2.5 border-l-2 border-l-accent/60 border-r border-border text-text-main">
                  <strong>FCFF</strong> (NOPAT + D&A − CapEx − ΔNWC)
                </td>
                <td className="p-2.5 text-[#cbd5e1]">
                  Net Income or Unadjusted FCFE
                </td>
              </tr>

              <tr>
                <td className="p-2.5 font-semibold text-text-main align-top">Discount Rate</th>
                <td className="p-2.5 border-l-2 border-l-accent/60 border-r border-border text-text-main">
                  <strong>WACC ({fmtPct(waccVal, 2)})</strong> (Equity + Debt Capital Cost)
                </td>
                <td className="p-2.5 text-[#cbd5e1]">
                  Cost of Equity ≈ {fmtPct(waccVal, 1)} (live)
                </td>
              </tr>

              <tr>
                <td className="p-2.5 font-semibold text-text-main align-top">Reinvestment Drag</th>
                <td className="p-2.5 border-l-2 border-l-accent/60 border-r border-border text-text-main">
                  Explicit CapEx & Working Capital deducted
                </td>
                <td className="p-2.5 text-[#cbd5e1]">
                  Omitted or unconstrained
                </td>
              </tr>

              <tr>
                <td className="p-2.5 font-semibold text-text-main align-top">Capital Structure</th>
                <td className="p-2.5 border-l-2 border-l-accent/60 border-r border-border text-text-main">
                  Enterprise Value → Net Cash/Debt → Equity Value
                </td>
                <td className="p-2.5 text-[#cbd5e1]">
                  Direct Equity Value shortcut
                </td>
              </tr>

              <tr className="bg-surface-3">
                <td className="p-2.5 font-bold text-text-main">Model Valuation Output</td>
                <td className="p-2.5 bg-accent-subtle border-l-2 border-l-accent border-r border-accent-border font-bold text-accent-hover text-[13px]">
                  {impliedPrice != null ? `${currencySym}${fmtNum(impliedPrice, 2)}` : '—'} / share
                </td>
                <td className="p-2.5 text-[#cbd5e1] font-semibold">
                  Differs based on cash flow definitions
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Why FCFF Matters */}
        <div className="bg-surface border border-border rounded-sm p-3 space-y-2">
          <div className="flex items-center space-x-2 text-text-main font-semibold text-[13px]">
            <Scale className="w-4 h-4 text-accent shrink-0" aria-hidden />
            <span>Why FCFF Cash Flow Accounting is Used</span>
          </div>
          <p className="text-[#cbd5e1] leading-relaxed">
            Net income does not represent total cash available to investors because companies must spend real cash on Capital Expenditures (CapEx) to maintain operations and tie up capital in inventory and receivables (ΔNWC). FCFF accounts for these reinvestment requirements.
          </p>
          <p className="text-[#cbd5e1] leading-relaxed">
            Stock-based compensation is deducted from FCFF as a real economic cost. Although non-cash under accounting rules, it transfers value to employees and dilutes shareholders, so treating it as free cash would overstate intrinsic value.
          </p>
        </div>

        {/* Modal Footer */}
        <div className="flex justify-end pt-1">
          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-accent hover:bg-accent-hover text-white text-[12px] font-semibold rounded-sm transition-colors cursor-pointer"
          >
            Close
          </button>
        </div>
      </div>
    </Modal>
  )
}
