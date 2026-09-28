'use client'

import Link from 'next/link'
import { CONTACT_EMAIL } from '@/lib/site'

/**
 * Last-resort boundary for a page that throws while rendering.
 *
 * Without this, Next serves its own error page, which is a different site: a
 * light background, different type, no navigation, and nothing that says what
 * this is or where to go. A visitor who followed a link to a ticker and landed
 * there had no way back and no idea whether to retry.
 *
 * The message is deliberately plain about being an error. It is one, and the
 * engine is the only thing that can be fixed, so the recovery is a link rather
 * than a retry button that would fail the same way.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <div className="min-h-screen bg-canvas text-text-main font-sans flex flex-col">
      <main className="flex-1 w-full max-w-[1400px] mx-auto px-4 sm:px-5 py-20 sm:py-28">
        <div className="max-w-[62ch]">
          <h1 className="text-[26px] sm:text-[32px] font-bold tracking-tight leading-[1.15] text-balance">
            This page could not be built.
          </h1>
          <p className="mt-4 text-[14px] text-text-muted leading-relaxed">
            The engine hit an error while reading this company. That is our fault rather than
            yours, and it is worth saying so plainly rather than showing a browser error page.
          </p>
          <p className="mt-3 text-[14px] text-text-muted leading-relaxed">
            Trying again will work if it was a transient problem. If it does not, the ticker is
            worth telling us about.
          </p>

          <div className="mt-7 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={reset}
              className="h-11 px-4 rounded-sm bg-accent text-canvas text-[13px] font-semibold hover:bg-accent-hover transition-colors active:translate-y-px"
            >
              Try again
            </button>
            <Link
              href="/"
              className="h-11 px-4 inline-flex items-center rounded-sm border border-border-interactive text-[13px] text-text-muted hover:text-text-main hover:border-accent-border transition-colors"
            >
              Back to search
            </Link>
            <a
              href={`mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent('Valence error report')}`}
              className="text-[13px] text-accent hover:text-accent-hover transition-colors"
            >
              Report it
            </a>
          </div>

          {error.digest && (
            <p className="mt-6 font-mono text-[11px] text-text-faint">
              Reference {error.digest}
            </p>
          )}
        </div>
      </main>
    </div>
  )
}
