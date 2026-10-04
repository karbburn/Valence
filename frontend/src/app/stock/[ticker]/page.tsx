import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import Workbench from '@/components/Workbench'
import { StockJsonLd } from '@/components/JsonLd'
import { getModelSpecServer, getPrerenderSlugs, resolveSlugServer } from '@/lib/serverApi'
import { isValidSlug, normalizeSlug, stockUrl } from '@/lib/tickers'
import { SITE_NAME, SITE_URL, PRERENDER_LIMIT } from '@/lib/site'
import { fmtPrice } from '@/lib/formatters'
import { mayPublishPrice, withheldReason } from '@/lib/publication'

/** Slugs are matched case-insensitively, so lowercase and uppercase must both build. */
export const dynamicParams = true
export const dynamic = 'force-dynamic'

/**
 * Rebuild at most this often. Market prices refresh daily, so an hourly window
 * keeps a page well inside that cadence without re-rendering on every visit.
 */
// Segment config must be a literal: Next reads it statically, so an imported
// constant is rejected. Keep in step with REVALIDATE_SECONDS in lib/site.ts.
export const revalidate = 3600

type Params = { params: Promise<{ ticker: string }> }

/**
 * Prerender the tickers that already have a compiled model, capped.
 *
 * Only companies the server has actually built. Each prerendered page embeds a
 * full ModelSpecification of roughly 175 KB, so this is a build-output budget
 * rather than a taste decision; everything past the cap renders on first
 * request and is then cached.
 */
export async function generateStaticParams() {
  const slugs = await getPrerenderSlugs(PRERENDER_LIMIT)
  return slugs.map((ticker) => ({ ticker }))
}

function valuationLines(spec: Awaited<ReturnType<typeof getModelSpecServer>>) {
  if (!spec) return null
  const currency = spec.metadata?.currency || 'USD'
  const valuation =
    spec.valuation?.find((v) => v.scenario === 'base') ?? spec.valuation?.[0]
  if (!valuation) return null

  const implied = valuation.dcf_bridge?.implied_share_price
  const market = valuation.reverse_dcf?.market_price
  const wacc = valuation.wacc?.wacc
  const priceDate = valuation.reverse_dcf?.market_price_date

  return {
    currency,
    implied: implied != null ? fmtPrice(implied, currency, 2) : null,
    market: market != null ? fmtPrice(market, currency, 2) : null,
    wacc: wacc != null ? `${wacc.toFixed(1)}%` : null,
    // The session the market price is the close of. Carried into the meta
    // description so a figure quoted from a search result or an answer engine
    // arrives with the date needed to check it. A valuation quoted without one
    // cannot be verified against anything, and the price it is measured against
    // moves every session.
    priceDate: priceDate ?? null,
  }
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { ticker } = await params

  if (!isValidSlug(ticker)) {
    return { title: 'Unknown ticker' }
  }

  const slug = normalizeSlug(ticker)
  const company = await resolveSlugServer(slug)

  if (!company) {
    return { title: 'Unknown ticker', robots: { index: false, follow: true } }
  }

  const spec = await getModelSpecServer(company.company_id)
  const v = valuationLines(spec)

  // The publication verdict gates the DESCRIPTION, not only the body.
  //
  // `implied_share_price` is computed for every model; the verdict decides whether it may
  // be SHOWN. This description formatted it unconditionally, so the twelve `opinion_only`
  // companies published the exact number the product says it withholds. Verified live: the
  // /stock/INFY headline reads "n/a" while its meta description read
  // "DCF implied value 1,079.32 vs 1,035.00 market".
  //
  // The meta description is the outermost surface in the product: what Google indexes, what
  // Slack and X unfurl, what an answer engine quotes. A guard applied everywhere except
  // here is not applied.
  const mayPublish = mayPublishPrice(spec)
  const reason = withheldReason(spec)

  const delta =
    mayPublish && v?.implied && v?.market
      ? ` vs ${v.market} market${v.priceDate ? ` (${v.priceDate})` : ''}`
      : ''

  // Gated on the verdict, not only on the value being present.
  //
  // `getModelSpecServer` already withholds `implied_share_price` on a withheld model,
  // so `v.implied` is null and this branch is unreachable for one. The gate is kept
  // anyway, in the same form as the other five surfaces that print the figure, because
  // the day someone serves a specification from somewhere other than that boundary the
  // description is the outermost surface in the product and must not depend on it.
  const description =
    mayPublish && v?.implied
      ? `DCF implied value ${v.implied}${delta}${v.wacc ? ` at a ${v.wacc} WACC` : ''}. Full unlevered FCFF model, three scenarios, trading comps and a 31-tab Excel export, free in the browser.`
      : reason
        ? `No valuation is published for ${company.name} (${company.ticker}). ${reason} Three-scenario unlevered FCFF model and a 31-tab Excel export, free in the browser.`
        : `Unlevered FCFF discounted cash flow valuation for ${company.name} (${company.ticker}). Three scenarios, live WACC build, trading comps and a 31-tab Excel export, free in the browser.`

  const title = `${company.name} (${company.ticker}), DCF Valuation`

  return {
    title,
    description,
    // Must be set here. The root layout declares a single canonical for the whole
    // site, and an un-overridden per-route value makes every ticker page claim
    // the homepage as canonical, which deindexes the entire feature silently.
    alternates: { canonical: stockUrl(SITE_URL, company.slug) },
    openGraph: {
      type: 'article',
      siteName: SITE_NAME,
      title,
      description,
      url: stockUrl(SITE_URL, company.slug),
    },
    twitter: {
      card: 'summary_large_image',
      title,
      description,
    },
    robots: { index: true, follow: true },
  }
}

export default async function StockTickerPage({ params }: Params) {
  const { ticker } = await params

  if (!isValidSlug(ticker)) notFound()

  const company = await resolveSlugServer(normalizeSlug(ticker))
  if (!company) notFound()

  const spec = await getModelSpecServer(company.company_id)

  return (
    <>
      <StockJsonLd company={company} spec={spec} />
      <Workbench companyId={company.company_id} initialSpec={spec} />
    </>
  )
}
