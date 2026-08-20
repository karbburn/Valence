'use client'

import React from 'react'
import { Save, Bookmark, FileSpreadsheet, CheckCircle2, AlertTriangle, Copy } from 'lucide-react'
import { ModelSpecification, ScenarioLabel, CompanySummary } from '@/lib/types'
import { CompanySearch } from './CompanySearch'

export interface HeaderProps {
  spec: ModelSpecification | null
  mode: 'analyst' | 'quick' | 'full'
  scenario: ScenarioLabel
  companyId: string
  onModeChange: (mode: 'analyst' | 'quick' | 'full') => void
  onScenarioChange: (scenario: ScenarioLabel) => void
  onSelectCompany: (company: CompanySummary) => void
  onSave?: () => void
  onOpenSaved?: () => void
  onOpenQA?: () => void
  onExportExcel?: () => void
  onCopySummary?: () => void
}

export function Header({
  spec,
  mode,
  scenario,
  onModeChange,
  onScenarioChange,
  onSelectCompany,
  onSave,
  onOpenSaved,
  onOpenQA,
  onExportExcel,
  onCopySummary,
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
    <header className="sticky top-0 z-40 h-[48px] w-full bg-[#111622]/95 backdrop-blur-md border-b border-[#1e283d] px-2.5 sm:px-3 md:px-4 flex items-center justify-between text-sans select-none gap-2 md:gap-3 overflow-visible">
      {/* Left section: Logo, Search, Company Badge */}
      <div className="flex items-center space-x-2 sm:space-x-3 shrink-0">
        {/* Brand Logo */}
        <div className="flex items-center space-x-1.5 sm:space-x-2 shrink-0">
          <div className="h-8 px-1.5 bg-white rounded-[4px] flex items-center justify-center shadow-sm overflow-hidden border border-white/20">
            <img
              src="/logo.png"
              alt="Valence Logo"
              className="h-6 w-auto object-contain"
            />
          </div>
          <span className="font-bold text-[16px] sm:text-[17px] tracking-[0.05em] text-[#f8fafc]">
            VALENCE
          </span>
        </div>

        {/* Company Search Component */}
        <CompanySearch onSelectCompany={onSelectCompany} />

        {/* Active Company Badge */}
        {metadata && (
          <div className="hidden lg:flex items-center space-x-1.5 bg-[#0d1220] border border-[#1e283d] rounded-[4px] px-2 py-1 max-w-[150px] lg:max-w-[190px]">
            <span className="font-bold text-[10.5px] uppercase tracking-[0.03em] text-[#f8fafc] truncate">
              {metadata.name}
            </span>
            <span className="font-mono font-bold text-[9.5px] text-[#7dd3fc] bg-[#0ea5e9]/10 border border-[#0ea5e9]/20 rounded-[3px] px-1 py-0.5 shrink-0">
              {metadata.ticker}
            </span>
          </div>
        )}
      </div>

      {/* Center section: Mode Tabs */}
      <div
        role="tablist"
        aria-label="View Mode Navigation"
        className="flex items-center bg-[#111622] border border-[#1e283d] rounded-[6px] p-0.5 space-x-0.5 shrink-0"
      >
        <button
          role="tab"
          aria-selected={mode === 'analyst'}
          onClick={() => onModeChange('analyst')}
          className={`px-2.5 sm:px-3 py-1 text-[11px] sm:text-[12px] font-medium rounded-[4px] whitespace-nowrap transition-colors ${
            mode === 'analyst'
              ? 'bg-[#0ea5e9] text-white font-semibold shadow-sm'
              : 'text-[#64748b] hover:text-[#f8fafc]'
          }`}
        >
          Analyst Mode
        </button>
        <button
          role="tab"
          aria-selected={mode === 'quick'}
          onClick={() => onModeChange('quick')}
          className={`px-2.5 sm:px-3 py-1 text-[11px] sm:text-[12px] font-medium rounded-[4px] whitespace-nowrap transition-colors ${
            mode === 'quick'
              ? 'bg-[#0ea5e9] text-white font-semibold shadow-sm'
              : 'text-[#64748b] hover:text-[#f8fafc]'
          }`}
        >
          Quick DCF
        </button>
        <button
          role="tab"
          aria-selected={mode === 'full'}
          onClick={() => onModeChange('full')}
          className={`px-2.5 sm:px-3 py-1 text-[11px] sm:text-[12px] font-medium rounded-[4px] whitespace-nowrap transition-colors ${
            mode === 'full'
              ? 'bg-[#0ea5e9] text-white font-semibold shadow-sm'
              : 'text-[#64748b] hover:text-[#f8fafc]'
          }`}
        >
          3-Statement
        </button>
      </div>

      {/* Right section: Scenario Toggle, QA Badge, Action Buttons */}
      <div className="flex items-center space-x-1.5 sm:space-x-2 shrink-0 pr-1">
        {/* Scenario Control */}
        <div
          role="tablist"
          aria-label="Valuation Scenario"
          className="flex items-center bg-[#111622] border border-[#1e283d] rounded-[6px] p-0.5 space-x-0.5 shrink-0"
        >
          {(['base', 'bull', 'bear'] as ScenarioLabel[]).map((sc) => (
            <button
              key={sc}
              role="tab"
              aria-selected={scenario === sc}
              onClick={() => onScenarioChange(sc)}
              className={`px-2 py-0.5 text-[10.5px] sm:text-[11px] font-medium capitalize rounded-[4px] whitespace-nowrap transition-colors ${
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
          className={`flex items-center space-x-1 px-2 py-1 rounded-[4px] text-[9px] sm:text-[9.5px] font-bold tracking-[0.03em] uppercase border whitespace-nowrap shrink-0 transition-colors ${
            qaStatus === 'passed'
              ? 'bg-[#10b981]/10 text-[#10b981] border-[#10b981]/30 hover:bg-[#10b981]/20'
              : qaStatus === 'failed'
              ? 'bg-[#ef4444]/10 text-[#ef4444] border-[#ef4444]/30 animate-pulse hover:bg-[#ef4444]/20'
              : 'bg-[#192030] text-[#64748b] border-[#1e283d] hover:text-[#94a3b8]'
          }`}
        >
          {qaStatus === 'passed' ? (
            <>
              <CheckCircle2 className="w-3 h-3 text-[#10b981] shrink-0" />
              <span>MODEL VALID</span>
            </>
          ) : qaStatus === 'failed' ? (
            <>
              <AlertTriangle className="w-3 h-3 text-[#ef4444] shrink-0" />
              <span>
                {failedChecks.length} {failedChecks.length === 1 ? 'CHECK' : 'CHECKS'} FAILED
              </span>
            </>
          ) : (
            <span>QA NOT RUN</span>
          )}
        </button>

        {/* Action Buttons */}
        <div className="flex items-center space-x-1 sm:space-x-1.5 shrink-0">
          <button
            onClick={onCopySummary}
            title="Copy valuation memo summary to clipboard"
            className="flex items-center space-x-1 px-2 py-1 bg-[#192030] hover:bg-[#2a3652] text-[#7dd3fc] border border-[#0ea5e9]/30 text-[11px] font-semibold rounded-[4px] transition-colors cursor-pointer shrink-0"
          >
            <Copy className="w-3.5 h-3.5 shrink-0" />
            <span>Copy</span>
          </button>

          <button
            onClick={onSave}
            className="flex items-center space-x-1 px-2 py-1 bg-[#0ea5e9] hover:bg-[#38bdf8] text-white text-[11px] font-semibold rounded-[4px] transition-colors cursor-pointer shrink-0"
          >
            <Save className="w-3.5 h-3.5 shrink-0" />
            <span>Save</span>
          </button>

          <button
            onClick={onOpenSaved}
            className="flex items-center space-x-1 px-2 py-1 bg-[#192030] hover:bg-[#2a3652] text-[#94a3b8] hover:text-[#f8fafc] border border-[#1e283d] text-[11px] font-semibold rounded-[4px] transition-colors cursor-pointer shrink-0"
          >
            <Bookmark className="w-3.5 h-3.5 shrink-0" />
            <span>Saved</span>
          </button>

          <button
            onClick={onExportExcel}
            className="flex items-center space-x-1 px-2.5 py-1 bg-[#065f46] hover:bg-[#047857] text-[#6ee7b7] border border-[#047857] text-[11.5px] font-bold rounded-[4px] transition-colors cursor-pointer shrink-0 shadow-sm"
          >
            <FileSpreadsheet className="w-3.5 h-3.5 shrink-0" />
            <span>Excel</span>
          </button>
        </div>
      </div>
    </header>
  )
}
