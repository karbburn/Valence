'use client'

import React, { useEffect, useId, useRef } from 'react'
import { X } from 'lucide-react'

export interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  children: React.ReactNode
  maxWidth?: string
}

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'

export function Modal({
  open,
  onClose,
  title,
  children,
  maxWidth = 'max-w-lg',
}: ModalProps) {
  const titleId = useId()
  const boxRef = useRef<HTMLDivElement>(null)
  const restoreFocusRef = useRef<HTMLElement | null>(null)

  // Focus moves into the dialog on open and returns to the trigger on close.
  useEffect(() => {
    if (!open) return
    restoreFocusRef.current = document.activeElement as HTMLElement | null

    const box = boxRef.current
    const preferred =
      box?.querySelector<HTMLElement>('[data-autofocus]') ??
      box?.querySelector<HTMLElement>(FOCUSABLE)
    ;(preferred ?? box)?.focus()

    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    return () => {
      document.body.style.overflow = prevOverflow
      restoreFocusRef.current?.focus?.()
    }
  }, [open])

  // Minimal focus containment: Tab cycles inside the dialog.
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== 'Tab' || !boxRef.current) return
    const items = Array.from(
      boxRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)
    ).filter((el) => el.offsetParent !== null)
    if (items.length === 0) return
    const first = items[0]
    const last = items[items.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  if (!open) return null

  return (
    // The overlay is the scroll container: short dialogs center via auto margins,
    // tall dialogs scroll fully instead of clipping beyond the viewport.
    <div className="fixed inset-0 z-50 overflow-y-auto overscroll-contain">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-[#04070d]/85 backdrop-blur-sm transition-opacity"
        onClick={onClose}
        aria-hidden
      />

      {/* Centering wrapper — min-h-full + m-auto keeps the top reachable when
          the dialog is taller than the viewport (flex items-center would not). */}
      <div className="relative flex min-h-full p-4 sm:p-6">
        <div
          ref={boxRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          tabIndex={-1}
          onKeyDown={handleKeyDown}
          className={`relative z-10 m-auto w-full ${maxWidth} bg-surface border border-border-interactive rounded-md shadow-overlay outline-none`}
        >
        <div className="flex items-center justify-between border-b border-border px-5 py-3.5 bg-surface-3">
          <h2 id={titleId} className="font-bold text-[15px] text-text-main font-sans">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="text-text-muted hover:text-text-main transition-colors p-1 rounded-sm hover:bg-surface-2 cursor-pointer"
          >
            <X className="w-4 h-4" aria-hidden />
          </button>
        </div>

        <div className="p-5 font-sans">{children}</div>
        </div>
      </div>
    </div>
  )
}
