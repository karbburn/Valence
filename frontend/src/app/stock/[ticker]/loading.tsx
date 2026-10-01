/**
 * What a reader sees while a ticker builds.
 *
 * The stock page is a Server Component that awaits the model, and for any ticker
 * outside the prebuilt set that await is a full ingestion against live sources:
 * about seven seconds cold. Without this file the browser sits on a blank response
 * for all of it, which reads as a broken link rather than as work in progress.
 *
 * The shape is the point. This mirrors the two regions the real page renders, the
 * seven-card KPI strip and the drivers-plus-schedule body, so the content arrives
 * into a frame that already has the right outline and nothing jumps. A centred
 * spinner would not: it implies the page is coming as one block when in fact the
 * header is ready long before the numbers are.
 *
 * The line of text is deliberately specific. "Loading" tells a reader nothing about
 * a seven-second wait; naming the work and giving a bound is what makes the wait
 * legible. Measured cold at roughly 7s, so "usually under 10 seconds" is honest
 * rather than reassuring.
 */

const KPI_CARDS = [
  { label: 'DCF implied price', wide: false },
  { label: 'Market price', wide: false },
  { label: 'Statements', wide: false },
  { label: 'Enterprise value', wide: false },
  { label: 'Equity value', wide: false },
  { label: 'WACC', wide: false },
  { label: 'Terminal growth (G)', wide: false },
]

function KpiSkeleton({ label }: { label: string }) {
  return (
    <div
      aria-hidden="true"
      className="rounded-lg border border-[var(--c-border)] bg-[var(--c-surface)] px-4 py-3"
    >
      <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--c-text-3)]">
        {label}
      </div>
      <div className="skeleton-bar mt-2 h-7 w-24 rounded" />
      <div className="skeleton-bar mt-2 h-3 w-20 rounded" />
    </div>
  )
}

function Bar({ className }: { className: string }) {
  return <div aria-hidden="true" className={`skeleton-bar rounded ${className}`} />
}

export default function Loading() {
  return (
    <div className="min-h-screen bg-[var(--c-canvas)]">
      {/* Header strip. Real chrome, muted, so the page is recognisable while it loads. */}
      <header className="sticky top-0 z-20 border-b border-[var(--c-border)] bg-[var(--c-surface-3)]">
        <div className="mx-auto flex max-w-[1800px] flex-wrap items-center gap-3 px-4 py-2.5">
          <span className="text-[15px] font-bold tracking-tight text-[var(--c-text)]">
            Valence
          </span>
          <Bar className="h-8 w-56" />
          <div className="ml-auto flex items-center gap-3">
            <Bar className="h-7 w-16" />
            <Bar className="h-7 w-16" />
            <Bar className="h-7 w-16" />
            <Bar className="h-7 w-20" />
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1800px] px-4 py-4">
        {/* The work in progress, stated plainly. */}
        <div
          role="status"
          aria-live="polite"
          className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-[var(--c-accent-border)] bg-[var(--c-accent-subtle)] px-4 py-3"
        >
          {/* No status dot here.
           *
           * It pulsed, so it read as a live indicator, which means it was claiming to
           * report something. It was not: it pulsed on a timer whether the build was
           * progressing or wedged. And it was redundant, because the skeleton grid
           * directly below it is the real progress signal, laid out where the figures
           * will land. One honest indicator, not a decorative one standing in front of
           * a real one. */}
          <span className="text-sm font-medium text-[var(--c-text)]">
            Building the model
          </span>
          <span className="text-sm text-[var(--c-text-2)]">
            Reading this company&apos;s statements and building the valuation. Usually
            under 10 seconds.
          </span>
        </div>

        {/* KPI strip, same count and order as the real page. */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
          {KPI_CARDS.map((card) => (
            <KpiSkeleton key={card.label} label={card.label} />
          ))}
        </div>

        {/* Drivers panel and schedule, in the proportions the page renders. */}
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(340px,1fr)_minmax(0,2fr)]">
          <section className="rounded-lg border border-[var(--c-border)] bg-[var(--c-surface)] p-4">
            <div className="flex items-center justify-between">
              <Bar className="h-4 w-32" />
              <Bar className="h-5 w-24" />
            </div>
            <div className="mt-4 space-y-3">
              {[0, 1, 2, 3, 4, 5].map((row) => (
                <div key={row} className="rounded-md border border-[var(--c-border)] p-3">
                  <Bar className="h-3 w-28" />
                  <Bar className="mt-3 h-1.5 w-full" />
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-lg border border-[var(--c-border)] bg-[var(--c-surface)] p-4">
            <div className="flex items-center justify-between">
              <Bar className="h-4 w-40" />
              <Bar className="h-5 w-28" />
            </div>
            <div className="mt-4 space-y-2">
              {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((row) => (
                <div key={row} className="flex items-center gap-3">
                  <Bar className="h-3 w-40 shrink-0" />
                  {[0, 1, 2, 3, 4].map((col) => (
                    <Bar key={col} className="h-3 flex-1" />
                  ))}
                </div>
              ))}
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}
