import { Suspense } from 'react'
import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import { getManifestServer } from '@/lib/serverApi'
import CompanyCard from '@/components/CompanyCard'
import { SITE_URL, SITE_NAME, OG_IMAGE, CONTACT_EMAIL } from '@/lib/site'
import type { ResolvedSlug } from '@/lib/tickers'
import { TickerSearch } from '@/components/landing/TickerSearch'
import { SiteFooter } from '@/components/SiteFooter'

// Segment config must be a literal: Next reads it statically, so an imported
// constant is rejected. Keep in step with REVALIDATE_SECONDS in lib/site.ts.
export const revalidate = 3600

const PAGE_SIZE = 500

export const metadata: Metadata = {
  title: `All tickers`,
  // Counts are not interpolated here. The page knows them and states them in the copy
  // below, and a number that changes on every rebuild is not something to freeze into a
  // crawler's cache. What the description must not do is promise figures for every row,
  // which is what "the pre-built set opens with its figures already in place" did for the
  // fourteen whose valuation is withheld.
  description:
    'Search every listed US and Indian ticker. Search any of them and the engine builds the model on first open. Each row states whether its valuation is published or withheld, and a withheld model opens with its full statements, its audit, and the check that stopped it. Unlevered FCFF DCF, three scenarios and a 31-tab Excel export.',
  alternates: { canonical: `${SITE_URL}/stock` },
  openGraph: {
    title: `All tickers | ${SITE_NAME}`,
    description:
      'Every listed US and Indian ticker, searchable. Each row states whether its valuation is published or withheld; anything not pre-built is calculated on first open.',
    url: `${SITE_URL}/stock`,
    images: [OG_IMAGE],
  },
}

async function loadAll(): Promise<ResolvedSlug[]> {
  const first = await getManifestServer(0, PAGE_SIZE)
  if (!first) return []

  const all = [...first.companies]
  let offset = PAGE_SIZE
  // Page through rather than assuming one request covers the universe. A single
  // oversized request is exactly the kind of thing that starts failing quietly
  // once the ticker count grows.
  while (first.has_more && all.length < 5000) {
    const next = await getManifestServer(offset, PAGE_SIZE)
    if (!next || next.companies.length === 0) break
    all.push(...next.companies)
    offset += PAGE_SIZE
  }
  return all
}

export default async function StockIndexPage() {
  const companies = await loadAll()
  if (companies.length === 0) notFound()

  const withModel = companies.filter((c) => c.has_model)
  const allModelled = withModel.length === companies.length
  const published = withModel.filter((c) => c.publishable === true)
  const withheld = withModel.filter((c) => c.publishable === false)
  const india = companies.filter((c) => c.market === 'india')
  const us = companies.filter((c) => c.market === 'us')

  return (
    <div className="min-h-screen bg-canvas text-text-main font-sans">
      <SiteHeader />

      <main className="w-full max-w-[1400px] mx-auto px-4 sm:px-5 py-10 sm:py-14">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-12">
          <div className="lg:col-span-7">
            {/* The engine covers every listed US and Indian ticker, so the page
                says that. What is listed below is the pre-built set, which is a
                convenience, and the count is stated rather than implied so the
                two are never confused. The pre-session copy said "All tickers";
                narrowing it to "a curated list, not the whole market" described
                a current limitation as if it were the product. */}
            <h1 className="text-[30px] sm:text-[38px] font-bold tracking-tight leading-[1.08] text-text-main">
              Search every listed US and Indian ticker
            </h1>
            <p className="mt-4 text-[14.5px] text-text-muted max-w-[58ch] leading-relaxed">
              Search any of them, or any other listed ticker, and the engine reads its filings
              and builds the model on first open. Of the {companies.length} below,{' '}
              {withModel.length} are pre-built already
              {withheld.length > 0 ? (
                <>
                  , of which{' '}
                  <span className="font-mono text-[13px] text-positive">{published.length}</span>{' '}
                  carry a published valuation and{' '}
                  <span className="font-mono text-[13px] text-warning">{withheld.length}</span>{' '}
                  are marked Withheld. A withheld model opens with its full statements and
                  audit, and names the check that stopped the engine presenting its result as
                  a valuation
                </>
              ) : null}
              {withModel.length < companies.length ? (
                <>. The rest are calculated on first open</>
              ) : (
                <>.</>
              )}
            </p>
            <p className="mt-3 text-[13px] leading-relaxed">
              Looking for something that is not resolving?{' '}
              <a
                href={`mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent('Request a ticker')}`}
                className="text-accent hover:text-accent-hover transition-colors"
              >
                Ask for a ticker
              </a>{' '}
              and it will be added.
            </p>
          </div>
          <div className="lg:col-span-5">
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-text-dim mb-3">
              Search any listed ticker
            </p>
            <Suspense fallback={<div className="h-12 rounded-sm bg-surface border border-border" />}>
              <TickerSearch />
            </Suspense>
            <p className="mt-2.5 text-[11.5px] text-text-dim leading-relaxed">
              Search covers the whole listed universe, not just the names below. If a model cannot
              be built from the filings available, the page says so rather than showing an empty
              result.
            </p>
          </div>
        </div>

        <section className="mt-12">
          <h2 className="font-mono text-[10px] uppercase tracking-[0.18em] text-text-dim pb-2 border-b border-border">
            India ({india.length})
          </h2>
          <TickerGrid companies={india} allModelled={allModelled} />
        </section>

        <section className="mt-10">
          <h2 className="font-mono text-[10px] uppercase tracking-[0.18em] text-text-dim pb-2 border-b border-border">
            United States ({us.length})
          </h2>
          <TickerGrid companies={us} allModelled={allModelled} />
        </section>
      </main>

      {/* This route was the only public page without the footer, so it shipped
          without the legal line, the data-provenance note, or the profile links.
          Those are the statements that make the figures on the page
          attributable, which matters most on the index where the figures are
          densest. */}
      <SiteFooter />
    </div>
  )
}

function TickerGrid({
  companies,
  allModelled,
}: {
  companies: ResolvedSlug[]
  allModelled: boolean
}) {
  return (
    <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
      {companies.map((c) => (
        <li key={c.company_id}>
          <CompanyCard
            companyId={c.company_id}
            slug={c.slug}
            ticker={c.ticker}
            name={c.name}
            exchange={c.exchange}
            hasModel={c.has_model}
            publishable={c.publishable}
            showStatusChip={!allModelled}
          />
        </li>
      ))}
    </ul>
  )
}

function SiteHeader() {
  return (
    <header className="border-b border-border bg-surface/95 backdrop-blur-md sticky top-0 z-40">
      <div className="w-full max-w-[1400px] mx-auto px-4 sm:px-5 h-[56px] flex items-center justify-between">
        <Link href="/" className="font-bold text-[16px] tracking-[0.05em] text-text-main">
          Valence
        </Link>
        <nav className="flex items-center gap-4 text-[12px] text-text-muted">
          <Link href="/" className="hover:text-text-main transition-colors">
            Home
          </Link>
          <Link href="/methodology" className="hover:text-text-main transition-colors">
            Methodology
          </Link>
        </nav>
      </div>
    </header>
  )
}
