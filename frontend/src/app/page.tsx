'use client'

import React, { useState, useEffect } from 'react'
import { Header } from '@/components/Header'
import { KPIBar } from '@/components/KPIBar'
import { LoadingOverlay } from '@/components/LoadingOverlay'
import { ErrorBanner } from '@/components/ErrorBanner'
import { Toast } from '@/components/Toast'
import { DriverPanel } from '@/components/DriverPanel'
import { WACCBreakdown } from '@/components/WACCBreakdown'
import { FinancialRatios } from '@/components/FinancialRatios'
import { DCFSchedule } from '@/components/DCFSchedule'
import { ForecastTable } from '@/components/ForecastTable'
import { QuickDCFView } from '@/components/QuickDCFView'
import { FullModelView } from '@/components/FullModelView'
import { QAModal } from '@/components/QAModal'
import { SaveModal } from '@/components/SaveModal'
import { SavedModelsModal } from '@/components/SavedModelsModal'
import { MethodologyModal } from '@/components/MethodologyModal'
import { MobileGuard } from '@/components/MobileGuard'
import { useModelSpec } from '@/hooks/useModelSpec'
import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts'
import { ScenarioLabel, CompanySummary } from '@/lib/types'
import { saveModel, loadSavedModel } from '@/lib/api'
import { fmtPrice, fmtNum } from '@/lib/formatters'
import { DRIVER_CONFIGS } from '@/components/DriverPanel'

const driverLabel = (key: string) => DRIVER_CONFIGS.find((c) => c.key === key)

const formatDriverValue = (key: string, value: number): string => {
  const unit = driverLabel(key)?.unit ?? '%'
  if (unit === 'x') return `${fmtNum(value, 1)}x`
  if (unit === 'days') return `${fmtNum(value, 0)} days`
  return `${fmtNum(value, 1)}%`
}

export default function HomePage() {
  const { spec, loading, error, clearError, companyId, loadModel, applySpec, recompute, revert, resetAll } =
    useModelSpec('infy_infy')

  const [mode, setMode] = useState<'analyst' | 'quick' | 'full'>('analyst')
  const [scenario, setScenario] = useState<ScenarioLabel>('base')
  const [toastMessage, setToastMessage] = useState<string | null>(null)
  const [toastType, setToastType] = useState<'success' | 'error' | 'warning' | 'info'>('success')
  const [localError, setLocalError] = useState<string | null>(null)

  // Context-aware loading copy
  const [loadingTitle, setLoadingTitle] = useState('Compiling Valuation Model')
  const [loadingSubtitle, setLoadingSubtitle] = useState(
    'Ingesting live financial statements, normalizing taxonomy, and solving DCF & WACC matrices...'
  )

  const [exporting, setExporting] = useState(false)

  // Modal visibility states
  const [qaOpen, setQaOpen] = useState(false)
  const [saveOpen, setSaveOpen] = useState(false)
  const [savedModelsOpen, setSavedModelsOpen] = useState(false)
  const [methodologyOpen, setMethodologyOpen] = useState(false)

  // Keyboard Shortcuts (Ctrl+S, 1/2/3 mode keys, Escape, Left/Right arrows)
  useKeyboardShortcuts({
    onSave: () => setSaveOpen(true),
    onSetMode: setMode,
    onScenarioChange: setScenario,
    onCloseModals: () => {
      setQaOpen(false)
      setSaveOpen(false)
      setSavedModelsOpen(false)
      setMethodologyOpen(false)
    },
    currentScenario: scenario,
    hasOpenModal: qaOpen || saveOpen || savedModelsOpen || methodologyOpen,
  })

  useEffect(() => {
    loadModel('infy_infy')
  }, [loadModel])

  const handleSelectCompany = (company: CompanySummary) => {
    setLocalError(null)
    const isLive = company.onboarding_status !== 'onboarded'

    if (isLive) {
      setLoadingTitle(`Compiling Live Model for ${company.ticker}`)
      setLoadingSubtitle(
        `Ingesting live financial statements, normalizing taxonomy, and solving DCF matrices...`
      )
    } else {
      setLoadingTitle(`Loading ${company.ticker} Model`)
      setLoadingSubtitle(`Loading precomputed valuation model from local registry...`)
    }

    loadModel(company.company_id)
    setToastType('info')
    setToastMessage(`Loaded: ${company.ticker} (${company.name})`)
  }

  const handleDriverChange = async (driverKey: string, value: number) => {
    await recompute(driverKey, value, scenario)
    const label = driverLabel(driverKey)?.label ?? driverKey
    setToastType('info')
    setToastMessage(`${label} set to ${formatDriverValue(driverKey, value)}`)
  }

  const handleDriverRevert = async (driverKey: string, period?: string) => {
    await revert(driverKey, scenario, period)
    const label = driverLabel(driverKey)?.label ?? driverKey
    setToastType('info')
    setToastMessage(`${label} reverted to baseline`)
  }

  const handleSaveSubmit = async (name: string) => {
    if (!companyId || !spec) return
    await saveModel(spec, name)
    setToastType('success')
    setToastMessage(`Saved model: "${name}"`)
  }

  const handleLoadSavedModel = async (modelId: string) => {
    setLocalError(null)
    const loadedSpec = await loadSavedModel(modelId)
    if (loadedSpec?.metadata?.company_id) {
      applySpec(loadedSpec)
    }
    setToastType('success')
    setToastMessage(`Loaded saved model`)
  }

  const handleExportExcel = async () => {
    if (!companyId || exporting) return
    setExporting(true)
    try {
      const res = await fetch(`/api/export/excel?company_id=${companyId}`)
      if (!res.ok) throw new Error(`Export failed (${res.status})`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${spec?.metadata?.ticker?.toLowerCase() || companyId}_valuation_model.xlsx`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      setToastType('success')
      setToastMessage(`Excel workbook downloaded — 30 tabs, live formulas`)
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : 'Excel export failed')
    } finally {
      setExporting(false)
    }
  }

  const handleResetAll = async () => {
    if (!spec) return
    await resetAll(scenario)
    setToastType('info')
    setToastMessage('All valuation drivers restored to baseline defaults')
  }

  const handleCopySummary = async () => {
    if (!spec) return
    const ticker = spec.metadata?.ticker || 'MODEL'
    const name = spec.metadata?.name || 'Company'
    const currency = spec.metadata?.currency || 'INR'
    const valuation = spec.valuation?.find((v) => v.scenario === scenario) || spec.valuation?.[0]
    const bridge = valuation?.dcf_bridge
    const price = bridge?.implied_share_price != null ? fmtPrice(bridge.implied_share_price, currency, 2) : '—'
    const mkt = valuation?.reverse_dcf?.market_price != null ? fmtPrice(valuation.reverse_dcf.market_price, currency, 2) : '—'
    const waccVal = valuation?.wacc?.wacc != null ? `${valuation.wacc.wacc.toFixed(2)}%` : '—'

    const text = `${name} (${ticker}) DCF Valuation [${scenario.toUpperCase()} SCENARIO]\nDCF Implied Price: ${price} | Market Price: ${mkt}\nWACC: ${waccVal} | Model: Unlevered FCFF @ WACC`

    try {
      await navigator.clipboard.writeText(text)
      setToastType('success')
      setToastMessage('Valuation memo copied to clipboard')
    } catch {
      setToastType('error')
      setToastMessage('Clipboard unavailable — copy blocked by the browser')
    }
  }

  return (
    <div className="min-h-screen bg-canvas text-text-main flex flex-col font-sans">
      {/* Mobile Viewport Guard (<900px) */}
      <MobileGuard />

      {/* Page Loading Overlay */}
      <LoadingOverlay
        visible={loading}
        title={loadingTitle}
        subtitle={loadingSubtitle}
      />

      {/* Global Error Banner */}
      <ErrorBanner
        message={error || localError}
        onDismiss={() => {
          setLocalError(null)
          clearError()
        }}
        onRetry={() => {
          setLocalError(null)
          clearError()
          loadModel(companyId)
        }}
        retryLabel={spec ? 'Retry' : 'Reload model'}
      />

      {/* Header Toolbar */}
      <Header
        spec={spec}
        mode={mode}
        scenario={scenario}
        exporting={exporting}
        onModeChange={setMode}
        onScenarioChange={setScenario}
        onSelectCompany={handleSelectCompany}
        onSave={() => setSaveOpen(true)}
        onOpenSaved={() => setSavedModelsOpen(true)}
        onOpenQA={() => setQaOpen(true)}
        onExportExcel={handleExportExcel}
        onCopySummary={handleCopySummary}
      />

      {/* KPI Ticker Strip */}
      <KPIBar spec={spec} scenario={scenario} />

      {/* Main Workspace Layout */}
      <main id="main" className="flex-1 w-full max-w-[1680px] mx-auto p-4 sm:p-5">
        {!spec && !loading && (
          <div className="bg-surface border border-border rounded-sm p-8 text-center text-text-dim text-[13px] space-y-3">
            <p>No valuation model loaded. Use the search bar in the header to select a company.</p>
            <button
              onClick={() => {
                setLocalError(null)
                clearError()
                loadModel(companyId)
              }}
              className="px-4 py-1.5 bg-surface-2 hover:bg-surface text-text-muted hover:text-text-main border border-border text-[12px] font-semibold rounded-sm transition-colors cursor-pointer"
            >
              Reload default model
            </button>
          </div>
        )}

        <div
          id="panel-analyst"
          role="tabpanel"
          aria-labelledby="tab-analyst"
          hidden={mode !== 'analyst'}
        >
          {spec && mode === 'analyst' && (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-start">
              {/* Left Column: Driver Sliders, WACC Breakdown & Return Ratios */}
              <div className="lg:col-span-4 space-y-4">
                <DriverPanel
                  spec={spec}
                  scenario={scenario}
                  onDriverChange={handleDriverChange}
                  onDriverRevert={handleDriverRevert}
                  onResetAll={handleResetAll}
                />
                <WACCBreakdown spec={spec} scenario={scenario} />
                <FinancialRatios spec={spec} scenario={scenario} />
              </div>

              {/* Right Column: DCF Valuation Schedule & Forecast Summary */}
              <div className="lg:col-span-8 space-y-4">
                <DCFSchedule
                  spec={spec}
                  scenario={scenario}
                  onOpenMethodology={() => setMethodologyOpen(true)}
                />
                <ForecastTable spec={spec} scenario={scenario} />
              </div>
            </div>
          )}
        </div>

        <div
          id="panel-quick"
          role="tabpanel"
          aria-labelledby="tab-quick"
          hidden={mode !== 'quick'}
        >
          {spec && mode === 'quick' && (
            <QuickDCFView
              spec={spec}
              scenario={scenario}
              onOpenMethodology={() => setMethodologyOpen(true)}
            />
          )}
        </div>

        <div
          id="panel-full"
          role="tabpanel"
          aria-labelledby="tab-full"
          hidden={mode !== 'full'}
        >
          {spec && mode === 'full' && <FullModelView spec={spec} scenario={scenario} />}
        </div>
      </main>

      {/* Shortcut reference — persistent, quiet */}
      <footer className="w-full max-w-[1680px] mx-auto px-4 pb-3 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[10px] text-text-dim">
        <span className="text-text-faint">Shortcuts</span>
        <span>
          <kbd>1</kbd> analyst
        </span>
        <span>
          <kbd>2</kbd> quick DCF
        </span>
        <span>
          <kbd>3</kbd> 3-statement
        </span>
        <span>
          <kbd>←</kbd>
          <kbd>→</kbd> scenario
        </span>
        <span>
          <kbd>Ctrl S</kbd> save
        </span>
        <span>
          <kbd>Esc</kbd> close dialogs
        </span>
      </footer>

      {/* Modals */}
      <QAModal
        open={qaOpen}
        onClose={() => setQaOpen(false)}
        qa={spec?.qa || null}
      />

      {saveOpen && (
        <SaveModal
          open
          onClose={() => setSaveOpen(false)}
          companyName={spec?.metadata?.name || 'Valuation Model'}
          scenario={scenario}
          onSave={handleSaveSubmit}
        />
      )}

      {savedModelsOpen && (
        <SavedModelsModal
          open
          onClose={() => setSavedModelsOpen(false)}
          onLoadModel={handleLoadSavedModel}
        />
      )}

      <MethodologyModal
        open={methodologyOpen}
        onClose={() => setMethodologyOpen(false)}
        spec={spec}
        scenario={scenario}
      />

      {/* Toast Notification System */}
      <Toast
        message={toastMessage}
        type={toastType}
        onClose={() => setToastMessage(null)}
      />
    </div>
  )
}
