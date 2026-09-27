import { permanentRedirect, notFound } from 'next/navigation'
import { isValidSlug, normalizeSlug, stockPath } from '@/lib/tickers'
import { resolveSlugServer } from '@/lib/serverApi'

export const dynamic = 'force-dynamic'

type Params = { params: Promise<{ ticker: string }> }

/**
 * Bare-ticker alias: `/NVDA` permanently redirects to `/stock/NVDA`.
 *
 * A route rather than middleware, for three reasons. It calls the same resolver
 * the canonical route uses, so the two cannot disagree about what a slug means.
 * It needs no edge bundle and no matcher, and a matcher has to guess what counts
 * as ticker-shaped, where a wrong guess is a wrong redirect. And an unrecognised
 * single segment falls through to a 404 instead of being redirected into one.
 */
export default async function TickerAliasPage({ params }: Params) {
  const { ticker } = await params

  if (!isValidSlug(ticker)) notFound()

  const slug = normalizeSlug(ticker)
  const company = await resolveSlugServer(slug)
  if (!company) notFound()

  // Redirect to the canonical slug, which also normalises case: /nvda and
  // /Nvda both land on /stock/NVDA, and /INFY-NYSE stays distinct from /INFY.
  // Permanent, because the alias never changes: a crawler should cache the
  // answer rather than re-request it on every visit.
  permanentRedirect(stockPath(company.slug))
}
