import { Suspense } from 'react'
import type { Metadata } from 'next'
import Link from 'next/link'
import { CheckCircle2, XCircle, AlertTriangle, Minus } from 'lucide-react'
import { getManifestServer, getModelSpecServer, resolveSlugServer } from '@/lib/serverApi'
import { stockPath } from '@/lib/tickers'
import { SITE_URL, SITE_NAME, SITE_TITLE, SITE_DESCRIPTION, CONTACT_EMAIL } from '@/lib/site'
import { fmtPrice, fmtPct } from '@/lib/formatters'
import type { ModelSpecification } from '@/lib/types'
import type { ResolvedSlug } from '@/lib/tickers'
import { SiteFooter } from '@/components/SiteFooter'
import { LaunchVideo } from '@/components/landing/LaunchVideo'
import { TickerSearch } from '@/components/landing/TickerSearch'
import { LiveModelPreview } from '@/components/landing/LiveModelPreview'
import { Reveal, RevealGroup, RevealItem } from '@/components/landing/Reveal'

// Segment config must be a literal: Next reads it statically, so an imported
// constant is rejected. Keep in step with REVALIDATE_SECONDS in lib/site.ts.
export const revalidate = 3600

export const metadata: Metadata = {
  title: SITE_TITLE,
  description: SITE_DESCRIPTION,
  alternates: { canonical: SITE_URL },
  openGraph: {
    type: 'website',
    siteName: SITE_NAME,
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
    url: SITE_URL,
  },
}

/** How many tickers the rail shows, and how many models are pulled for it. */
const RAIL_LIMIT = 8
const PREVIEW_TICKER = 'NVDA'

interface RailItem {
  company: ResolvedSlug
  implied: number | null
  market: number | null
  currency: string
  deltaPct: number | null
}

function summarise(spec: ModelSpecification | null) {
  const valuation =
    spec?.valuation?.find((v) => v.scenario === 'base') ?? spec?.valuation?.[0]
  const implied = valuation?.dcf_bridge?.implied_share_price ?? null
  const market = valuation?.reverse_dcf?.market_price ?? null
  const deltaPct =
    implied != null && market ? ((implied - market) / market) * 100 : null
  return { implied, market, deltaPct, currency: spec?.metadata?.currency || 'USD' }
}

async function loadRail(): Promise<RailItem[]> {
  const page = await getManifestServer(0, 500)
  if (!page) return []

  const ready = page.companies.filter((c) => c.has_model).slice(0, RAIL_LIMIT)
  // Sequential on purpose. These are five or six large payloads against a
  // single-instance backend, and firing them together buys nothing but a
  // thundering herd against a free tier.
  const items: RailItem[] = []
  for (const company of ready) {
    const spec = await getModelSpecServer(company.company_id)
    items.push({ company, ...summarise(spec) })
  }
  return items
}

export default async function LandingPage() {
  const [rail, manifest, previewCompany] = await Promise.all([
    loadRail(),
    getManifestServer(0, 5000),
    resolveSlugServer(PREVIEW_TICKER),
  ])
  const previewSpec = previewCompany ? await getModelSpecServer(previewCompany.company_id) : null

  const readyCount = rail.filter((r) => r.deltaPct != null).length
  const totalListed = manifest?.total ?? 0
  const qa = previewSpec?.qa

  return (
    <div className="min-h-screen bg-canvas text-text-main font-sans flex flex-col">
      <SiteNav />

      <main className="flex-1">
        {/* 1. Hero, asymmetric split. Four text elements: headline, subtext, search, video caption. */}
        <section className="w-full max-w-[1400px] mx-auto px-4 sm:px-5 pt-16 sm:pt-20 lg:pt-24 pb-16 sm:pb-20">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 lg:gap-14 items-center">
            <div className="lg:col-span-7">
              <h1 className="text-[38px] sm:text-[52px] lg:text-[60px] font-bold tracking-[-0.02em] leading-[1.02] text-text-main">
                A DCF you can argue with.
              </h1>
              <p className="mt-5 text-[15px] sm:text-[16px] text-text-muted leading-relaxed max-w-[52ch]">
                Unlevered FCFF at WACC for US and Indian equities. Change any driver, export 31
                tabs, read the audit.
              </p>
              <div className="mt-7">
                <Suspense fallback={<div className="h-12 max-w-[440px] rounded-sm bg-surface border border-border" />}>
                  <TickerSearch />
                </Suspense>
              </div>
              <p className="mt-3 text-[11.5px] text-text-dim font-mono">
                {totalListed > 0
                  ? `${totalListed} companies listed across US and Indian markets`
                  : 'US and Indian markets'}
                {' · '}
                <Link href="/stock" className="text-accent hover:text-accent-hover">
                  browse all
                </Link>
              </p>
            </div>

            <div className="lg:col-span-5">
              <LaunchVideo />
            </div>
          </div>
        </section>

        {/* 2. Ticker rail. Proof with real figures rather than a claim. */}
        {rail.length > 0 && (
          <section className="border-y border-border bg-surface-2/30">
            <div className="w-full max-w-[1400px] mx-auto px-4 sm:px-5 py-12">
              <h2 className="text-[20px] sm:text-[23px] font-bold tracking-tight text-text-main">
                Open a model
              </h2>
              <p className="mt-2 text-[13.5px] text-text-muted max-w-[62ch] leading-relaxed">
                {readyCount} of these have a compiled model today. Every figure below is the
                model&apos;s own output against the last closing price.
              </p>

              <RevealGroup className="mt-6 flex gap-3 overflow-x-auto pb-3 -mx-4 px-4 snap-x snap-mandatory">
                {rail.map((item) => (
                  <RevealItem key={item.company.company_id} className="snap-start shrink-0">
                    <Link
                      href={stockPath(item.company.slug)}
                      className="group block w-[212px] bg-surface border border-border rounded-sm p-3.5 hover:border-accent-border hover:bg-surface-2 transition-colors"
                    >
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[11px] font-bold text-accent-hover bg-accent-subtle border border-accent-border rounded-sm px-1.5 py-0.5">
                          {item.company.ticker}
                        </span>
                        <span className="font-mono text-[9.5px] text-text-faint uppercase">
                          {item.company.exchange}
                        </span>
                      </div>
                      <p className="mt-2 text-[12.5px] text-text-main truncate">{item.company.name}</p>

                      {item.deltaPct != null ? (
                        <>
                          <p className="mt-3 font-mono text-[11px] text-text-dim">
                            implied{' '}
                            <span className="text-text-main">
                              {fmtPrice(item.implied!, item.currency, 2)}
                            </span>
                            <span className="mx-1 text-text-faint">vs</span>
                            <span>{fmtPrice(item.market!, item.currency, 2)}</span>
                          </p>
                          <p
                            className={`mt-1 font-mono text-[15px] font-bold ${
                              item.deltaPct >= 0 ? 'text-positive' : 'text-negative'
                            }`}
                          >
                            {item.deltaPct >= 0 ? '+' : ''}
                            {fmtPct(item.deltaPct, 1)}
                          </p>
                        </>
                      ) : (
                        <p className="mt-3 font-mono text-[11px] text-text-dim">On demand</p>
                      )}
                    </Link>
                  </RevealItem>
                ))}
              </RevealGroup>
            </div>
          </section>
        )}

        {/* 3. The model, running. Full-bleed panel, one message, no split. */}
        {previewSpec && (
          <section className="w-full max-w-[1400px] mx-auto px-4 sm:px-5 py-16 sm:py-20">
            <Reveal>
              <h2 className="text-[24px] sm:text-[30px] font-bold tracking-tight text-text-main max-w-[24ch]">
                The model, not a screenshot.
              </h2>
              <p className="mt-3 text-[14px] text-text-muted max-w-[62ch] leading-relaxed">
                This is the real component, wired to a real specification, with the scenario switch
                live. Every ticker page loads the same workbench with the model already in the HTML.
              </p>
            </Reveal>
            <Reveal className="mt-7">
              <LiveModelPreview spec={previewSpec} />
            </Reveal>
          </section>
        )}

        {/* 4. Capabilities. Grouped chunks, mono label left, one concrete line right. */}
        <section className="border-y border-border bg-surface-2/30">
          <div className="w-full max-w-[1400px] mx-auto px-4 sm:px-5 py-16 sm:py-20">
            <Reveal>
              <h2 className="text-[24px] sm:text-[30px] font-bold tracking-tight text-text-main">
                What it does
              </h2>
            </Reveal>

            <div className="mt-9 grid grid-cols-1 md:grid-cols-3 gap-x-10 gap-y-9">
              {[
                {
                  group: 'Valuation',
                  entries: [
                    ['Unlevered FCFF', 'Discounted at a live WACC build, not a preset rate'],
                    ['Three scenarios', 'Base, bull and bear, each with its own driver path'],
                    ['Reverse DCF', 'What the market price implies about the assumptions'],
                    ['Football field', 'DCF, trading comps and precedent transactions side by side'],
                  ],
                },
                {
                  group: 'Modelling',
                  entries: [
                    ['Three-statement', 'Forecast income statement, balance sheet and cash flow'],
                    ['Driver overrides', 'Every change is revertible to the model baseline'],
                    ['WACC breakdown', 'Cost of equity, cost of debt, and the weights behind them'],
                  ],
                },
                {
                  group: 'Output',
                  entries: [
                    ['Excel export', '31 tabs with live formulas, not pasted values'],
                    ['Audit engine', 'Structural checks that report their own failures'],
                    ['US and India', 'SEC EDGAR filings and NSE listed companies'],
                  ],
                },
              ].map((col) => (
                <Reveal key={col.group}>
                  <h3 className="font-mono text-[10px] uppercase tracking-[0.18em] text-text-dim pb-2 border-b border-border">
                    {col.group}
                  </h3>
                  <dl className="mt-3.5 space-y-3.5">
                    {col.entries.map(([term, detail]) => (
                      <div key={term}>
                        <dt className="font-mono text-[12px] text-text-main">{term}</dt>
                        <dd className="mt-0.5 text-[12.5px] text-text-muted leading-relaxed">
                          {detail}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* 5. The audit engine. Narrow single column. The one eyebrow on the page. */}
        {qa && (
          <section className="w-full max-w-[1400px] mx-auto px-4 sm:px-5 py-16 sm:py-20">
            <div className="max-w-[68ch]">
              <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-text-dim">
                The audit engine
              </p>
              <Reveal>
                <h2 className="mt-3 text-[24px] sm:text-[30px] font-bold tracking-tight text-text-main leading-[1.15]">
                  It reports its own failures.
                </h2>
                <p className="mt-4 text-[14px] text-text-muted leading-relaxed">
                  Every model is checked before it is served: the forecast balance sheet balances,
                  the cash flow statement articulates, peers are measured on the same basis as the
                  company they are compared to, and the WACC in the export reproduces the number in
                  the API. A check that cannot run is marked skipped, never counted as a pass.
                </p>
              </Reveal>

              <Reveal className="mt-7 border border-border rounded-sm bg-surface">
                <div className="px-3.5 py-2.5 border-b border-border bg-surface-2/60 flex items-center justify-between">
                  <span className="font-mono text-[11px] text-text-main">
                    {previewCompany?.ticker} audit report
                  </span>
                  <span className="font-mono text-[10px] text-text-dim">
                    {qa.checks?.filter((c) => c.passed).length ?? 0} of {qa.checks?.length ?? 0}{' '}
                    passed
                  </span>
                </div>
                <ul className="divide-y divide-border">
                  {(qa.checks ?? []).slice(0, 7).map((c) => {
                    const skipped = c.passed && c.detail.startsWith('SKIPPED:')
                    const Icon = skipped ? Minus : c.passed ? CheckCircle2 : XCircle
                    const colour = skipped
                      ? 'text-text-dim'
                      : c.passed
                        ? 'text-positive'
                        : 'text-negative'
                    return (
                      <li key={c.check_name} className="px-3.5 py-2.5 flex items-start gap-2.5">
                        <Icon className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${colour}`} aria-hidden />
                        <span className="min-w-0">
                          <span className="block text-[12.5px] text-text-main">{c.check_name}</span>
                          <span className="block font-mono text-[10.5px] text-text-dim leading-relaxed">
                            {c.detail}
                          </span>
                        </span>
                      </li>
                    )
                  })}
                </ul>
                {qa.checks && qa.checks.length > 7 && (
                  <p className="px-3.5 py-2.5 border-t border-border text-[11px] text-text-dim">
                    {qa.checks.length - 7} further checks run on every model.{' '}
                    <Link
                      href="/methodology#audit"
                      className="text-accent hover:text-accent-hover"
                    >
                      How the audit works
                    </Link>
                  </p>
                )}
              </Reveal>
            </div>
          </section>
        )}

        {/* 6. Coverage. The densest moment on the page, placed as the calm passage. */}
        <section className="border-t border-border bg-surface-2/30">
          <div className="w-full max-w-[1400px] mx-auto px-4 sm:px-5 py-16 sm:py-20">
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-12">
              <div className="lg:col-span-5">
                <h2 className="text-[24px] sm:text-[30px] font-bold tracking-tight text-text-main leading-[1.15]">
                  What is actually covered
                </h2>
                <p className="mt-4 text-[14px] text-text-muted leading-relaxed">
                  The engine can value any ticker it can source filings for. It does not always
                  manage to, and this page will not pretend otherwise.
                </p>
                <ul className="mt-6 space-y-3 text-[13px] text-text-muted leading-relaxed">
                  <li className="flex gap-2.5">
                    <AlertTriangle className="w-3.5 h-3.5 mt-0.5 text-warning shrink-0" aria-hidden />
                    <span>
                      A ticker with no compiled model has not had usable financial statements
                      sourced from the filings read. Its page says so rather than showing an empty
                      result.
                    </span>
                  </li>
                  <li className="flex gap-2.5">
                    <Minus className="w-3.5 h-3.5 mt-0.5 text-text-dim shrink-0" aria-hidden />
                    <span>
                      Financial sector companies are out of scope entirely. Bank and insurance
                      balance sheets do not fit an enterprise value bridge.
                    </span>
                  </li>
                  <li className="flex gap-2.5">
                    <Minus className="w-3.5 h-3.5 mt-0.5 text-text-dim shrink-0" aria-hidden />
                    <span>
                      Forecasts are the model&apos;s own arithmetic. No sell-side estimate is used
                      anywhere.
                    </span>
                  </li>
                </ul>
                <Link
                  href="/methodology#limitations"
                  className="inline-block mt-6 text-[13px] text-accent hover:text-accent-hover transition-colors"
                >
                  Full limitations
                </Link>
              </div>

              <div className="lg:col-span-7">
                <div className="border border-border rounded-sm bg-surface overflow-hidden">
                  <table className="w-full text-left border-collapse">
                    <caption className="sr-only">
                      Coverage by market, showing which companies have a compiled valuation model
                    </caption>
                    <thead>
                      <tr className="bg-surface-2/60 border-b border-border">
                        <th scope="col" className="p-3 font-mono text-[10px] uppercase tracking-[0.14em] text-text-dim font-medium">
                          Market
                        </th>
                        <th scope="col" className="p-3 font-mono text-[10px] uppercase tracking-[0.14em] text-text-dim font-medium text-right">
                          Listed
                        </th>
                        <th scope="col" className="p-3 font-mono text-[10px] uppercase tracking-[0.14em] text-text-dim font-medium text-right">
                          Ready
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {(['india', 'us'] as const).map((m) => {
                        const rows = manifest?.companies.filter((c) => c.market === m) ?? []
                        return (
                          <tr key={m}>
                            <th scope="row" className="p-3 text-[13px] font-medium text-text-main">
                              {m === 'india' ? 'India' : 'United States'}
                            </th>
                            <td className="p-3 text-right font-mono text-[13px] text-text-muted">
                              {rows.length}
                            </td>
                            <td className="p-3 text-right font-mono text-[13px] text-text-main">
                              {rows.filter((c) => c.has_model).length}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                  <p className="px-3 py-2.5 border-t border-border text-[11px] text-text-dim leading-relaxed">
                    Counts are live from the model registry, not maintained by hand. A ticker moves
                    into the ready column the first time the engine successfully builds it.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* 7. Close. One CTA, same label as the hero. */}
        <section className="w-full max-w-[1400px] mx-auto px-4 sm:px-5 py-16 sm:py-24">
          <div className="max-w-[46ch]">
            <h2 className="text-[24px] sm:text-[30px] font-bold tracking-tight text-text-main leading-[1.15]">
              Start with a ticker.
            </h2>
            <p className="mt-3 text-[14px] text-text-muted leading-relaxed">
              No account, no upload, nothing stored on a server. The model runs in the tab.
            </p>
            <div className="mt-6">
              <Suspense fallback={<div className="h-12 max-w-[440px] rounded-sm bg-surface border border-border" />}>
                <TickerSearch />
              </Suspense>
            </div>
            <p className="mt-5 text-[12px] text-text-dim">
              Prefer to read first?{' '}
              <Link href="/methodology" className="text-accent hover:text-accent-hover">
                How the valuation is built
              </Link>
              , or{' '}
              <a
                href={`mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent('Valence ticker request')}`}
                className="text-accent hover:text-accent-hover"
              >
                ask for a ticker
              </a>
              .
            </p>
          </div>
        </section>
      </main>

      <SiteFooter />
    </div>
  )
}

function SiteNav() {
  return (
    <header className="border-b border-border bg-surface/95 backdrop-blur-md sticky top-0 z-40">
      <div className="w-full max-w-[1400px] mx-auto px-4 sm:px-5 h-[56px] flex items-center justify-between">
        <Link href="/" className="font-bold text-[16px] tracking-[0.05em] text-text-main">
          Valence
        </Link>
        <nav className="flex items-center gap-5 text-[12.5px] text-text-muted">
          <Link href="/stock" className="hover:text-text-main transition-colors">
            All tickers
          </Link>
          <Link href="/methodology" className="hover:text-text-main transition-colors">
            Methodology
          </Link>
          <a
            href="https://github.com/karbburn"
            rel="noopener noreferrer"
            target="_blank"
            className="hover:text-text-main transition-colors"
          >
            GitHub
          </a>
        </nav>
      </div>
    </header>
  )
}
