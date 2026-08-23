'use client'

import React, { useEffect, useRef, useState } from 'react'
import { RotateCcw } from 'lucide-react'
import { fmtNum } from '@/lib/formatters'

export interface DriverSliderProps {
  driverKey: string
  label: string
  value: number
  unit: '%' | 'days' | 'x'
  min: number
  max: number
  step: number
  isOverride: boolean
  onChange: (key: string, value: number) => void
  onRevert: (key: string) => void
}

const inputId = (key: string) => `driver-${key.replace(/\./g, '-')}`

export function DriverSlider({
  driverKey,
  label,
  value,
  unit,
  min,
  max,
  step,
  isOverride,
  onChange,
  onRevert,
}: DriverSliderProps) {
  const [localVal, setLocalVal] = useState<number>(value)
  const [draftText, setDraftText] = useState<string | null>(null)
  const isDragging = useRef(false)
  const id = inputId(driverKey)

  useEffect(() => {
    if (!isDragging.current) {
      setLocalVal(value)
      setDraftText(null)
    }
  }, [value])

  const formatReadout = (v: number) => {
    if (unit === '%') return `${fmtNum(v, 1)}%`
    if (unit === 'x') return `${fmtNum(v, 1)}x`
    return `${fmtNum(v, 0)} d`
  }

  const clamp = (v: number) => Math.min(max, Math.max(min, v))

  // Immediate visual readout while scrubbing; recompute fires on release.
  const handleInput = (e: React.FormEvent<HTMLInputElement>) => {
    isDragging.current = true
    setLocalVal(parseFloat((e.target as HTMLInputElement).value))
  }

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    isDragging.current = false
    const val = parseFloat(e.target.value)
    setLocalVal(val)
    setDraftText(null)
    onChange(driverKey, val)
  }

  // Precise numeric entry: commit on Enter or blur, reject invalid drafts.
  const commitDraft = () => {
    if (draftText == null) return
    const parsed = parseFloat(draftText.replace(/[^0-9.\-]/g, ''))
    if (!Number.isNaN(parsed)) {
      const clamped = clamp(parsed)
      setLocalVal(clamped)
      onChange(driverKey, clamped)
    }
    setDraftText(null)
  }

  return (
    <div
      className={`rounded-sm px-2 py-1.5 transition-colors border ${
        isOverride
          ? 'bg-surface-3 border-accent-border'
          : 'bg-surface-3 border-border hover:border-border-interactive'
      }`}
    >
      <div className="flex items-center justify-between gap-2 mb-0.5">
        <label
          htmlFor={id}
          className="font-semibold text-[12px] text-[#e2e8f0] truncate cursor-pointer"
        >
          {label}
        </label>

        <div className="flex items-center gap-1.5 shrink-0">
          {isOverride && (
            <button
              type="button"
              onClick={() => onRevert(driverKey)}
              aria-label={`Revert ${label} to model baseline`}
              title="Revert to baseline assumption"
              className="flex items-center gap-1 font-bold text-[10px] text-text-faint hover:text-accent-hover bg-surface-2 hover:bg-surface border border-border rounded-sm px-1 py-0.5 transition-colors cursor-pointer"
            >
              <RotateCcw className="w-3 h-3" aria-hidden />
              <span>override</span>
            </button>
          )}

          <input
            type="text"
            inputMode="decimal"
            aria-label={`${label} — exact value`}
            value={draftText ?? formatReadout(localVal)}
            onChange={(e) => setDraftText(e.target.value)}
            onBlur={commitDraft}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                ;(e.target as HTMLInputElement).blur()
              }
              if (e.key === 'Escape') {
                setDraftText(null)
                ;(e.target as HTMLInputElement).blur()
              }
            }}
            className="w-[4.25rem] text-right font-mono text-[12px] font-semibold text-text-main bg-transparent border border-transparent hover:border-border rounded-sm px-1 py-0.5 focus:border-accent-border focus:bg-canvas transition-colors cursor-text"
          />
        </div>
      </div>

      <input
        id={id}
        type="range"
        className="driver-range"
        min={min}
        max={max}
        step={step}
        value={localVal}
        aria-valuetext={formatReadout(localVal)}
        onInput={handleInput}
        onChange={handleChange}
      />
    </div>
  )
}
