'use client'

import React from 'react'
import { Monitor } from 'lucide-react'

export function MobileGuard() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="min-[900px]:hidden fixed inset-0 z-50 bg-[#080c14] flex flex-col items-center justify-center p-6 text-center select-none"
    >
      <div className="max-w-sm space-y-4 flex flex-col items-center">
        <div className="w-12 h-12 bg-[#111622] border border-[#2a3652] rounded-[6px] flex items-center justify-center text-[#0ea5e9] shadow-md">
          <Monitor className="w-6 h-6" aria-hidden />
        </div>

        <div className="space-y-1.5">
          <h2 className="font-bold text-[16px] text-[#f8fafc]">
            A wider screen is needed
          </h2>
          <p className="text-[12px] text-[#94a3b8] leading-relaxed">
            Valence lays out financial schedules across multiple columns. Open it on a
            viewport at least 900px wide to work with the model.
          </p>
        </div>

        <div className="font-mono text-[10px] text-[#7dd3fc] bg-[#0ea5e9]/10 border border-[#0ea5e9]/20 rounded-[3px] px-2.5 py-1">
          MINIMUM VIEWPORT: 900PX
        </div>
      </div>
    </div>
  )
}
