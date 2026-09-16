'use client'

import React from 'react'
import { AlertTriangle, X } from 'lucide-react'

export interface ErrorBannerProps {
  message: string | null
  onDismiss: () => void
  onRetry?: () => void
  retryLabel?: string
}

/**
 * Errors persist until the user dismisses them — auto-dismissing an error
 * destroys information the user may still need to read.
 */
export function ErrorBanner({ message, onDismiss, onRetry, retryLabel = 'Retry' }: ErrorBannerProps) {
  if (!message) return null

  return (
    <div
      role="alert"
      className="fixed top-4 left-1/2 -translate-x-1/2 z-[90] flex items-center gap-3 bg-surface border border-negative/40 rounded-sm px-4 py-2.5 shadow-pop select-none"
    >
      <AlertTriangle className="w-4 h-4 text-negative shrink-0" aria-hidden />

      <span className="font-medium text-[12px] text-text-main max-w-md break-words">
        {message}
      </span>

      {onRetry && (
        <button
          onClick={onRetry}
          className="text-[11px] font-semibold text-accent hover:text-accent-hover border border-accent-border hover:bg-accent-subtle rounded-sm px-2 py-0.5 transition-colors cursor-pointer shrink-0"
        >
          {retryLabel}
        </button>
      )}

      <button
        onClick={onDismiss}
        className="text-negative hover:text-text-main transition-colors p-1 rounded-sm hover:bg-negative-subtle cursor-pointer shrink-0"
        aria-label="Dismiss error"
      >
        <X className="w-3.5 h-3.5" aria-hidden />
      </button>
    </div>
  )
}
