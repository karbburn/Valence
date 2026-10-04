'use client'

import Link from 'next/link'
import { usePendingNavigation } from '@/lib/usePendingNavigation'
import { stockPath } from '@/lib/tickers'

interface Props {
  companyId: string
  slug: string
  ticker: string
  name: string
  exchange: string
  hasModel: boolean
  /**
   * Whether this model's valuation may be presented, or only its evidence.
   *
   * Null when there is no compiled model at all. The chip used to read "Ready" for
   * every compiled model, and 14 of the 23 compiled models open on a page that
   * publishes no valuation. On a list of 161 rows that read as "25 published
   * valuations" when the truth was 9, which is the product's central claim
   * overstated by the surface meant to support it.
   */
  publishable?: boolean | null
  /** When every covered company is already modelled, a column of identical "Ready"
   *  chips carries no information and reads as a status light on a list where
   *  status is not the variable, so the chip is dropped entirely. */
  showStatusChip: boolean
}

/**
 * One company on the coverage list, and the first thing on this page to acknowledge
 * a click.
 *
 * The destination takes five seconds or more, because it compiles the model before
 * it renders anything. Without a pending state the card simply does not change, and
 * a visitor cannot distinguish a navigation in progress from a dropped click, so
 * they click again. A second click is a second model build competing with the first
 * for the same throttle, so the retry makes the wait worse rather than shorter.
 *
 * Marking only the card that was activated is the point. Dimming all of them would
 * acknowledge something happened without saying which of the twenty rows they chose.
 */
export default function CompanyCard({
  companyId,
  slug,
  ticker,
  name,
  exchange,
  hasModel,
  publishable,
  showStatusChip,
}: Props) {
  const { navigate, pendingTo } = usePendingNavigation()
  const isPending = pendingTo === companyId

  return (
    <Link
      href={stockPath(slug)}
      onClick={(e) => {
        // Let the browser keep modified clicks (new tab, download).
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
        e.preventDefault()
        navigate(stockPath(slug), companyId)
      }}
      aria-busy={isPending}
      aria-current={isPending ? 'true' : undefined}
      className={`group flex items-center gap-3 bg-surface border rounded-sm px-3 py-2.5 transition-colors ${
        isPending
          ? 'border-accent-border bg-surface-2 opacity-70'
          : 'border-border hover:border-accent-border hover:bg-surface-2'
      }`}
    >
      <span className="font-mono text-[11px] font-bold text-accent-hover bg-accent-subtle border border-accent-border rounded-sm px-1.5 py-0.5 shrink-0">
        {ticker}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[13px] font-medium text-text-main truncate">
          {name}
        </span>
        <span className="block font-mono text-[10px] text-text-dim truncate">
          {exchange} · {slug}
        </span>
      </span>
      {/* The chip swaps to the state of the thing they just clicked. A spinner here
          would be worse than nothing: it animates whether or not the build is
          actually progressing, and on a page full of rows it turns twenty idle
          loops into one page of noise. A label that changes and then goes away is
          honest and is still. */}
      {isPending ? (
        <span className="shrink-0 font-mono text-[10px] px-1.5 py-0.5 rounded-sm border border-accent-border bg-accent-subtle text-accent-hover">
          Opening
        </span>
      ) : (
        showStatusChip && (
          <span
            className={`shrink-0 font-mono text-[10px] px-1.5 py-0.5 rounded-sm border ${
              !hasModel
                ? 'bg-surface-2 text-text-dim border-border'
                : publishable
                  ? 'bg-positive-subtle text-positive border-positive/30'
                  : 'bg-[#f59e0b]/10 text-[#f59e0b] border-[#f59e0b]/30'
            }`}
            title={
              hasModel && !publishable
                ? 'The model is built and opens with its figures. Its valuation is not ' +
                  'published, and the page names the check that stopped it.'
                : undefined
            }
          >
            {/* Three states, because "Ready" answered a question nobody asked and hid
                the one they did. Ready to open, and ready to publish a valuation, are
                different claims, and 14 of 23 rows could only make the first. */}
            {!hasModel ? 'Builds on open' : publishable ? 'Published' : 'Withheld'}
          </span>
        )
      )}
    </Link>
  )
}