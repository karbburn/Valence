'use client'

import React, { useCallback, useEffect, useId, useRef, useState } from 'react'
import Image from 'next/image'
import Link from 'next/link'
import {
  Save,
  Bookmark,
  FileSpreadsheet,
  CheckCircle2,
  AlertTriangle,
  Copy,
  Ellipsis,
} from 'lucide-react'
import { ModelSpecification, ScenarioLabel, CompanySummary } from '@/lib/types'
import { fmtPct } from '@/lib/formatters'
import { CompanySearch } from './CompanySearch'

export interface HeaderProps {
  spec: ModelSpecification | null
  mode: 'analyst' | 'quick' | 'full'
  scenario: ScenarioLabel
  exporting?: boolean
  onModeChange: (mode: 'analyst' | 'quick' | 'full') => void
  onScenarioChange: (scenario: ScenarioLabel) => void
  onSelectCompany: (company: CompanySummary) => void
  onSave?: () => void
  onOpenSaved?: () => void
  onOpenQA?: () => void
  onExportExcel?: () => void
  onCopySummary?: () => void
}

const MODES: Array<{ id: 'analyst' | 'quick' | 'full'; label: string }> = [
  { id: 'analyst', label: 'Analyst' },
  { id: 'quick', label: 'Quick DCF' },
  { id: 'full', label: '3-Statement' },
]

const SCENARIOS: ScenarioLabel[] = ['base', 'bull', 'bear']

export function Header({
  spec,
  mode,
  scenario,
  exporting = false,
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
  const skippedChecks = qaChecks.filter(
    (c) => c.passed && c.detail.startsWith('SKIPPED:')
  )
  const qaStatus =
    qaChecks.length === 0
      ? 'not_run'
      : failedChecks.length === 0
      ? skippedChecks.length === 0
        ? 'passed'
        : 'warning'
      : 'failed'

  // Live delta per scenario vs the current market quote — glanceable without switching.
  const marketPrice =
    spec?.valuation?.find((v) => v.scenario === scenario)?.reverse_dcf?.market_price ?? null

  const scenarioDelta = (sc: ScenarioLabel): string | null => {
    const price = spec?.valuation?.find((v) => v.scenario === sc)?.dcf_bridge?.implied_share_price
    if (price == null || marketPrice == null || marketPrice <= 0) return null
    const delta = ((price - marketPrice) / marketPrice) * 100
    return `${delta >= 0 ? '+' : ''}${fmtPct(delta, 0)}`
  }

  const modeListRef = useRef<HTMLDivElement>(null)

  /* ------------------------------------------------------------------ *
   * The overflow menu.
   *
   * Measured in a browser on 2026-10-04, this header needs 1416px:
   *
   *     900px  overflows by 500   scenario chips, QA, Copy, Save, Library, Excel cut off
   *    1024px  overflows by 392   QA, Copy, Save, Library, Excel cut off
   *    1152px  overflows by 264   Copy, Save, Library, Excel cut off
   *    1280px  overflows by 136   Library and Excel cut off, Excel by 132px
   *    1366px  overflows by  50   Excel cut off
   *    1440px  fits
   *
   * So the Excel export -- the primary export, per the comment above it -- was not merely
   * off-screen at 1280px as recorded. It was unreachable at EVERY width from 900px to
   * 1439px, while MobileGuard promises the workbench works from 900px. The bar is a single
   * non-wrapping row, so the overflow lands on whichever control sits furthest right: the
   * one a reader is most likely to be reaching for.
   *
   * The four actions collapse into one menu below 1440px. 1440 is not arbitrary, it is where
   * the row first fits, measured rather than guessed, and above it nothing changes at all,
   * so every width that works today looks identical.
   *
   * Collapsing these four takes the row from 1416px to 1163px, measured, so the floor
   * becomes 1163px rather than 1416px, and 1280px -- the width the defect was recorded
   * against -- goes from 136px short to 117px clear. Reaching 900px as well would need the
   * view tabs and scenario chips collapsed too, which removes functionality rather than
   * relocating it -- so MobileGuard's stated minimum is corrected to 1163px in the same
   * change. That correction is the point: a guard promising a width the layout cannot honour
   * is the same defect as the off-screen button, one layer up.
   *
   * 1163 is where the row fits EXACTLY: at 1162px it overflows by 1px, and at 1163px by
   * nothing. Pinning that down took a per-pixel sweep, because reading a stretched viewport's
   * width as the row's intrinsic requirement gives the wrong answer by 79px -- which is what
   * an earlier draft of this comment did, and it would have needlessly hidden the workbench
   * across widths that work.
   * ------------------------------------------------------------------ */
  const [actionsOpen, setActionsOpen] = useState(false)
  const actionsRef = useRef<HTMLDivElement>(null)
  const actionsButtonRef = useRef<HTMLButtonElement>(null)
  const actionsMenuId = useId()
  const closeActions = useCallback(() => setActionsOpen(false), [])

  useEffect(() => {
    if (!actionsOpen) return
    const onPointerDown = (e: PointerEvent) => {
      if (!actionsRef.current?.contains(e.target as Node)) setActionsOpen(false)
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setActionsOpen(false)
      // Focus returns to the control that opened the menu. Without this, Escape leaves focus
      // on <body> and a keyboard user has to Tab from the top of the document to find where
      // they were.
      actionsButtonRef.current?.focus()
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [actionsOpen])

  /** Each entry runs its action and closes, so the menu never hangs open behind a modal. */
  const runAction = (fn?: () => void) => {
    closeActions()
    fn?.()
  }

  const ACTION_ITEMS = [
    {
      key: 'copy',
      label: 'Copy memo',
      hint: 'Copy valuation memo to clipboard',
      Icon: Copy,
      disabled: false,
      run: () => runAction(onCopySummary),
    },
    {
      key: 'save',
      label: 'Save',
      hint: undefined,
      Icon: Save,
      disabled: false,
      run: () => runAction(onSave),
    },
    {
      key: 'library',
      label: 'Library',
      hint: 'Open model library (saved models)',
      Icon: Bookmark,
      disabled: false,
      run: () => runAction(onOpenSaved),
    },
    {
      key: 'excel',
      label: exporting ? 'Exporting…' : 'Excel',
      hint: 'Export the model to a workbook',
      Icon: FileSpreadsheet,
      disabled: Boolean(exporting),
      run: () => runAction(onExportExcel),
    },
  ]

  // Roving-tabindex tab pattern: arrows move focus and selection inside the list.
  const handleModeKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    e.preventDefault()
    e.stopPropagation()
    const idx = MODES.findIndex((m) => m.id === mode)
    const next =
      MODES[(idx + (e.key === 'ArrowRight' ? 1 : MODES.length - 1)) % MODES.length].id
    onModeChange(next)
    requestAnimationFrame(() => {
      modeListRef.current
        ?.querySelector<HTMLButtonElement>(`#tab-${next}`)
        ?.focus()
    })
  }

  return (
    <header className="sticky top-0 z-40 h-[48px] w-full bg-surface/95 backdrop-blur-md border-b border-border px-2.5 sm:px-3 md:px-4 flex items-center justify-between text-sans select-none gap-2 md:gap-3 overflow-visible">
      {/* Left section: Logo, Search, Company Badge */}
      <div className="flex items-center space-x-2 sm:space-x-3 shrink-0">
        {/* The wordmark is the way out of the workbench. These pages are the
            indexable surface, so most visitors arrive here from a search result
            with no site navigation above them, and without this the deep link is
            a dead end: nothing on the page reached the homepage, the ticker
            index, or the methodology. */}
        <Link
          href="/"
          className="flex items-center space-x-1.5 sm:space-x-2 shrink-0 group"
          aria-label="Valence home"
        >
          <div className="h-8 px-1.5 bg-white rounded-sm flex items-center justify-center shadow-pop overflow-hidden">
            <Image
              src="/logo.png"
              alt=""
              width={28}
              height={28}
              priority
              className="h-6 w-auto object-contain"
            />
          </div>
          <span className="font-bold text-[16px] sm:text-[17px] tracking-[0.05em] text-text-main group-hover:text-accent-hover transition-colors">
            Valence
          </span>
        </Link>

        <CompanySearch onSelectCompany={onSelectCompany} />

        {/* The page's subject, so the h1. Broken at 900px rather than Tailwind's
            lg, because that is exactly where the mobile guard takes over: the
            guard carries its own h1 for the viewport it owns, and matching the
            breakpoints means exactly one of the two is ever exposed. At lg they
            disagreed, which both left a 900 to 1024 band with no heading at all
            and put two h1s in the accessibility tree on a phone. */}
        {metadata && (
          <h1 className="hidden min-[900px]:flex items-center space-x-1.5 bg-surface-3 border border-border rounded-sm px-2 py-1 max-w-[190px]">
            <span className="font-bold text-[11px] uppercase tracking-[0.03em] text-text-main truncate">
              {metadata.name}
            </span>
            <span className="font-mono font-bold text-[10px] text-accent-hover bg-accent-subtle border border-accent-border rounded-sm px-1.5 py-0.5 shrink-0">
              {metadata.ticker}
            </span>
          </h1>
        )}
      </div>

      {/* Center section: Mode Tabs */}
      <div
        ref={modeListRef}
        role="tablist"
        aria-label="Workspace view"
        onKeyDown={handleModeKeyDown}
        className="flex items-center bg-surface border border-border rounded-md p-0.5 space-x-0.5 shrink-0"
      >
        {MODES.map((m) => {
          const active = mode === m.id
          return (
            <button
              key={m.id}
              id={`tab-${m.id}`}
              role="tab"
              type="button"
              aria-selected={active}
              aria-controls={`panel-${m.id}`}
              tabIndex={active ? 0 : -1}
              onClick={() => onModeChange(m.id)}
              className={`px-2.5 sm:px-3 py-1 text-[12px] rounded-sm whitespace-nowrap transition-colors cursor-pointer ${
                active
                  ? 'bg-surface-2 text-text-main font-semibold'
                  : 'text-text-dim hover:text-text-main'
              }`}
            >
              {m.label}
            </button>
          )
        })}
      </div>

      {/* Right section: Scenario Toggle, QA Badge, Action Buttons */}
      <div className="flex items-center space-x-1.5 sm:space-x-2 shrink-0 pr-1">
        {/* Scenario control — a single-select radio group, not tabs */}
        <div
          role="radiogroup"
          aria-label="Valuation scenario"
          data-scenario-nav=""
          className="flex items-center bg-surface border border-border rounded-md p-0.5 shrink-0"
        >
          {SCENARIOS.map((sc) => {
            const active = scenario === sc
            const delta = scenarioDelta(sc)
            return (
              <button
                key={sc}
                role="radio"
                type="button"
                aria-checked={active}
                tabIndex={active ? 0 : -1}
                onClick={() => onScenarioChange(sc)}
                title={
                  delta
                    ? `Implied price ${delta} vs market under ${sc} assumptions`
                    : undefined
                }
                className={`px-2 py-0.5 text-[11px] capitalize rounded-sm whitespace-nowrap transition-colors cursor-pointer ${
                  active
                    ? 'bg-surface-2 text-text-main font-semibold'
                    : 'text-text-dim hover:text-text-muted'
                }`}
              >
                {sc}
                {delta && active && (
                  <span
                    className={`ml-1 font-mono text-[10px] ${
                      delta.startsWith('+') ? 'text-positive' : 'text-negative'
                    }`}
                  >
                    {delta}
                  </span>
                )}
              </button>
            )
          })}
        </div>

        {/* QA Status — opens the audit report */}
        <button
          type="button"
          onClick={onOpenQA}
          aria-label={
            qaStatus === 'passed'
              ? 'QA report: all model checks passed'
              : qaStatus === 'warning'
              ? `QA report: passed with ${skippedChecks.length} skipped check${skippedChecks.length === 1 ? '' : 's'}`
              : qaStatus === 'failed'
              ? `QA report: ${failedChecks.length} of ${qaChecks.length} checks failed`
              : 'QA report: checks have not run yet'
          }
          title="Open the automated model audit report"
          className={`flex items-center space-x-1 px-2 py-1 rounded-sm text-[10px] font-semibold uppercase tracking-[0.03em] border whitespace-nowrap shrink-0 transition-colors cursor-pointer ${
            qaStatus === 'passed'
              ? 'bg-positive-subtle text-positive border-positive/30 hover:bg-positive/20'
              : qaStatus === 'warning'
              ? 'bg-[#f59e0b]/10 text-[#f59e0b] border-[#f59e0b]/30 hover:bg-[#f59e0b]/20'
              : qaStatus === 'failed'
              ? 'bg-negative-subtle text-negative border-negative/40 hover:bg-negative/20'
              : 'bg-surface-2 text-text-dim border-border hover:text-text-muted'
          }`}
        >
          {qaStatus === 'passed' ? (
            <>
              <CheckCircle2 className="w-3 h-3 shrink-0" aria-hidden />
              <span>Model valid</span>
            </>
          ) : qaStatus === 'warning' ? (
            <>
              <AlertTriangle className="w-3 h-3 shrink-0" aria-hidden />
              <span>
                Valid · {skippedChecks.length} skipped
              </span>
            </>
          ) : qaStatus === 'failed' ? (
            <>
              <AlertTriangle className="w-3 h-3 shrink-0" aria-hidden />
              <span>
                {failedChecks.length} check{failedChecks.length === 1 ? '' : 's'} failed
              </span>
            </>
          ) : (
            <span>QA pending</span>
          )}
        </button>

        {/* Action buttons — Excel is the primary export; the rest are quiet */}
        {/* A nav landmark. This cluster and the mode tabs are the only regions
            past the KPI bar that a screen reader can jump to; header, main and
            footer alone gave no way past the bar itself. */}
        <nav aria-label="Model actions" className="flex items-center space-x-1 sm:space-x-1.5 shrink-0">
          {/* `max-[1439px]:hidden` on the four inline actions, and the menu below
              1440px, is one decision made in two class lists. The breakpoint is
              duplicated by necessity -- Tailwind has no way to say "the other one" --
              so `the header breakpoint is stated once` asserts the two agree, because a
              mismatch here shows up as both the row and the menu at once, which looks
              like a duplicate control rather than an overflow. */}
          <button
            type="button"
            onClick={onCopySummary}
            title="Copy valuation memo to clipboard"
            className="max-[1439px]:hidden flex items-center space-x-1 px-2 py-1 bg-surface-2 hover:bg-surface text-text-muted hover:text-text-main border border-border text-[11px] font-medium rounded-sm transition-colors cursor-pointer shrink-0"
          >
            <Copy className="w-3.5 h-3.5 shrink-0" aria-hidden />
            <span>Copy</span>
          </button>

          <button
            type="button"
            onClick={onSave}
            className="max-[1439px]:hidden flex items-center space-x-1 px-2 py-1 bg-transparent hover:bg-accent-subtle text-accent hover:text-accent-hover border border-accent-border text-[11px] font-medium rounded-sm transition-colors cursor-pointer shrink-0"
          >
            <Save className="w-3.5 h-3.5 shrink-0" aria-hidden />
            <span>Save</span>
          </button>

          {/* `max-[1439px]:hidden` and NOT `hidden sm:flex`. The original button used
              `hidden sm:flex` to drop Library on narrow screens, and adding the max-width
              variant alongside it does not compose: both match between 640px and 1439px,
              and `sm:flex` won, so Library stayed on the row for the whole band while the
              other three collapsed. Measured at 1152px with `sm:flex` present: Library
              visible and 90px off the edge. The max-width variant alone is the whole
              condition now, because the menu covers the narrow case that `sm:` was
              guarding. */}
          <button
            type="button"
            onClick={onOpenSaved}
            title="Open model library (saved models)"
            className="max-[1439px]:hidden flex items-center space-x-1 px-2 py-1 bg-surface-2 hover:bg-surface text-text-muted hover:text-text-main border border-border text-[11px] font-medium rounded-sm transition-colors cursor-pointer shrink-0"
          >
            <Bookmark className="w-3.5 h-3.5 shrink-0" aria-hidden />
            <span>Library</span>
          </button>

          <button
            type="button"
            onClick={onExportExcel}
            disabled={exporting}
            className="max-[1439px]:hidden flex items-center space-x-1 px-2.5 py-1 bg-excel-bg hover:bg-excel-bg-hover disabled:opacity-60 text-excel-text border border-excel-border text-[11px] font-semibold rounded-sm transition-colors cursor-pointer disabled:cursor-wait shrink-0"
          >
            <FileSpreadsheet className="w-3.5 h-3.5 shrink-0" aria-hidden />
            <span>{exporting ? 'Exporting…' : 'Excel'}</span>
          </button>

          {/* The same four actions, for the widths where the row does not fit. A menu
              rather than a narrower row because the row is a single non-wrapping line in
              a fixed 48px bar: there is nowhere for a control to go but off the end. */}
          <div ref={actionsRef} className="relative min-[1440px]:hidden shrink-0">
            <button
              ref={actionsButtonRef}
              type="button"
              onClick={() => setActionsOpen((v) => !v)}
              aria-expanded={actionsOpen}
              aria-haspopup="menu"
              aria-controls={actionsOpen ? actionsMenuId : undefined}
              aria-label={`Model actions${actionsOpen ? ', open' : ''}`}
              title="Model actions"
              className="flex items-center px-2 py-1 bg-surface-2 hover:bg-surface text-text-muted hover:text-text-main border border-border text-[11px] font-medium rounded-sm transition-colors cursor-pointer"
            >
              <Ellipsis className="w-3.5 h-3.5" aria-hidden />
            </button>

            {actionsOpen && (
              <div
                id={actionsMenuId}
                role="menu"
                aria-label="Model actions"
                className="absolute right-0 top-[calc(100%+6px)] z-50 min-w-[190px] rounded-sm border border-border-interactive bg-surface-2 py-1 shadow-[var(--shadow-pop)]"
              >
                {ACTION_ITEMS.map(({ key, label, hint, Icon, disabled, run }) => (
                  <button
                    key={key}
                    type="button"
                    role="menuitem"
                    title={hint}
                    disabled={disabled}
                    onClick={run}
                    className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-[12px] text-text-main hover:bg-surface-3 disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
                  >
                    <Icon className="w-3.5 h-3.5 shrink-0 text-text-dim" aria-hidden />
                    <span>{label}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </nav>
      </div>
    </header>
  )
}
