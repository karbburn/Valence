'use client'

import React from 'react'

export interface LoadingOverlayProps {
  visible: boolean
  title?: string
  subtitle?: string
  /** Ticker being compiled, so the panel names the thing the reader just clicked. */
  ticker?: string
}

/**
 * The build state for one company.
 *
 * It used to be a spinner and an activity bar. Two indefinite animations, neither
 * of which carried information: a spinner says "time is passing" and an activity bar
 * says the same thing louder. On a build that runs five seconds or more, that is the
 * entire content of the screen, and a reader watching two loops has no way to judge
 * whether it is working or stuck.
 *
 * So: one indeterminate bar, which is the honest shape for work whose length is
 * unknown but whose existence is known, and copy that sets a real expectation rather
 * than advising a retry. "Retry in a few seconds" was the wrong instruction in the
 * original state because it read as advice to click again, which is the precise
 * behaviour that makes the wait longer.
 *
 * The ticker is in the title because the click was already acknowledged on the card
 * that was pressed. Naming the company here closes that loop: the reader can tell
 * the panel belongs to the thing they chose, and not to something else that happened
 * to start compiling.
 */
export function LoadingOverlay({
  visible,
  title = 'Building the model',
  subtitle,
  ticker,
}: LoadingOverlayProps) {
  if (!visible) return null

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-canvas/80 backdrop-blur-[6px] select-none"
    >
      <div className="bg-surface border border-border-interactive rounded-md p-6 max-w-sm w-full text-center shadow-overlay">
        <h3 className="font-semibold text-[14px] text-text-main">
          {ticker ? `Reading ${ticker}'s filings` : title}
        </h3>
        <p className="mt-1.5 text-[12px] text-text-muted leading-relaxed">
          {subtitle ??
            'Reading the statements, forecasting five years, and discounting the cash flows. This normally takes under ten seconds.'}
        </p>

        {/* One indeterminate bar. `indeterminate` rather than a spinner because a
            bar with a known origin reads as progress and a rotating ring does not,
            and because a single element is easier to read at a glance than two
            animating at different rhythms. */}
        <div
          className="mt-5 h-1 w-full overflow-hidden rounded-full bg-surface-2"
          aria-hidden
        >
          <div className="loading-bar h-full w-1/3 rounded-full bg-accent" />
        </div>
      </div>
    </div>
  )
}