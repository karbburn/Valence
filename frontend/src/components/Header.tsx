'use client'

import React from 'react'
import { Search, Save, Bookmark, FileSpreadsheet, CheckCircle2, AlertTriangle } from 'lucide-react'
import { ModelSpecification, ScenarioLabel } from '@/lib/types'

export interface HeaderProps {
  spec: ModelSpecification | null
  mode: 'analyst' | 'quick' | 'full'
  scenario: ScenarioLabel
  companyId: string
  onModeChange: (mode: 'analyst' | 'quick' | 'full') => void
  onScenarioChange: (scenario: ScenarioLabel) => void
  onCompanyChange?: (companyId: string) => void
  onSave?: () => void
  onOpenSaved?: () => void
  onOpenQA?: () => void
  onExportExcel?: () => void
  searchQuery?: string
  onSearchChange?: (query: string) => void
}

export function Header({
  spec,
  mode,
  scenario,
  onModeChange,
  onScenarioChange,
  onSave,
  onOpenSaved,
  onOpenQA,
  onExportExcel,
  searchQuery = '',
  onSearchChange,
}: HeaderProps) {
  const metadata = spec?.metadata
  const qaChecks = spec?.qa?.checks || []
  const failedChecks = qaChecks.filter((c) => !c.passed)
  const qaStatus =
    qaChecks.length === 0
      ? 'not_run'
      : failedChecks.length === 0
      ? 'passed'
      : 'failed'

  return (
    <header className="sticky top-0 z-40 h-[48px] w-full bg-[#111622]/95 backdrop-blur-md border-b border-[#1e283d] px-5 flex items-center justify-between text-sans select-none">
      {/* Left section: Logo, Search, Company Badge */}
      <div className="flex items-center space-x-4">
        {/* Brand Logo */}
        <div className="flex items-center space-x-2.5">
          <div className="w-[30px] h-[30px] bg-white rounded-[4px] p-[3px] flex items-center justify-center shadow-sm">
            <div className="w-full h-full bg-[#080c14] rounded-[2px] border border-[#1e283d] flex items-center justify-center">
              <div className="w-2 h-2 bg-[#0ea5e9] rounded-full" />
            </div>
          </div>
          <span className="font-bold text-[18px] tracking-[0.05em] text-[#f8fafc]">
            VALENCE
          </span>
        </div>

        {/* Company Search Input */}
        <div className="relative w-64">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#64748b]" />
          <input
            type="text"
            placeholder="Search ticker or company..."
            value={searchQuery}
            onChange={(e) => onSearchChange?.(e.target.value)}
            className="w-full h-8 bg-[#0d1220] border border-[#2a3652] rounded-[4px] pl-8 pr-3 text-[12px] text-[#f8fafc] placeholder-[#475569] focus:outline-none focus:border-[#0ea5e9] focus:ring-1 focus:ring-[#0ea5e9]/30 transition-colors"
          />
        </div>

        {/* Active Company Badge */}
        {metadata && (
          <div className="flex items-center space-x-2 bg-[#0d1220] border border-[#1e283d] rounded-[4px] px-2.5 py-1">
            <span className="font-bold text-[11px] uppercase tracking-[0.04em] text-[#f8fafc]">
              {metadata.name}
            </span>
            <span className="font-mono font-bold text-[10px] text-[#7dd3fc] bg-[#0ea5e9]/10 border border-[#0ea5e9]/20 rounded-[3px] px-1.5 py-0.5">
              {metadata.ticker}
            </span>
          </div>
        )}
      </div>

      {/* Center section: Mode Tabs */}
      <div className="flex items-center bg-[#111622] border border-[#1e283d] rounded-[6px] p-1 space-x-1">
        <button
          onClick={() => onModeChange('analyst')}
          className={`px-3 py-1 text-[12px] font-medium rounded-[4px] transition-colors ${
            mode === 'analyst'
              ? 'bg-[#0ea5e9] text-white font-semibold shadow-sm'
              : 'text-[#64748b] hover:text-[#f8fafc]'
          }`}
        >
          Analyst Mode
        </button>
        <button
          onClick={() => onModeChange('quick')}
          className={`px-3 py-1 text-[12px] font-medium rounded-[4px] transition-colors ${
            mode === 'quick'
              ? 'bg-[#0ea5e9] text-white font-semibold shadow-sm'
              : 'text-[#64748b] hover:text-[#f8fafc]'
          }`}
        >
          Quick DCF
        </button>
        <button
          onClick={() => onModeChange('full')}
          className={`px-3 py-1 text-[12px] font-medium rounded-[4px] transition-colors ${
            mode === 'full'
              ? 'bg-[#0ea5e9] text-white font-semibold shadow-sm'
              : 'text-[#64748b] hover:text-[#f8fafc]'
          }`}
        >
          3-Statement
        </button>
      </div>

      {/* Right section: Scenario Toggle, QA Badge, Action Buttons */}
      <div className="flex items-center space-x-3">
        {/* Scenario Control */}
        <div className="flex items-center bg-[#111622] border border-[#1e283d] rounded-[6px] p-0.5 space-x-0.5">
          {(['base', 'bull', 'bear'] as ScenarioLabel[]).map((sc) => (
            <button
              key={sc}
              onClick={() => onScenarioChange(sc)}
              className={`px-2.5 py-0.5 text-[11px] font-medium capitalize rounded-[4px] transition-colors ${
                scenario === sc
                  ? 'bg-[#2a3652] text-[#f8fafc] font-bold'
                  : 'text-[#64748b] hover:text-[#94a3b8]'
              }`}
            >
              {sc}
            </button>
          ))}
        </div>

        {/* QA Status Badge */}
        <button
          onClick={onOpenQA}
          className={`flex items-center space-x-1.5 px-2.5 py-1 rounded-full text-[9px] font-bold tracking-[0.04em] uppercase border transition-colors ${
            qaStatus === 'passed'
              ? 'bg-[#10b981]/10 text-[#10b981] border-[#10b981]/30 hover:bg-[#10b981]/20'
              : qaStatus === 'failed'
              ? 'bg-[#ef4444]/10 text-[#ef4444] border-[#ef4444]/30 animate-pulse hover:bg-[#ef4444]/20'
              : 'bg-[#192030] text-[#64748b] border-[#1e283d] hover:text-[#94a3b8]'
          }`}
        >
          {qaStatus === 'passed' ? (
            <>
              <CheckCircle2 className="w-3 h-3 text-[#10b981]" />
              <span>MODEL VALID</span>
            </>
          ) : qaStatus === 'failed' ? (
            <>
              <AlertTriangle className="w-3 h-3 text-[#ef4444]" />
              <span>{failedChecks.length} CHECKS FAILED</span>
            </>
          ) : (
            <span>QA NOT RUN</span>
          )}
        </button>

        {/* Action Buttons */}
        <div className="flex items-center space-x-1.5">
          <button
            onClick={onSave}
            className="flex items-center space-x-1 px-3 py-1 bg-[#0ea5e9] hover:bg-[#38bdf8] text-white text-[12px] font-semibold rounded-[4px] transition-colors"
          >
            <Save className="w-3.5 h-3.5" />
            <span>Save</span>
          </button>

          <button
            onClick={onOpenSaved}
            className="flex items-center space-x-1 px-2.5 py-1 bg-[#192030] hover:bg-[#2a3652] text-[#94a3b8] hover:text-[#f8fafc] border border-[#1e283d] text-[12px] font-semibold rounded-[4px] transition-colors"
          >
            <Bookmark className="w-3.5 h-3.5" />
            <span>Saved</span>
          </button>

          <button
            onClick={onExportExcel}
            className="flex items-center space-x-1 px-2.5 py-1 bg-[#065f46] hover:bg-[#047857] text-[#6ee7b7] border border-[#047857] text-[12px] font-semibold rounded-[4px] transition-colors"
          >
            <FileSpreadsheet className="w-3.5 h-3.5" />
            <span>Excel</span>
          </button>
        </div>
      </div>
    </header>
  )
}
