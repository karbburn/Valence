'use client'

import React from 'react'
import { Monitor } from 'lucide-react'

export function MobileGuard() {
  return (
    <div className="min-[900px]:hidden fixed inset-0 z-50 bg-[#080c14] flex flex-col items-center justify-center p-6 text-center select-none">
      <div className="max-w-sm space-y-4 flex flex-col items-center">
        <div className="w-12 h-12 bg-[#111622] border border-[#2a3652] rounded-[6px] flex items-center justify-center text-[#0ea5e9] shadow-md">
          <Monitor className="w-6 h-6" />
        </div>

        <div className="space-y-1.5">
          <h2 className="font-bold text-[16px] text-[#f8fafc]">
            Screen Too Narrow
          </h2>
          <p className="text-[12px] text-[#94a3b8] leading-relaxed">
            Valence is an institutional financial modeling terminal requiring a minimum 900px viewport for multi-column schedules.
          </p>
          <p className="text-[11px] text-[#64748b]">
            Please enlarge your browser window or switch to a desktop workstation.
          </p>
        </div>

        <div className="font-mono text-[10px] text-[#7dd3fc] bg-[#0ea5e9]/10 border border-[#0ea5e9]/20 rounded-[3px] px-2.5 py-1">
          MINIMUM VIEWPORT: 900PX
        </div>
      </div>
    </div>
  )
}
