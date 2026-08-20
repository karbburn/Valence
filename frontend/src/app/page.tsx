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
import { fmtPrice } from '@/lib/formatters'

export default function HomePage() {
  const { spec, loading, error, companyId, loadModel, applySpec, recompute, revert } =
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
    setToastType('info')
    setToastMessage(`${driverKey} → ${value}`)
  }

  const handleDriverRevert = async (driverKey: string, period?: string) => {
    await revert(driverKey, scenario, period)
    setToastType('info')
    setToastMessage(`${driverKey} reverted`)
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

  const handleExportExcel = () => {
    window.location.href = `/api/export/excel?company_id=${companyId}`
    setToastType('success')
    setToastMessage(`30-Tab Institutional Model generated for ${spec?.metadata?.ticker || 'Company'}!`)
  }

  const handleResetAll = async () => {
    if (!spec) return
    const scenarioAssumptions = (spec.assumptions || []).filter((a) => a.scenario === scenario && a.type === 'user_override')
    for (const a of scenarioAssumptions) {
      await revert(a.driver_key, scenario, a.period)
    }
    setToastType('info')
    setToastMessage('All valuation drivers restored to baseline defaults')
  }

  const handleCopySummary = () => {
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

    navigator.clipboard.writeText(text)
    setToastType('success')
    setToastMessage('Valuation memo summary copied to clipboard!')
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
        onDismiss={() => setLocalError(null)}
      />

      {/* Header Toolbar */}
      <Header
        spec={spec}
        mode={mode}
        scenario={scenario}
        companyId={companyId}
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
      <main className="flex-1 w-full max-w-[1680px] mx-auto p-4 sm:p-5">
        {!spec && !loading && (
          <div className="bg-surface border border-border rounded-[4px] p-8 text-center text-[#64748b] text-[13px]">
            No valuation model loaded. Use the search bar in the header to select a company.
          </div>
        )}

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

        {spec && mode === 'quick' && (
          <QuickDCFView
            spec={spec}
            scenario={scenario}
            onOpenMethodology={() => setMethodologyOpen(true)}
          />
        )}

        {spec && mode === 'full' && (
          <FullModelView spec={spec} scenario={scenario} />
        )}
      </main>

      {/* Modals */}
      <QAModal
        open={qaOpen}
        onClose={() => setQaOpen(false)}
        qa={spec?.qa || null}
      />

      <SaveModal
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        companyName={spec?.metadata?.name || 'Valuation Model'}
        scenario={scenario}
        onSave={handleSaveSubmit}
      />

      <SavedModelsModal
        open={savedModelsOpen}
        onClose={() => setSavedModelsOpen(false)}
        onLoadModel={handleLoadSavedModel}
      />

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
