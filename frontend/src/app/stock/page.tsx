import { Suspense } from 'react'
import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import { getManifestServer } from '@/lib/serverApi'
import { stockPath } from '@/lib/tickers'
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
  description:
    'Every listed US and Indian ticker. Search any of them and the engine builds the model on first open; the pre-built set below opens with its figures already in place. Unlevered FCFF DCF, three scenarios and a 31-tab Excel export.',
  alternates: { canonical: `${SITE_URL}/stock` },
  openGraph: {
    title: `All tickers | ${SITE_NAME}`,
    description:
      'Every listed US and Indian ticker, searchable. The names listed are pre-built; anything else builds on first open.',
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
              Every listed US and Indian ticker
            </h1>
            <p className="mt-4 text-[14.5px] text-text-muted max-w-[58ch] leading-relaxed">
              Search any of them, or any other listed ticker, and the engine reads its filings and
              builds the model on first open. The {companies.length} below are pre-built already
              and open with their figures in place
              {withModel.length < companies.length ? (
                <>
                  {' '}
                  {withModel.length} marked{' '}
                  <span className="font-mono text-[13px] text-positive">Ready</span>, the rest
                  calculated on first open
                </>
              ) : null}
              .
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
          <Link
            href={stockPath(c.slug)}
            className="group flex items-center gap-3 bg-surface border border-border rounded-sm px-3 py-2.5 hover:border-accent-border hover:bg-surface-2 transition-colors"
          >
            <span className="font-mono text-[11px] font-bold text-accent-hover bg-accent-subtle border border-accent-border rounded-sm px-1.5 py-0.5 shrink-0">
              {c.ticker}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-[13px] font-medium text-text-main truncate">
                {c.name}
              </span>
              <span className="block font-mono text-[10px] text-text-dim truncate">
                {c.exchange} · {c.slug}
              </span>
            </span>
            {/* Only shown when it distinguishes something. When every covered
                company is already modelled, a column of identical green Ready
                chips carries no information and reads as a status light on a
                list where status is not the variable.

                "Builds on open" rather than "On demand", matching the search
                dropdown. Nothing is on demand: the engine reads the filings when
                the page is opened. A page that says "on demand" in one place and
                "builds on open" in another has made the reader reconcile two
                words for one state. */}
            {!allModelled && (
              <span
                className={`shrink-0 font-mono text-[10px] px-1.5 py-0.5 rounded-sm border ${
                  c.has_model
                    ? 'bg-positive-subtle text-positive border-positive/30'
                    : 'bg-surface-2 text-text-dim border-border'
                }`}
              >
                {c.has_model ? 'Ready' : 'Builds on open'}
              </span>
            )}
          </Link>
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
