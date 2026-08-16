'use client'

import React, { useEffect } from 'react'
import { AlertTriangle, X } from 'lucide-react'

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
    <div className="fixed top-4 left-1/2 -translate-x-1/2 z-[90] flex items-center space-x-3 bg-[#111622]/95 border border-[#ef4444]/40 rounded-[4px] px-5 py-2.5 shadow-[0_0_30px_rgba(239,68,68,0.15)] backdrop-blur-md transition-all duration-300 select-none overflow-hidden">
      {/* Subtle top reflection line */}
      <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-[#ef4444]/50 to-transparent" />

      {/* Warning/Alert Icon */}
      <AlertTriangle className="w-4 h-4 text-[#ef4444] shrink-0 animate-[pulse_2s_infinite]" />
      
      {/* Error Message */}
      <span className="font-medium text-[12px] text-[#fca5a5] max-w-md break-words pr-2">
        {message}
      </span>

      {/* Divider */}
      <div className="w-[1px] h-3.5 bg-[#ef4444]/25" />

      {/* Dismiss Button */}
      <button
        onClick={onDismiss}
        className="text-[#ef4444] hover:text-[#f8fafc] transition-colors p-1 rounded-[3px] hover:bg-[#ef4444]/10 cursor-pointer"
        aria-label="Dismiss error"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}
