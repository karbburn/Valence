'use client'

import React, { useState, useEffect } from 'react'
import { RotateCcw } from 'lucide-react'

export interface DriverSliderProps {
  driverKey: string
  label: string
  value: number
  unit: string
  min: number
  max: number
  step: number
  isOverride: boolean
  onChange: (key: string, val: number) => void
  onRevert?: (key: string) => void
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

  useEffect(() => {
    setLocalVal(value)
  }, [value])

  const formatDisplay = (val: number) => {
    if (unit === 'days') return `${Math.round(val)}d`
    if (unit === '%') return `${val.toFixed(2)}%`
    if (unit === 'x') return `${val.toFixed(2)}x`
    return `${val.toFixed(2)}`
  }

  const handleInput = (e: React.FormEvent<HTMLInputElement>) => {
    const nextVal = parseFloat((e.target as HTMLInputElement).value)
    if (!isNaN(nextVal)) {
      setLocalVal(nextVal)
    }
  }

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const nextVal = parseFloat(e.target.value)
    if (!isNaN(nextVal)) {
      onChange(driverKey, nextVal)
    }
  }

  return (
    <div
      className={`bg-[#0d1220] border rounded-[4px] p-[8px_10px] select-none transition-all ${
        isOverride
          ? 'border-[#0ea5e9]/40 ring-1 ring-[#0ea5e9]/20'
          : 'border-[#1e283d]'
      }`}
    >
      {/* Header: Label, Override badge, Readout, Revert */}
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center space-x-1.5 min-w-0">
          <span className="text-[12px] font-semibold text-[#e2e8f0] truncate">
            {label}
          </span>
          {isOverride && (
            <span className="text-[9px] font-bold uppercase tracking-[0.04em] text-[#7dd3fc] bg-[#0ea5e9]/10 border border-[#0ea5e9]/30 rounded-[3px] px-1 py-0.2 shrink-0">
              Override
            </span>
          )}
        </div>

        <div className="flex items-center space-x-2 shrink-0">
          <span className="font-mono text-[12px] text-[#94a3b8] w-14 text-right">
            {formatDisplay(localVal)}
          </span>
          {isOverride && onRevert && (
            <button
              onClick={() => onRevert(driverKey)}
              className="flex items-center space-x-0.5 text-[10px] font-bold text-[#ef4444] hover:text-[#fca5a5] transition-colors"
              title="Revert to model-generated value"
            >
              <RotateCcw className="w-2.5 h-2.5" />
              <span>Revert</span>
            </button>
          )}
        </div>
      </div>

      {/* Slider Track & Thumb */}
      <div className="relative flex items-center">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={localVal}
          onInput={handleInput}
          onChange={handleChange}
          className="w-full h-1.5 bg-[#1e283d] rounded-sm appearance-none cursor-pointer accent-[#0ea5e9] focus:outline-none"
        />
      </div>

      {/* Min / Max Labels */}
      <div className="flex justify-between text-[9px] font-mono text-[#475569] mt-1">
        <span>
          {min}
          {unit === '%' ? '%' : ''}
        </span>
        <span>
          {max}
          {unit === '%' ? '%' : ''}
        </span>
      </div>
    </div>
  )
}
