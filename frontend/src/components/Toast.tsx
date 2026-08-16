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

  const getBorderColor = () => {
    switch (type) {
      case 'success':
        return 'border-[#10b981]/40 text-[#e2e8f0]'
      case 'error':
        return 'border-[#ef4444]/40 text-[#fca5a5]'
      case 'warning':
        return 'border-[#f59e0b]/40 text-[#fef3c7]'
      case 'info':
        return 'border-[#0ea5e9]/40 text-[#e0f2fe]'
    }
  }

  const renderIcon = () => {
    switch (type) {
      case 'success':
        return <CheckCircle2 className="w-4 h-4 text-[#10b981] shrink-0" />
      case 'error':
        return <AlertTriangle className="w-4 h-4 text-[#ef4444] shrink-0" />
      case 'warning':
        return <AlertTriangle className="w-4 h-4 text-[#f59e0b] shrink-0" />
      case 'info':
        return <Info className="w-4 h-4 text-[#0ea5e9] shrink-0" />
    }
  }

  return (
    <div
      className={`fixed bottom-6 right-6 z-50 flex items-center space-x-2.5 bg-[#192030] border rounded-[4px] px-4 py-2.5 shadow-xl select-none transition-all ${getBorderColor()}`}
    >
      {renderIcon()}
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
