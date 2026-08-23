'use client'

import React from 'react'

export interface LoadingOverlayProps {
  visible: boolean
  title?: string
  subtitle?: string
}

/**
 * Full-screen build state. Announced politely to assistive tech, visually calm:
 * one spinner, one activity bar, honest copy. No engine cosplay.
 */
export function LoadingOverlay({
  visible,
  title = 'Building valuation model',
  subtitle = 'Ingesting statements, normalizing, forecasting, and discounting cash flows.',
}: LoadingOverlayProps) {
  if (!visible) return null

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-canvas/80 backdrop-blur-[6px] select-none"
    >
      <div className="bg-surface border border-border-interactive rounded-md p-6 max-w-sm w-full text-center shadow-overlay">
        <div className="mx-auto mb-4 h-10 w-10 rounded-full border-2 border-surface-2 border-t-accent animate-spin" />

        <h3 className="font-semibold text-[14px] text-text-main">{title}</h3>
        <p className="mt-1.5 text-[12px] text-text-muted leading-relaxed">{subtitle}</p>

        <div className="activity-bar mt-4 rounded-full" aria-hidden />
      </div>
    </div>
  )
}
