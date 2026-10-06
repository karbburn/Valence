/**
 * What a market price actually is, and what it may honestly be called.
 *
 * A valuation site that labels a daily close as "Live" is telling a reader to
 * anchor a decision on a number it believes is current to the minute. On
 * 2026-09-30 that is exactly what L&T's page did: an exchange close from
 * 2026-09-28, captioned "As of 2026-09-28 · Live".
 *
 * The backend is not confused about this. `_fetch_yfinance_history` is documented
 * as returning "a real exchange close — which is the engine's valuation basis
 * (previous close), not an intraday print", and `_fetch_yahoo_chart` as a
 * "Daily-close price". Only `_fetch_yfinance`, which reads `currentPrice` out of
 * yfinance's `.info`, and the TwelveData path can carry a current price. The
 * frontend was grouping all four together as live, so the two sources that
 * provably cannot be live were the two most likely to be shown.
 *
 * This module is the single definition, because the classification was duplicated
 * across KPIBar and QuickDCFView and had drifted: QuickDCFView matched only
 * `registry` and `market_default` as fallbacks while KPIBar also matched anything
 * beginning with `market_default`, so a suffixed fallback was called a benchmark on
 * one page and printed bare on another.
 */

export type QuoteKind =
  | 'live'        // a current price from a source that can carry one
  | 'close'       // the last exchange close: a dated figure, not an intraday print
  | 'stale'       // a cached close from a fetch that failed
  | 'benchmark'   // a placeholder, not a traded price
  | 'successor'   // real price, but for a different legal entity
  | 'undated'     // a price with no quote date at all
  | 'unclassified'

/** Sources that can return a current price. */
const LIVE_SOURCES = new Set(['yfinance', 'twelvedata'])

/** Sources documented by the backend as returning a daily close. */
const CLOSE_SOURCES = new Set(['yfinance_history', 'yahoo_chart'])

const SUCCESSOR_SUFFIX = ':successor_ticker'

/** Strip the successor marker so the base provider can be classified. */
export function baseQuoteSource(source: string | null | undefined): string | null {
  if (!source) return null
  return source.endsWith(SUCCESSOR_SUFFIX)
    ? source.slice(0, -SUCCESSOR_SUFFIX.length)
    : source
}

export function classifyQuote(
  source: string | null | undefined,
  quoteDate: string | null | undefined,
): QuoteKind {
  if (source && source.endsWith(SUCCESSOR_SUFFIX)) return 'successor'
  const base = baseQuoteSource(source)
  if (!quoteDate) return 'undated'
  if (!base) return 'undated'
  if (LIVE_SOURCES.has(base)) return 'live'
  if (CLOSE_SOURCES.has(base)) return 'close'
  if (base.startsWith('stale_cache')) return 'stale'
  if (base === 'registry' || base === 'market_default' || base.startsWith('market_default')) {
    return 'benchmark'
  }
  return 'unclassified'
}

/** The short caption shown under the price. */
export function quoteCaption(kind: QuoteKind, quoteDate: string | null | undefined): string {
  const d = quoteDate ?? 'undated'
  switch (kind) {
    case 'successor':
      return `As of ${d} · Successor ticker`
    case 'undated':
      return 'Live / Benchmark'
    case 'live':
      return `As of ${d} · Live`
    case 'close':
      // "Close", not "Live". The date is right there; the word was the problem.
      return `As of ${d} · Close`
    case 'stale':
      return `As of ${d} · Stale`
    case 'benchmark':
      return `As of ${d} · Benchmark`
    default:
      return `As of ${d}`
  }
}

/** The longer label used where there is room for it. */
export function quoteLabel(kind: QuoteKind, quoteDate: string | null | undefined): string {
  const d = quoteDate ?? 'undated'
  switch (kind) {
    case 'successor':
      return `Successor ticker · As of ${d}`
    case 'undated':
      return 'Benchmark quote'
    case 'live':
      return `Live quote · As of ${d}`
    case 'close':
      return `Daily close · As of ${d}`
    case 'stale':
      return `Stale close · As of ${d}`
    case 'benchmark':
      return `Benchmark · As of ${d}`
    default:
      return `As of ${d}`
  }
}

/** The hover explanation, which is where the distinction is actually made explicit. */
export function quoteTitle(
  kind: QuoteKind,
  quoteDate: string | null | undefined,
  baseSource: string | null | undefined,
): string {
  const d = quoteDate ?? 'an unknown date'
  switch (kind) {
    case 'successor':
      return "The listed ticker was retired by a corporate action and this quote is the successor entity. It is not comparable with this model's historical financials, so the vs-market % is suppressed."
    case 'undated':
      return 'This price carries no quote date, so treat it as indicative only.'
    case 'live':
      return `Current price from ${baseSource} as of ${d}. Company pages are served as static HTML and revalidated hourly, so the figure on screen can lag the market by up to that interval.`
    case 'close':
      return `Last exchange close from ${baseSource} on ${d}. This is a daily close, not an intraday print, and it is the basis the valuation is measured against. Pages are served as static HTML and revalidated hourly, so this figure can be up to an hour old.`
    case 'stale':
      return `The live fetch failed, so this is the last cached close from ${d}. Refresh to try again.`
    case 'benchmark':
      return `This is a benchmark placeholder from ${baseSource}, not a traded price. Treat the vs-market comparison with caution.`
    default:
      return `Price as of ${d} from ${baseSource}.`
  }
}

/** Amber flags the captions a reader should not take at face value. */
export function quoteIsFlagged(kind: QuoteKind): boolean {
  return kind === 'stale' || kind === 'benchmark' || kind === 'successor'
}
