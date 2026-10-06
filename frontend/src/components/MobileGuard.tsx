'use client'

import React from 'react'
import Link from 'next/link'
import { Monitor } from 'lucide-react'

/**
 * The whole page below 900px.
 *
 * Under that width the workbench is unusable, so this is not a degraded view of
 * the model, it is the entire surface. Two things it must therefore do, and
 * previously did not.
 *
 * Say which company the visitor asked for. These URLs are the indexable surface,
 * so people arrive from a search result, and the old copy gave them no way to
 * tell whether they had landed on the right ticker.
 *
 * Offer a way onward. With nothing but a minimum-width message, a phone visitor
 * who followed a deep link was stuck, which is the worst possible outcome for the
 * one page that is meant to be linked to.
 *
 * The threshold has been wrong in both directions, which is the point of keeping this
 * comment rather than the number alone:
 *
 * - It promised 900px while the header row needed 1416px with every control inline, so
 *   between 900px and 1415px the controls ran off the right edge and the Excel export --
 *   the primary export -- was unreachable. Measured 2026-10-04.
 * - Corrected to 1163px on 2026-10-04 when the four export actions collapsed below
 *   1440px: admitting fewer widths is better than admitting widths with controls
 *   off-screen. Honest, but it walled off every 900 to 1162px visitor with a
 *   minimum-width page instead of the product.
 * - Corrected back to 900px on 2026-10-06 by compacting the row below 1163px rather
 *   than removing controls: the view tabs relocate into a labelled menu, the QA badge
 *   shows its icon, the wordmark gives its 73px back, the scenario gap number moves to
 *   the chip's tooltip. Worst-case row requirement, measured in a browser on the widest
 *   composition found (long company name at the badge's 190px cap, the longest view
 *   label, widest in-band search): 839.5px below 1024, 855.5px from 1024 to 1162.
 *   900px admits that with 60px clear, and 900 is the promise the product started with.
 *
 * The number is measured rather than round for tidiness' sake, and where a round number
 * and the measurement disagree the round one is only used when it is the larger of the
 * two -- admitting a width the layout cannot honour is the same defect as the off-screen
 * button one layer up, turned from a visible failure into an invisible one, on exactly
 * the pages people arrive at from a search result.
 *
 * 840 to 899px would fit the header alone and is deliberately not claimed: the body was
 * verified only from 900px up, and no common device lands in that band (tablets sit at
 * 810 to 834, laptops start at 1024).
 */
export function MobileGuard({
  companyName,
  ticker,
}: {
  companyName?: string
  ticker?: string
}) {
  const heading = companyName
    ? `${companyName}${ticker ? ` (${ticker})` : ''}`
    : 'A wider screen is needed'

  return (
    <div
      role="status"
      aria-live="polite"
      className="min-[900px]:hidden fixed inset-0 z-50 bg-[#080c14] flex flex-col items-center justify-center p-6 text-center select-none overflow-y-auto"
    >
      <div className="max-w-sm space-y-4 flex flex-col items-center my-auto py-8">
        <div className="w-12 h-12 bg-[#111622] border border-[#2a3652] rounded-[6px] flex items-center justify-center text-[#0ea5e9] shadow-md">
          <Monitor className="w-6 h-6" aria-hidden />
        </div>

        <div className="space-y-1.5">
          {/* The h1 for this viewport. The workbench's own heading is inside the
              app bar, which this overlay covers. */}
          <h1 className="font-bold text-[16px] text-[#f8fafc] text-balance">
            {heading}
          </h1>
          <p className="text-[12px] text-[#94a3b8] leading-relaxed">
            {companyName
              ? 'The model for this company lays out financial schedules across multiple columns. Open it on a viewport at least 900px wide to work with the figures.'
              : 'Valence lays out financial schedules across multiple columns. Open it on a viewport at least 900px wide to work with the model.'}
          </p>
        </div>

        <div className="font-mono text-[10px] text-[#7dd3fc] bg-[#0ea5e9]/10 border border-[#0ea5e9]/20 rounded-[3px] px-2.5 py-1">
          MINIMUM VIEWPORT: 900PX
        </div>

        <nav aria-label="Site" className="flex items-center gap-4 pt-1">
          <Link
            href="/stock"
            className="text-[12px] text-[#0ea5e9] hover:text-[#7dd3fc] transition-colors"
          >
            All tickers
          </Link>
          <span className="text-[#2a3652]" aria-hidden>
            /
          </span>
          <Link
            href="/"
            className="text-[12px] text-[#0ea5e9] hover:text-[#7dd3fc] transition-colors"
          >
            Home
          </Link>
        </nav>
      </div>
    </div>
  )
}
