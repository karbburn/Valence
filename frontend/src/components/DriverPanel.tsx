'use client'

import React from 'react'
import { Sliders, RotateCcw } from 'lucide-react'
import { ModelSpecification, ScenarioLabel } from '@/lib/types'
import { DriverSlider } from './DriverSlider'

export interface DriverConfig {
  key: string
  label: string
  unit: '%' | 'days' | 'x'
  min: number
  max: number
  step: number
}

export const DRIVER_CONFIGS: DriverConfig[] = [
  { key: 'revenue_growth', label: 'Revenue Growth %', unit: '%', min: -5, max: 30, step: 0.5 },
  { key: 'ebitda_margin', label: 'EBITDA Margin %', unit: '%', min: 5, max: 45, step: 0.5 },
  { key: 'ebit_margin', label: 'EBIT / Operating Margin %', unit: '%', min: 5, max: 40, step: 0.5 },
  { key: 'da_pct_revenue', label: 'D&A % Revenue', unit: '%', min: 0.5, max: 15, step: 0.1 },
  { key: 'tax_rate', label: 'Effective Tax Rate %', unit: '%', min: 10, max: 40, step: 0.5 },
  { key: 'capex_pct_revenue', label: 'CapEx % Revenue', unit: '%', min: 0.5, max: 20, step: 0.1 },
  { key: 'dso_days', label: 'DSO (Days Receivable)', unit: 'days', min: 20, max: 200, step: 1 },
  { key: 'dpo_days', label: 'DPO (Days Payable)', unit: 'days', min: 5, max: 90, step: 1 },
  { key: 'wacc.cost_of_equity', label: 'Cost of Equity (CAPM) %', unit: '%', min: 6, max: 22, step: 0.25 },
  { key: 'terminal_growth_rate', label: 'Terminal Growth Rate %', unit: '%', min: 0.5, max: 7, step: 0.25 },
  { key: 'exit_ev_multiple', label: 'Exit EV/EBITDA Multiple', unit: 'x', min: 5, max: 45, step: 0.5 },
]

export interface DriverPanelProps {
  spec: ModelSpecification | null
  scenario: ScenarioLabel
  onDriverChange: (driverKey: string, value: number) => void
  onDriverRevert: (driverKey: string, period?: string) => void
  onResetAll?: () => void
}

export function DriverPanel({
  spec,
  scenario,
  onDriverChange,
  onDriverRevert,
  onResetAll,
}: DriverPanelProps) {
  const assumptions = spec?.assumptions || []
  const scenarioAssumptions = assumptions.filter((a) => a.scenario === scenario)
  const hasOverrides = scenarioAssumptions.some((a) => a.type === 'user_override')

  const handleResetAll = () => {
    if (onResetAll) {
      onResetAll()
    } else {
      scenarioAssumptions
        .filter((a) => a.type === 'user_override')
        .forEach((a) => onDriverRevert(a.driver_key, a.period || 'FY27'))
    }
  }

  return (
    <div className="bg-surface border border-[#1e283d] rounded-[4px] p-3.5 flex flex-col shadow-sm select-none">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#1e283d] pb-2.5 mb-2.5">
        <div className="flex items-center space-x-2">
          <Sliders className="w-4 h-4 text-[#0ea5e9]" />
          <h2 className="font-bold text-[15px] text-text-main">
            Valuation Drivers
          </h2>
        </div>
        <div className="flex items-center space-x-2">
          {hasOverrides && (
            <button
              onClick={handleResetAll}
              title="Reset all driver overrides to baseline defaults"
              className="flex items-center space-x-1 text-[10.5px] font-semibold text-[#f43f5e] bg-[#f43f5e]/10 border border-[#f43f5e]/30 hover:bg-[#f43f5e]/20 rounded-[3px] px-2 py-0.5 transition-colors cursor-pointer"
            >
              <RotateCcw className="w-3 h-3" />
              <span>Reset All</span>
            </button>
          )}
          <span className="font-mono text-[10px] text-[#7dd3fc] bg-[#0ea5e9]/10 border border-[#0ea5e9]/20 rounded-[3px] px-2 py-0.5 uppercase">
            {scenario} Scenario
          </span>
        </div>
      </div>

      {/* Driver List */}
      <div className="space-y-2 max-h-[calc(100vh-340px)] overflow-y-auto pr-1">
        {DRIVER_CONFIGS.map((cfg) => {
          const matched = scenarioAssumptions.find(
            (a) => a.driver_key === cfg.key && (a.period === 'FY27' || a.period === 'all')
          )
          const val = matched?.value ?? 0
          const isOverride = matched?.type === 'user_override'

          return (
            <DriverSlider
              key={cfg.key}
              driverKey={cfg.key}
              label={cfg.label}
              value={val}
              unit={cfg.unit}
              min={cfg.min}
              max={cfg.max}
              step={cfg.step}
              isOverride={isOverride}
              onChange={onDriverChange}
              onRevert={(key) => onDriverRevert(key, matched?.period || 'FY27')}
            />
          )
        })}
      </div>
    </div>
  )
}
