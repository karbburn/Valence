import type { CompanySummary } from './types'

/**
 * Ticker slug rules, shared by the server routes and the client.
 *
 * A slug is the public URL segment for one company: `NVDA`, `INFY-NYSE`,
 * `BRK.B`. It is not the company_id (`nvda_us`) and cannot be derived from the
 * ticker, because a ticker can name more than one listing and the market suffix
 * is a convention rather than a rule.
 *
 * Every function here is total: no input reaches a fetch or a company_id
 * without passing the shape gate first.
 */

/** Shape a slug may take. Narrower than the backend's company_id pattern on purpose. */
export const SLUG_PATTERN = /^[A-Za-z0-9][A-Za-z0-9.-]{0,31}$/

/**
 * First path segments that are routes, never tickers.
 *
 * A single word is indistinguishable from a ticker by shape alone, so without
 * this list `/stock` parses as a ticker called "stock". No real listing uses
 * these names, and treating one as a slug would make the index page look like a
 * broken ticker.
 */
export const RESERVED_SEGMENTS = new Set([
  'stock',
  'methodology',
  'api',
  '_next',
  'favicon.ico',
  'robots.txt',
  'sitemap.xml',
  'manifest.webmanifest',
  'icon',
  'opengraph-image',
])

/** A company as the slug resolver returns it. */
export interface ResolvedSlug extends CompanySummary {
  slug: string
  cik: string | null
  has_model: boolean
  /**
   * Whether this model's valuation may be presented, from the manifest.
   *
   * Null when there is no compiled model, which is different from false: nothing has been
   * withheld because nothing was built. The /stock index uses it to tell "opens instantly"
   * apart from "opens with a published valuation", which 14 of 23 compiled models do not.
   */
  publishable?: boolean | null
}

/** Reject before anything can reach a network call, a query, or a file path. */
export function isValidSlug(raw: string | null | undefined): boolean {
  if (typeof raw !== 'string') return false
  return SLUG_PATTERN.test(raw.trim())
}

/** Canonical form. Slugs are stored uppercase; visitors may type any case. */
export function normalizeSlug(raw: string | null | undefined): string {
  return (raw ?? '').trim().toUpperCase()
}

/** The canonical path for a ticker. One builder so no route invents its own. */
export function stockPath(slug: string): string {
  return `/stock/${encodeURIComponent(slug)}`
}

/** Absolute canonical URL, used for canonical tags, share links and JSON-LD. */
export function stockUrl(siteUrl: string, slug: string): string {
  return `${siteUrl.replace(/\/$/, '')}${stockPath(slug)}`
}

/**
 * Pull a slug out of a pathname.
 *
 * Accepts both `/stock/NVDA` and the bare `/NVDA` alias, because a popstate
 * handler has to cope with whichever form the address bar currently holds.
 *
 * A single unreserved word is returned as a candidate even if it turns out not
 * to be a ticker, because shape alone cannot tell the difference. The caller
 * resolves it against the allowlist, and that is the step that decides.
 */
export function slugFromPath(pathname: string): string | null {
  const segments = pathname.split('/').filter(Boolean)
  if (segments.length === 0) return null

  if (segments.length === 1) {
    const only = decodeURIComponent(segments[0])
    if (RESERVED_SEGMENTS.has(only.toLowerCase())) return null
    return isValidSlug(only) ? normalizeSlug(only) : null
  }

  // Only the two-segment canonical form counts. Anything deeper is some other
  // route, and guessing at its last segment would be inventing a company.
  if (segments.length !== 2) return null
  if (decodeURIComponent(segments[0]).toLowerCase() !== 'stock') return null

  const candidate = decodeURIComponent(segments[1])
  return isValidSlug(candidate) ? normalizeSlug(candidate) : null
}

/** True when the path is the bare-ticker alias that should redirect. */
export function isBareTickerPath(pathname: string): boolean {
  const segments = pathname.split('/').filter(Boolean)
  if (segments.length !== 1) return false
  const only = decodeURIComponent(segments[0])
  if (RESERVED_SEGMENTS.has(only.toLowerCase())) return false
  return isValidSlug(only)
}

/**
 * Resolve a slug to a company, or null when it is not a known ticker.
 *
 * This is the allowlist. An unknown slug must return null so the route can 404,
 * and must never be passed through to the model endpoint, which would attempt a
 * live ingestion for whatever company_id it was handed.
 */
export async function resolveSlug(slug: string): Promise<ResolvedSlug | null> {
  if (!isValidSlug(slug)) return null
  const normalized = normalizeSlug(slug)
  try {
    const res = await fetch(`/api/companies/resolve?slug=${encodeURIComponent(normalized)}`)
    if (!res.ok) return null
    return (await res.json()) as ResolvedSlug
  } catch {
    // A resolver outage must read as "not found" rather than taking the page
    // down: the workbench below can still load the model on its own.
    return null
  }
}
