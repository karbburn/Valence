'use client'

import React, { useEffect } from 'react'
import { CheckCircle2, AlertTriangle, X } from 'lucide-react'

export interface ToastProps {
  message: string | null
  type?: 'success' | 'error'
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

  return (
    <div
      className={`fixed bottom-6 right-6 z-50 flex items-center space-x-2.5 bg-[#192030] border rounded-[4px] px-4 py-2.5 shadow-xl select-none transition-all ${
        type === 'success'
          ? 'border-[#10b981]/40 text-[#e2e8f0]'
          : 'border-[#ef4444]/40 text-[#fca5a5]'
      }`}
    >
      {type === 'success' ? (
        <CheckCircle2 className="w-4 h-4 text-[#10b981] shrink-0" />
      ) : (
        <AlertTriangle className="w-4 h-4 text-[#ef4444] shrink-0" />
      )}
      <span className="font-semibold text-[12px]">{message}</span>
      <button
        onClick={onClose}
        className="text-[#64748b] hover:text-[#f8fafc] transition-colors ml-2"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}
