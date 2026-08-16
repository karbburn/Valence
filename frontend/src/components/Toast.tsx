'use client'

import React, { useEffect } from 'react'
import { CheckCircle2, AlertTriangle, Info, X } from 'lucide-react'

export interface ToastProps {
  message: string | null
  type?: 'success' | 'error' | 'warning' | 'info'
  onClose: () => void
  autoDismissMs?: number
}

export function Toast({
  message,
  type = 'success',
  onClose,
  autoDismissMs = 2500,
}: ToastProps) {
  useEffect(() => {
    if (!message) return
    const timer = setTimeout(() => {
      onClose()
    }, autoDismissMs)
    return () => clearTimeout(timer)
  }, [message, onClose, autoDismissMs])

  if (!message) return null

  const getStyleTokens = () => {
    switch (type) {
      case 'success':
        return {
          border: 'border-[#10b981]/30',
          gradient: 'from-[#10b981]/40 to-transparent',
          shadow: 'shadow-[0_4px_24px_rgba(16,185,129,0.12)]',
          text: 'text-[#e2e8f0]',
        }
      case 'error':
        return {
          border: 'border-[#ef4444]/30',
          gradient: 'from-[#ef4444]/40 to-transparent',
          shadow: 'shadow-[0_4px_24px_rgba(239,68,68,0.12)]',
          text: 'text-[#fca5a5]',
        }
      case 'warning':
        return {
          border: 'border-[#f59e0b]/30',
          gradient: 'from-[#f59e0b]/40 to-transparent',
          shadow: 'shadow-[0_4px_24px_rgba(245,158,11,0.12)]',
          text: 'text-[#fef3c7]',
        }
      case 'info':
        return {
          border: 'border-[#0ea5e9]/30',
          gradient: 'from-[#0ea5e9]/40 to-transparent',
          shadow: 'shadow-[0_4px_24px_rgba(14,165,233,0.12)]',
          text: 'text-[#e0f2fe]',
        }
    }
  }

  const renderIcon = () => {
    switch (type) {
      case 'success':
        return <CheckCircle2 className="w-4 h-4 text-[#10b981] shrink-0" />
      case 'error':
        return <AlertTriangle className="w-4 h-4 text-[#ef4444] shrink-0 animate-bounce" />
      case 'warning':
        return <AlertTriangle className="w-4 h-4 text-[#f59e0b] shrink-0" />
      case 'info':
        return <Info className="w-4 h-4 text-[#0ea5e9] shrink-0" />
    }
  }

  const tokens = getStyleTokens()

  return (
    <div
      className={`fixed bottom-6 right-6 z-50 flex items-center space-x-2.5 bg-[#111622]/95 border ${tokens.border} rounded-[4px] px-4 py-2.5 ${tokens.shadow} ${tokens.text} backdrop-blur-md transition-all duration-300 select-none overflow-hidden`}
    >
      {/* Subtle top reflection accent line */}
      <div className={`absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r ${tokens.gradient}`} />

      {/* Variant Icon */}
      {renderIcon()}

      {/* Message Text */}
      <span className="font-semibold text-[12px]">{message}</span>

      {/* Dismiss Button */}
      <button
        onClick={onClose}
        className="text-[#64748b] hover:text-[#f8fafc] transition-colors ml-2 p-0.5 rounded hover:bg-[#192030] cursor-pointer"
        aria-label="Dismiss notification"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}
