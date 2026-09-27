'use client'

import React from 'react'
import { CheckCircle2, AlertTriangle, ShieldCheck } from 'lucide-react'
import { QAResults } from '@/lib/types'
import { Modal } from './Modal'

export interface QAModalProps {
  open: boolean
  onClose: () => void
  qa: QAResults | null
}

export function QAModal({ open, onClose, qa }: QAModalProps) {
  const checks = qa?.checks || []
  const failedCount = checks.filter((c) => !c.passed).length
  const skippedCount = checks.filter(
    (c) => c.passed && c.detail.startsWith('SKIPPED:')
  ).length
  const allPassed = checks.length > 0 && failedCount === 0
  const hasWarnings = allPassed && skippedCount > 0

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Model Quality & Accounting Checks"
      maxWidth="max-w-2xl"
    >
      <div className="space-y-4">
        {/* Status Summary Banner */}
        <div
          className={`flex items-center justify-between p-3 rounded-[4px] border ${
            checks.length === 0
              ? 'bg-[#192030] border-[#1e283d] text-[#94a3b8]'
              : allPassed
              ? 'bg-[#10b981]/10 border-[#10b981]/30 text-[#10b981]'
              : 'bg-[#ef4444]/10 border-[#ef4444]/30 text-[#ef4444]'
          }`}
        >
          <div className="flex items-center space-x-2">
            {allPassed ? (
              <ShieldCheck className="w-5 h-5 text-[#10b981]" />
            ) : failedCount > 0 ? (
              <AlertTriangle className="w-5 h-5 text-[#ef4444]" />
            ) : (
              <ShieldCheck className="w-5 h-5 text-[#94a3b8]" />
            )}
            <span className="font-bold text-[13px]">
              {checks.length === 0
                ? 'No QA Checks Registered'
                : allPassed && !hasWarnings
                ? 'All Accounting & Valuation Consistency Checks Passed'
                : allPassed
                ? `Passed with ${skippedCount} Warning${skippedCount === 1 ? '' : 's'}. Review Skipped Checks.`
                : `${failedCount} of ${checks.length} Checks Failed`}
            </span>
          </div>

          <span className="text-[10px] font-mono font-semibold uppercase px-2 py-0.5 rounded-[3px] bg-[#0d1220] border border-[#1e283d]">
            {checks.length} Audited
          </span>
        </div>

        {/* Checks List */}
        <div className="space-y-2.5 max-h-[420px] overflow-y-auto pr-1">
          {checks.length === 0 ? (
            <div className="text-center py-6 text-[12px] text-text-dim">
              No QA check records available for this model.
            </div>
          ) : (
            checks.map((c, i) => (
              <div
                key={i}
                className="bg-[#080c14] border border-[#1e283d] rounded-[4px] p-3 flex items-start justify-between gap-3"
              >
                <div className="space-y-1 min-w-0">
                  <div className="flex items-center space-x-2">
                    <span className="font-semibold text-[12px] text-[#f8fafc]">
                      {c.check_name}
                    </span>
                    <span className="text-[9px] font-mono uppercase bg-[#111622] text-text-dim px-1.5 py-0.5 rounded-[2px] border border-[#1e283d]">
                      {c.category}
                    </span>
                  </div>
                  {c.detail && (
                    <p className="text-[11px] text-[#94a3b8] leading-relaxed">
                      {c.detail}
                    </p>
                  )}
                </div>

                <span
                  className={`flex items-center space-x-1 px-2 py-0.5 rounded-[3px] text-[10px] font-bold shrink-0 border ${
                    !c.passed
                      ? 'bg-[#ef4444]/10 text-[#ef4444] border-[#ef4444]/30'
                      : c.detail.startsWith('SKIPPED:')
                      ? 'bg-[#f59e0b]/10 text-[#f59e0b] border-[#f59e0b]/30'
                      : 'bg-[#10b981]/10 text-[#10b981] border-[#10b981]/30'
                  }`}
                >
                  {!c.passed ? (
                    <>
                      <AlertTriangle className="w-3 h-3 text-[#ef4444]" />
                      <span>FAIL</span>
                    </>
                  ) : c.detail.startsWith('SKIPPED:') ? (
                    <>
                      <AlertTriangle className="w-3 h-3 text-[#f59e0b]" />
                      <span>SKIPPED</span>
                    </>
                  ) : (
                    <>
                      <CheckCircle2 className="w-3 h-3 text-[#10b981]" />
                      <span>PASS</span>
                    </>
                  )}
                </span>
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end pt-2 border-t border-[#1e283d]">
          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-[#192030] hover:bg-[#2a3652] text-[#94a3b8] hover:text-[#f8fafc] border border-[#1e283d] rounded-[4px] text-[12px] font-semibold transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </Modal>
  )
}
