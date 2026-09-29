import type { MetadataRoute } from 'next'
import { getManifestServer } from '@/lib/serverApi'
import { stockPath } from '@/lib/tickers'
import { SITE_URL } from '@/lib/site'

// Segment config must be a literal: Next reads it statically, so an imported
// constant is rejected. Keep in step with REVALIDATE_SECONDS in lib/site.ts.
export const revalidate = 3600

/**
 * Sitemap for the ticker universe.
 *
 * Lists only slugs the backend reports as having a compiled model. A sitemap
 * entry is a promise that the URL resolves to something, and a page whose model
 * has not been built yet renders an empty shell behind a loading overlay.
 * Because the backend writes a snapshot on every successful build, this list
 * grows on its own as real usage accumulates rather than needing to be curated.
 *
 * Last-modified is the date the page's content last actually changed.
 *
 * Every URL used to carry the moment the sitemap was generated. That is a
 * statement about all twenty-two ticker pages and three static pages changing in
 * the same millisecond, on every regeneration, forever. Last-modified is the
 * field a crawler reads to decide what is worth re-fetching, and a value that is
 * always now is either a reason to re-fetch everything or a reason to stop
 * trusting the field. Both lose the distinction the field exists to carry, and
 * the methodology page, which changes about once a quarter, was claiming to
 * change hourly.
 *
 * Ticker pages take the date the backend compiled the model. The three static
 * pages carry fixed dates, which is the honest answer for a page whose content
 * only changes when someone edits it.
 */

/** The homepage changes when a release ships or the rail gains a model. */
const HOME_LAST_MODIFIED = new Date('2026-09-29')

/** The index of every covered ticker, which grows as models are compiled. */
const STOCK_INDEX_LAST_MODIFIED = new Date('2026-09-29')

/** The methodology. It is revised when the engine's method is revised. */
const METHODOLOGY_LAST_MODIFIED = new Date('2026-09-24')

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const entries: MetadataRoute.Sitemap = [
    {
      url: `${SITE_URL}/`,
      lastModified: HOME_LAST_MODIFIED,
      changeFrequency: 'weekly',
      priority: 1,
    },
    {
      url: `${SITE_URL}/stock`,
      lastModified: STOCK_INDEX_LAST_MODIFIED,
      changeFrequency: 'daily',
      priority: 0.8,
    },
    {
      url: `${SITE_URL}/methodology`,
      lastModified: METHODOLOGY_LAST_MODIFIED,
      changeFrequency: 'monthly',
      priority: 0.5,
    },
  ]

  const first = await getManifestServer(0, 5000)
  if (!first) return entries

  const all = [...first.companies]
  let offset = 5000
  while (first.has_more && all.length < 45000) {
    const next = await getManifestServer(offset, 5000)
    if (!next || next.companies.length === 0) break
    all.push(...next.companies)
    offset += 5000
  }

  for (const company of all) {
    if (!company.has_model) continue
    entries.push({
      url: `${SITE_URL}${stockPath(company.slug)}`,
      // Falls back to the index date rather than to now when the backend has not
      // said when the model was built. A wrong-but-old date is recoverable; a
      // date that claims to be this instant is not, and a model that was built
      // before this sitemap was last generated is not new by being mentioned.
      lastModified: company.model_built_at
        ? new Date(company.model_built_at)
        : STOCK_INDEX_LAST_MODIFIED,
      // The valuation itself is stable, but the price and the benchmark it is
      // measured against move every session, so a daily signal is right.
      changeFrequency: 'daily',
      priority: 0.7,
    })
  }

  return entries
}
