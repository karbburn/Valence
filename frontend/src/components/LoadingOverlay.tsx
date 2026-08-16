'use client'

import React from 'react'
import { Cpu } from 'lucide-react'

export interface LoadingOverlayProps {
  visible: boolean
  title?: string
  subtitle?: string
}

export function LoadingOverlay({
  visible,
  title = 'Compiling Valuation Model',
  subtitle = 'Ingesting live financial statements, normalizing taxonomy, and solving DCF & WACC matrices...',
}: LoadingOverlayProps) {
  if (!visible) return null

  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-[#080c14]/75 backdrop-blur-[12px] select-none transition-all duration-300">
      {/* Loading Modal Box */}
      <div className="relative bg-[#111622]/90 border border-[#2a3652]/60 rounded-[6px] p-6 max-w-md w-full text-center flex flex-col items-center shadow-[0_0_50px_rgba(14,165,233,0.12)] space-y-5 overflow-hidden">
        {/* Subtle top reflection line */}
        <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-[#0ea5e9]/50 to-transparent" />

        {/* High-Fidelity Multi-Ring Spinner */}
        <div className="relative w-16 h-16 flex items-center justify-center">
          {/* Outer ring - spins clockwise */}
          <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-[#0ea5e9] border-b-[#7dd3fc] animate-[spin_1.4s_linear_infinite]" />
          
          {/* Inner ring - spins counter-clockwise */}
          <div className="absolute inset-2 rounded-full border-2 border-transparent border-l-[#0ea5e9]/60 border-r-[#7dd3fc]/60 animate-[spin_0.8s_linear_infinite_reverse]" />
          
          {/* Pulsing center background aura */}
          <div className="absolute inset-4 rounded-full bg-[#0ea5e9]/10 animate-pulse blur-xs" />
          
          {/* Center CPU Icon */}
          <Cpu className="w-5 h-5 text-[#0ea5e9] z-10 animate-[pulse_1.5s_ease-in-out_infinite]" />
        </div>

        {/* Title & Subtitle */}
        <div className="space-y-1.5 px-2">
          <h3 className="font-bold text-[14px] text-[#f8fafc] tracking-wide">
            {title}
          </h3>
          <p className="text-[12px] text-[#94a3b8] leading-relaxed font-sans">
            {subtitle}
          </p>
        </div>

        {/* Engine Badge with status indicators */}
        <div className="flex items-center space-x-2 font-mono text-[9px] tracking-[0.08em] text-[#7dd3fc] bg-[#0ea5e9]/10 border border-[#0ea5e9]/20 rounded-[4px] px-3 py-1">
          <Cpu className="w-3.5 h-3.5 text-[#0ea5e9]" />
          <span>VALENCE MATRIX ENGINE</span>
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#10b981] opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-[#10b981]"></span>
          </span>
        </div>
      </div>
    </div>
  )
}
