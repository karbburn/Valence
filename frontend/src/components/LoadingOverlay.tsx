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
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-[#080c14]/80 backdrop-blur-md select-none">
      <div className="bg-[#111622] border border-[#2a3652] rounded-[6px] p-6 max-w-md w-full text-center flex flex-col items-center shadow-xl space-y-4">
        {/* Animated Spinner */}
        <div className="w-12 h-12 rounded-full border-2 border-[#1e283d] border-t-[#0ea5e9] animate-spin" />

        {/* Title & Subtitle */}
        <div className="space-y-1">
          <h3 className="font-bold text-[14px] text-[#f8fafc]">{title}</h3>
          <p className="text-[12px] text-[#94a3b8] leading-relaxed">{subtitle}</p>
        </div>

        {/* Engine Badge */}
        <div className="flex items-center space-x-1.5 font-mono text-[10px] text-[#0ea5e9] bg-[#0ea5e9]/10 border border-[#0ea5e9]/20 rounded-[4px] px-2.5 py-1">
          <Cpu className="w-3 h-3 text-[#0ea5e9]" />
          <span>VALENCE MATRIX ENGINE</span>
          <span className="w-1.5 h-1.5 bg-[#0ea5e9] rounded-full animate-ping ml-1" />
        </div>
      </div>
    </div>
  )
}
