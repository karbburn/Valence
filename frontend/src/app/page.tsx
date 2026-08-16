'use client'

import React, { useState, useEffect } from 'react'
import { Header } from '@/components/Header'
import { KPIBar } from '@/components/KPIBar'
import { LoadingOverlay } from '@/components/LoadingOverlay'
import { ErrorBanner } from '@/components/ErrorBanner'
import { Toast } from '@/components/Toast'
import { DriverPanel } from '@/components/DriverPanel'
import { WACCBreakdown } from '@/components/WACCBreakdown'
import { DCFSchedule } from '@/components/DCFSchedule'
import { ForecastTable } from '@/components/ForecastTable'
import { QuickDCFView } from '@/components/QuickDCFView'
import { FullModelView } from '@/components/FullModelView'
import { QAModal } from '@/components/QAModal'
import { SaveModal } from '@/components/SaveModal'
import { SavedModelsModal } from '@/components/SavedModelsModal'
import { MobileGuard } from '@/components/MobileGuard'
import { useModelSpec } from '@/hooks/useModelSpec'
import { ScenarioLabel, CompanySummary } from '@/lib/types'
import { saveModel, loadSavedModel } from '@/lib/api'

export default function HomePage() {
  const { spec, loading, error, companyId, loadModel, recompute, revert } =
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
    if (!companyId) return
    await saveModel(companyId, name)
    setToastType('success')
    setToastMessage(`Saved model: "${name}"`)
  }

  const handleLoadSavedModel = async (modelId: string) => {
    setLocalError(null)
    setLoadingTitle('Loading Saved Model')
    setLoadingSubtitle('Retrieving persisted valuation model parameters...')
    const loadedSpec = await loadSavedModel(modelId)
    if (loadedSpec?.metadata?.company_id) {
      await loadModel(loadedSpec.metadata.company_id)
    }
    setToastType('success')
    setToastMessage(`Loaded saved model`)
  }

  const handleExportExcel = () => {
    window.location.href = `/api/export/excel?company_id=${companyId}`
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
      />

      {/* KPI Ticker Strip */}
      <KPIBar spec={spec} scenario={scenario} />

      {/* Main Workspace Layout */}
      <main className="flex-1 w-full max-w-[1680px] mx-auto p-5">
        {!spec && !loading && (
          <div className="bg-surface border border-border rounded-[4px] p-8 text-center text-[#64748b] text-[13px]">
            No valuation model loaded. Use the search bar in the header to select a company.
          </div>
        )}

        {spec && mode === 'analyst' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
            {/* Left Column: Driver Sliders & WACC Breakdown */}
            <div className="lg:col-span-4 space-y-5">
              <DriverPanel
                spec={spec}
                scenario={scenario}
                onDriverChange={handleDriverChange}
                onDriverRevert={handleDriverRevert}
              />
              <WACCBreakdown spec={spec} scenario={scenario} />
            </div>

            {/* Right Column: DCF Valuation Schedule & Forecast Summary */}
            <div className="lg:col-span-8 space-y-5">
              <DCFSchedule spec={spec} scenario={scenario} />
              <ForecastTable spec={spec} scenario={scenario} />
            </div>
          </div>
        )}

        {spec && mode === 'quick' && (
          <QuickDCFView spec={spec} scenario={scenario} />
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

      {/* Toast Notification System */}
      <Toast
        message={toastMessage}
        type={toastType}
        onClose={() => setToastMessage(null)}
      />
    </div>
  )
}
