import type { ModelSpecification } from './types'
import type { ResolvedSlug } from './tickers'
import { REVALIDATE_SECONDS } from './site'

/**
 * Server-side API access.
 *
 * Two things make this different from the browser helpers in `api.ts`:
 *
 * 1. It uses an absolute backend URL. The `/api/:path*` rewrite in
 *    next.config.ts exists for browser traffic passing through the Next server;
 *    a server component fetching a relative path has no such guarantee, and
 *    during a static build there is no request origin at all.
 *
 * 2. Every call degrades instead of throwing. A cold or sleeping free-tier
 *    backend must not fail a build, so a failed fetch yields null and the route
 *    falls back to a client-side load.
 */

const FALLBACK_API_URL = 'https://valence-backend-wu85.onrender.com'

export function apiBaseUrl(): string {
  const configured =
    process.env.NEXT_PUBLIC_API_URL ?? process.env.VALENCE_API_URL ?? FALLBACK_API_URL
  return configured.replace(/\/$/, '')
}

function endpoint(path: string): string {
  return `${apiBaseUrl()}${path}`
}

/**
 * Marks these fetches as coming from the site's own build.
 *
 * The backend budgets requests per client, and every browser call reaches it
 * through the Next server, so it sees one address for the entire internet. A
 * build looks identical, and it is the one caller that cannot be slowed down
 * without consequence: it prerenders up to PRERENDER_LIMIT tickers, and when
 * the budget refused the excess every server-side fetch degraded to null, so
 * the build still exited zero and shipped the remainder as empty shells marked
 * noindex. A silent near-total prerender failure is worse than a loud one.
 *
 * The header identifies the operator's own build, not a caller claiming to be
 * one, and the backend ignores it from any origin the operator does not
 * control.
 */
const serverFetchInit = {
  next: { revalidate: REVALIDATE_SECONDS },
  headers: { 'x-valence-build': '1' },
} as const

/**
 * Fetch a compiled model for a company. Null when unavailable.
 *
 * Null is a normal outcome, not an error: the route renders the workbench
 * without a server payload and the client fetches the model itself, which is
 * also the correct behaviour for a ticker whose first build is still running.
 */
export async function getModelSpecServer(
  companyId: string
): Promise<ModelSpecification | null> {
  try {
    const res = await fetch(endpoint(`/api/model/${encodeURIComponent(companyId)}`), serverFetchInit)
    if (!res.ok) return null
    return (await res.json()) as ModelSpecification
  } catch {
    return null
  }
}

/**
 * Resolve a slug server-side. Null when unknown or when the backend is down.
 *
 * A resolver outage is indistinguishable from an unknown slug here, and both
 * must produce a 404 rather than a page that renders an empty shell.
 */
export async function resolveSlugServer(slug: string): Promise<ResolvedSlug | null> {
  try {
    const res = await fetch(
      endpoint(`/api/companies/resolve?slug=${encodeURIComponent(slug)}`),
      serverFetchInit
    )
    if (!res.ok) return null
    return (await res.json()) as ResolvedSlug
  } catch {
    return null
  }
}

export interface ManifestPage {
  total: number
  offset: number
  limit: number
  has_more: boolean
  companies: ResolvedSlug[]
}

/** One page of the public ticker universe. */
export async function getManifestServer(
  offset = 0,
  limit = 500
): Promise<ManifestPage | null> {
  try {
    const res = await fetch(
      endpoint(`/api/companies/manifest?offset=${offset}&limit=${limit}`),
      serverFetchInit
    )
    if (!res.ok) return null
    return (await res.json()) as ManifestPage
  } catch {
    return null
  }
}

/**
 * The slugs worth prerendering at build time.
 *
 * Only companies that already have a compiled model on the server. A page
 * without one embeds no payload and gains nothing from being prerendered, and
 * prerendering the whole universe would multiply an unbounded company count by
 * a 175 KB payload.
 */
export async function getPrerenderSlugs(limit: number): Promise<string[]> {
  const page = await getManifestServer(0, 5000)
  if (!page) return []
  return page.companies
    .filter((c) => c.has_model)
    .slice(0, limit)
    .map((c) => c.slug)
}
