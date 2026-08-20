'use client'

import React, { useState, useEffect, useRef } from 'react'
import { RotateCcw } from 'lucide-react'
import { fmtNum, fmtPct } from '@/lib/formatters'

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
  const isDragging = useRef(false)

  useEffect(() => {
    if (!isDragging.current) {
      setLocalVal(value)
    }
  }, [value])

  const formatReadout = (v: number) => {
    if (unit === '%') return fmtPct(v, 1)
    if (unit === 'x') return `${fmtNum(v, 1)}x`
    return `${fmtNum(v, 0)} d`
  }

  // Handle immediate visual readout scrubbing
  const handleInput = (e: React.FormEvent<HTMLInputElement>) => {
    const val = parseFloat((e.target as HTMLInputElement).value)
    isDragging.current = true
    setLocalVal(val)
  }

  // Trigger debounced recompute callback on change release
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = parseFloat(e.target.value)
    isDragging.current = false
    setLocalVal(val)
    onChange(driverKey, val)
  }

  return (
    <div
      className={`rounded-[4px] px-[8px] py-[6px] transition-all select-none border ${
        isOverride
          ? 'bg-[#0d1220] border-[#0ea5e9]/40 ring-1 ring-[#0ea5e9]/20'
          : 'bg-[#0d1220] border-[#1e283d] hover:border-[#2a3652]'
      }`}
    >
      {/* Top row: Label, Override badge, Value readout, Revert button */}
      <div className="flex items-center justify-between gap-2 mb-1">
        <div className="flex items-center space-x-1.5 min-w-0">
          <span className="font-semibold text-[12px] text-[#e2e8f0] truncate">
            {label}
          </span>
          {isOverride && (
            <span className="font-bold text-[8.5px] uppercase tracking-[0.04em] bg-[#0ea5e9]/15 text-[#7dd3fc] border border-[#0ea5e9]/30 px-1.5 py-0.5 rounded-[3px] shrink-0">
              ANALYST OVERRIDE
            </span>
          )}
        </div>

        <div className="flex items-center space-x-1.5 shrink-0">
          <span className="font-mono text-[12px] font-semibold text-[#f8fafc] w-14 text-right">
            {formatReadout(localVal)}
          </span>
          {isOverride && (
            <button
              onClick={() => onRevert(driverKey)}
              title="Revert to baseline assumption"
              className="text-[#94a3b8] hover:text-[#7dd3fc] transition-colors p-0.5 rounded hover:bg-[#192030]"
            >
              <RotateCcw className="w-3 h-3" />
            </button>
          )}
        </div>
      </div>

      {/* Slider Track */}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={localVal}
        onInput={handleInput}
        onChange={handleChange}
        className="w-full h-1 bg-[#192030] rounded-lg appearance-none cursor-pointer accent-[#0ea5e9]"
      />
    </div>
  )
}
