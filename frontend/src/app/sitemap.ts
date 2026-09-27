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
 */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date()
  const entries: MetadataRoute.Sitemap = [
    { url: `${SITE_URL}/`, lastModified: now, changeFrequency: 'weekly', priority: 1 },
    { url: `${SITE_URL}/stock`, lastModified: now, changeFrequency: 'daily', priority: 0.8 },
    { url: `${SITE_URL}/methodology`, lastModified: now, changeFrequency: 'monthly', priority: 0.5 },
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
      lastModified: now,
      // Prices refresh daily, so a daily signal matches the actual cadence.
      changeFrequency: 'daily',
      priority: 0.7,
    })
  }

  return entries
}
