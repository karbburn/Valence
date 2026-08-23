'use client'

import React, { useEffect, useRef } from 'react'
import { CheckCircle2, AlertTriangle, Info, X } from 'lucide-react'

export interface ToastProps {
  message: string | null
  type?: 'success' | 'error' | 'warning' | 'info'
  onClose: () => void
  autoDismissMs?: number
}

const TONE: Record<
  'success' | 'error' | 'warning' | 'info',
  { border: string; text: string; icon: React.ReactNode; label: string }
> = {
  success: {
    border: 'border-positive/40',
    text: 'text-text-main',
    icon: <CheckCircle2 className="w-4 h-4 text-positive shrink-0" aria-hidden />,
    label: 'Success',
  },
  error: {
    border: 'border-negative/40',
    text: 'text-text-main',
    icon: <AlertTriangle className="w-4 h-4 text-negative shrink-0" aria-hidden />,
    label: 'Error',
  },
  warning: {
    border: 'border-warning/40',
    text: 'text-text-main',
    icon: <AlertTriangle className="w-4 h-4 text-warning shrink-0" aria-hidden />,
    label: 'Warning',
  },
  info: {
    border: 'border-accent-border',
    text: 'text-text-main',
    icon: <Info className="w-4 h-4 text-accent shrink-0" aria-hidden />,
    label: 'Notice',
  },
}

export function Toast({
  message,
  type = 'success',
  onClose,
  autoDismissMs = 2500,
}: ToastProps) {
  const pausedRef = useRef(false)
  const tone = TONE[type]

  useEffect(() => {
    if (!message) return
    // Errors stay until dismissed — they carry information the user may be reading.
    if (type === 'error') return
    const timer = setTimeout(() => {
      if (!pausedRef.current) onClose()
    }, autoDismissMs)
    return () => clearTimeout(timer)
  }, [message, type, onClose, autoDismissMs])

  if (!message) return null

  return (
    <div
      role={type === 'error' ? 'alert' : 'status'}
      aria-live={type === 'error' ? 'assertive' : 'polite'}
      onMouseEnter={() => {
        pausedRef.current = true
      }}
      onMouseLeave={() => {
        pausedRef.current = false
      }}
      className={`fixed bottom-5 right-5 z-50 flex items-center gap-2.5 bg-surface border ${tone.border} rounded-sm px-3.5 py-2.5 shadow-pop ${tone.text} select-none`}
    >
      {tone.icon}
      <span className="font-medium text-[12px]">
        <span className="sr-only">{tone.label}: </span>
        {message}
      </span>
      <button
        onClick={onClose}
        className="text-text-dim hover:text-text-main transition-colors ml-1 p-0.5 rounded-sm hover:bg-surface-2 cursor-pointer"
        aria-label="Dismiss notification"
      >
        <X className="w-3.5 h-3.5" aria-hidden />
      </button>
    </div>
  )
}
