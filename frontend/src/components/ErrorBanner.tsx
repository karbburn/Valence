'use client'

import React, { useEffect } from 'react'
import { AlertCircle, X } from 'lucide-react'

export interface ErrorBannerProps {
  message: string | null
  onDismiss: () => void
  autoDismissMs?: number
}

export function ErrorBanner({
  message,
  onDismiss,
  autoDismissMs = 5000,
}: ErrorBannerProps) {
  useEffect(() => {
    if (!message) return
    const timer = setTimeout(() => {
      onDismiss()
    }, autoDismissMs)
    return () => clearTimeout(timer)
  }, [message, onDismiss, autoDismissMs])

  if (!message) return null

  return (
    <div className="fixed top-4 left-1/2 -translate-x-1/2 z-[90] flex items-center space-x-3 bg-[#ef4444]/10 border border-[#ef4444]/30 rounded-[4px] px-5 py-2.5 shadow-lg backdrop-blur-sm select-none">
      <AlertCircle className="w-4 h-4 text-[#ef4444] shrink-0" />
      <span className="font-semibold text-[12px] text-[#fca5a5]">{message}</span>
      <button
        onClick={onDismiss}
        className="text-[#ef4444] hover:text-[#f8fafc] transition-colors p-0.5 rounded-[2px]"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}
