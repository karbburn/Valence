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
import { useModelSpec } from '@/hooks/useModelSpec'
import { ScenarioLabel } from '@/lib/types'
import { saveModel } from '@/lib/api'

export default function HomePage() {
  const { spec, loading, error, companyId, loadModel, recompute, revert } =
    useModelSpec('infy_infy')

  const [mode, setMode] = useState<'analyst' | 'quick' | 'full'>('analyst')
  const [scenario, setScenario] = useState<ScenarioLabel>('base')
  const [toastMessage, setToastMessage] = useState<string | null>(null)
  const [toastType, setToastType] = useState<'success' | 'error' | 'warning' | 'info'>('success')
  const [searchQuery, setSearchQuery] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)

  useEffect(() => {
    loadModel('infy_infy')
  }, [loadModel])

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

  const handleSave = async () => {
    if (!companyId) return
    const defaultName = `${spec?.metadata?.name || 'Model'} – ${scenario.toUpperCase()}`
    const name = window.prompt('Save model as:', defaultName)
    if (!name) return

    try {
      await saveModel(companyId, name)
      setToastType('success')
      setToastMessage(`Saved: "${name}"`)
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : 'Save failed')
    }
  }

  const handleOpenSaved = () => {
    setToastType('info')
    setToastMessage('Saved models dialog ready')
  }

  const handleOpenQA = () => {
    setToastType('info')
    setToastMessage('QA checks dialog ready')
  }

  const handleExportExcel = () => {
    window.location.href = `/api/export/excel?company_id=${companyId}`
  }

  return (
    <div className="min-h-screen bg-canvas text-text-main flex flex-col font-sans">
      {/* Page Loading Overlay */}
      <LoadingOverlay visible={loading} />

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
        onSave={handleSave}
        onOpenSaved={handleOpenSaved}
        onOpenQA={handleOpenQA}
        onExportExcel={handleExportExcel}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
      />

      {/* KPI Ticker Strip */}
      <KPIBar spec={spec} scenario={scenario} />

      {/* Main Workspace Layout */}
      <main className="flex-1 w-full max-w-[1680px] mx-auto p-5">
        {mode === 'analyst' && (
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

        {mode === 'quick' && (
          <QuickDCFView spec={spec} scenario={scenario} />
        )}

        {mode === 'full' && (
          <FullModelView spec={spec} scenario={scenario} />
        )}
      </main>

      {/* Toast Notification System */}
      <Toast
        message={toastMessage}
        type={toastType}
        onClose={() => setToastMessage(null)}
      />
    </div>
  )
}
