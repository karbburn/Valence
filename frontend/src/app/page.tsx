import { Suspense } from 'react'
import type { Metadata } from 'next'
import Link from 'next/link'
import { getManifestServer, getModelSpecServer, resolveSlugServer } from '@/lib/serverApi'
import { stockPath } from '@/lib/tickers'
import { SITE_URL, SITE_NAME, SITE_TITLE, SITE_DESCRIPTION, CONTACT_EMAIL, OG_IMAGE } from '@/lib/site'
import { fmtPrice, fmtPct } from '@/lib/formatters'
import type { ModelSpecification } from '@/lib/types'
import type { ResolvedSlug } from '@/lib/tickers'
import { SiteFooter } from '@/components/SiteFooter'
import { LaunchVideo } from '@/components/landing/LaunchVideo'
import { TickerSearch } from '@/components/landing/TickerSearch'
import { LiveModelPreview } from '@/components/landing/LiveModelPreview'
import { Reveal, RevealGroup, RevealItem } from '@/components/landing/Reveal'

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
    images: [OG_IMAGE],
  },
}

const RAIL_LIMIT = 8
// A company whose audit is not a clean sweep. NVDA passes 10 of 10, which
// makes a section headed "it reports its own failures" look like a screenshot.
// 15 of the 22 listed companies skip at least one check, and for most of them
// it is cash_flow_reconciles: the reported cash flow statement does not
// articulate with balance sheet cash across the historical periods. That is a
// real finding, it is the reason the check exists, and showing it is the whole
// argument. Apple is the most recognisable of them.
const PREVIEW_TICKER = 'AAPL'

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

  const ready = page.companies.filter((c) => c.has_model)
  // Sequential on purpose. These are several large payloads against a
  // single-instance backend, and firing them together buys nothing but a
  // thundering herd against a free tier.
  //
  // Overshoot the limit, because a company whose DCF values equity below zero
  // is not a result and is dropped below, and the rail still has to fill.
  const items: RailItem[] = []
  for (const company of ready) {
    if (items.length >= RAIL_LIMIT) break
    const spec = await getModelSpecServer(company.company_id)
    const summary = summarise(spec)
    // A non-positive implied share price means the enterprise came out worth
    // less than its net debt, so the model is reporting a degenerate solve
    // rather than a valuation. Two listed companies are in that state, one of
    // them at -215% against market. Set beside valid results in the same
    // implied-versus-market format it reads as an opinion, and it is the same
    // mistake this page argues against elsewhere: printing a number the engine
    // could not defend. Excluded here, and the /stock index marks them.
    if (summary.implied != null && summary.implied <= 0) continue
    items.push({ company, ...summary })
  }
  return items
}

export default async function LandingPage() {
  const [rail, previewCompany] = await Promise.all([
    loadRail(),
    resolveSlugServer(PREVIEW_TICKER),
  ])
  const previewSpec = previewCompany
    ? await getModelSpecServer(previewCompany.company_id)
    : null

  const qa = previewSpec?.qa
  const checks = qa?.checks ?? []

  // A check that could not run is not a pass, and the page says so in the copy
  // directly above this report, so the number has to agree with the claim.
  //
  // The backend encodes a partial check as passed=true with the reasons appended
  // after any errors ("errors; SKIPPED: <what was missing>"), so the marker is a
  // substring, not a prefix. Testing for a prefix silently reported every partial
  // check as a clean pass.
  const isSkipped = (c: { detail?: string | null }) =>
    (c.detail ?? '').includes('SKIPPED:')
  const skippedCount = checks.filter(isSkipped).length
  const passedCount = checks.filter((c) => c.passed && !isSkipped(c)).length
  const failedCount = checks.length - passedCount - skippedCount

  return (
    <div className="min-h-screen bg-canvas text-text-main font-sans flex flex-col">
      <SiteNav />

      <main className="flex-1">
        {/* Hero. The action is a search, so the search is the hero. Left-weighted
            text against a full-bleed media band below it. */}
        {/* Hero. Asymmetric split, which is what every serious product in this
            category does: the value proposition on the left, a real artifact on
            the right. The previous arrangement stacked a 760px text block over a
            full-bleed media band, which left the right 55% of the viewport empty
            and read as a layout that failed to finish rather than as margin.

            The clip used to have to be full-bleed for legibility, because it was a
            screen recording whose KPI numerals rendered around 8px at half width.
            It is a composed title card now, built around one large figure, so it
            carries at 6 columns. Measured after the move: the 12.45% renders at
            roughly 60px, which is the point of the card.

            Six and six rather than five and seven, so the search box keeps a
            usable measure, and the headline drops to 54px so it still sets in two
            lines inside 660px. One block instead of two, so the page is six
            blocks rather than seven.

            The hero is three text elements and a field: the headline, one line of
            subtext, and the search. A fourth paragraph used to sit under the
            search explaining that the engine reads annual filings and runs its own
            checks. It was thirty words of reassurance placed directly under the
            control, where it read as a caption for the field rather than as
            anything a visitor needed in order to act, and it repeated what two
            sections below already say in full: the rail explains that a model is
            built from filings, and the audit section explains that the checks run
            before a number is shown. Cutting it also stops the page making the
            same promise three times. */}
        <section className="w-full max-w-[1400px] mx-auto px-4 sm:px-5 pt-14 sm:pt-16 lg:pt-20 pb-12 sm:pb-14">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-10 lg:gap-12 items-center">
            <div className="lg:col-span-6">
              <h1 className="text-balance text-[40px] sm:text-[50px] lg:text-[54px] font-bold tracking-[-0.025em] leading-[1.04] text-text-main">
                A DCF you can argue with.
              </h1>
              <p className="mt-5 text-[15px] sm:text-[16px] text-text-muted leading-relaxed max-w-[46ch]">
                Unlevered FCFF at WACC for US and Indian equities. Change any driver, export the
                whole workbook, read the audit.
              </p>
              <div className="mt-7">
                <Suspense
                  fallback={<div className="h-12 max-w-[440px] rounded-sm bg-surface border border-border" />}
                >
                  <TickerSearch />
                </Suspense>
              </div>
            </div>

            <div className="lg:col-span-6">
              <LaunchVideo />
            </div>
          </div>
        </section>

        {/* Rail. Real figures, and framed as what is pre-built rather than as a limit. */}
        {rail.length > 0 && (
          <section className="border-y border-border bg-surface">
            <div className="section-band w-full max-w-[1400px] mx-auto px-4 sm:px-5">
              {/* Stacked, not split. A heading on the left with the explainer
                  floating in the right column is the pattern that leaves a void
                  under the heading, and the heading carried the message on its
                  own anyway. */}
              <div className="max-w-[62ch]">
                <h2 className="text-[21px] sm:text-[24px] font-bold tracking-tight text-text-main">
                  Ready before you ask
                </h2>
                <p className="mt-3 text-[13.5px] text-text-muted leading-relaxed">
                  These are pre-built, so they open with the model already in the page. Any other
                  ticker builds on first visit, usually in a few seconds. Every figure below is
                  the model&apos;s own output against the last closing price.
                </p>
              </div>

              {/* The rail scrolls, and 380px of the last card was being sliced by
                  the viewport edge with nothing to say so. A mask on the right
                  edge fades the cut card out, which is the difference between
                  "there is more" and "this is broken". Left edge too, so the
                  fade reads as a scroller rather than as damage to one side. */}
              <RevealGroup className="rail-fade mt-7 flex gap-3 overflow-x-auto pb-3 -mx-4 px-4 snap-x snap-mandatory">
                {rail.map((item) => (
                  <RevealItem key={item.company.company_id} className="snap-start shrink-0">
                    <Link
                      href={stockPath(item.company.slug)}
                      className="group block w-[214px] bg-surface border border-border rounded-sm p-3.5 hover:border-accent-border hover:bg-surface-2 transition-colors"
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

        {/* The model, running. Full-bleed band, one message. */}
        {previewSpec && (
          <section className="section-band w-full max-w-[1400px] mx-auto px-4 sm:px-5">
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 lg:gap-12">
              <div className="lg:col-span-4">
                <h2 className="text-[24px] sm:text-[29px] font-bold tracking-tight text-text-main leading-[1.12]">
                  The model, not a screenshot.
                </h2>
                <p className="mt-4 text-[13.5px] text-text-muted leading-relaxed">
                  This is the real component, wired to a real specification, with the scenario
                  switch live. Switch bull and bear and watch the price move.
                </p>
                <p className="mt-4 text-[13.5px] text-text-muted leading-relaxed">
                  Every ticker page loads this same workbench with the model already in the HTML,
                  so the numbers are readable before any script runs.
                </p>
              </div>
              <div className="lg:col-span-8">
                <Reveal>
                  <LiveModelPreview spec={previewSpec} />
                </Reveal>
              </div>
            </div>
          </section>
        )}

        {/* What it does. Two groups: what runs in the browser, what ships in the workbook. */}
        <section className="border-y border-border bg-surface">
          <div className="section-band w-full max-w-[1400px] mx-auto px-4 sm:px-5">
            <Reveal>
              <h2 className="text-[24px] sm:text-[29px] font-bold tracking-tight text-text-main max-w-[26ch]">
                What runs in the browser, and what ships in the workbook
              </h2>
            </Reveal>

            <div className="mt-8 grid grid-cols-1 lg:grid-cols-2 gap-x-12 gap-y-10">
              <Reveal>
                <dl className="space-y-4 pt-4 border-t border-border-strong">
                  {[
                    [
                      'In the browser: unlevered FCFF DCF',
                      'Discounted at a WACC built from the company, not a preset rate',
                    ],
                    [
                      'Three scenarios',
                      'Base, bull and bear, each with its own growth, margin and capital path',
                    ],
                    [
                      'WACC in full',
                      'Risk-free rate, equity risk premium, beta, cost of debt, and the weights',
                    ],
                    [
                      'Three-statement forecast',
                      'Income statement, balance sheet and cash flow, five years out',
                    ],
                    [
                      'Driver overrides',
                      'Every change is revertible, and the model baseline is never lost',
                    ],
                    [
                      'Return ratios',
                      'Terminal ROIC, moat, first-year FCF yield, implied EV over EBIT',
                    ],
                  ].map(([term, detail]) => (
                    <div key={term}>
                      <dt className="font-mono text-[12px] text-text-main">{term}</dt>
                      <dd className="mt-0.5 text-[12.5px] text-text-muted leading-relaxed">
                        {detail}
                      </dd>
                    </div>
                  ))}
                </dl>
              </Reveal>

              <Reveal>
                <dl className="space-y-4 pt-4 border-t border-border-strong">
                  {[
                    [
                      'In the 31-tab export: trading comps',
                      'Peers measured on the same basis as the company itself',
                    ],
                    [
                      'Valuation comparison',
                      'DCF, comps and returns side by side, so the methods can be compared',
                    ],
                    ['Sensitivity', 'Two-way matrices over WACC and terminal growth'],
                    ['Investment returns', 'PE entry and exit, with IRR over the hold'],
                    [
                      'Data sources and assumption log',
                      'Every input traced to the filing line it came from',
                    ],
                    ['Model checks', 'The same audit the workbench runs, as a tab'],
                  ].map(([term, detail]) => (
                    <div key={term}>
                      <dt className="font-mono text-[12px] text-text-main">{term}</dt>
                      <dd className="mt-0.5 text-[12.5px] text-text-muted leading-relaxed">
                        {detail}
                      </dd>
                    </div>
                  ))}
                </dl>
              </Reveal>
            </div>
          </div>
        </section>

        {/* Audit. Prose left, report right. The report spans the width it needs. */}
        {qa && (
          <section className="section-band w-full max-w-[1400px] mx-auto px-4 sm:px-5">
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-12">
              <div className="lg:col-span-5">
                <Reveal>
                  <h2 className="text-[24px] sm:text-[29px] font-bold tracking-tight text-text-main leading-[1.12]">
                    It reports its own failures.
                  </h2>
                  <p className="mt-4 text-[13.5px] text-text-muted leading-relaxed">
                    Every model is checked before it is served. The forecast balance sheet has to
                    balance. The cash flow statement has to articulate with the income statement.
                    Peers have to be measured on the same basis as the company they are compared
                    to. The WACC in the export has to reproduce the number in the API.
                  </p>
                  <p className="mt-4 text-[13.5px] text-text-muted leading-relaxed">
                    A model with failing checks is served anyway, with the failures listed. A check
                    that cannot run is marked skipped, never counted as a pass.
                  </p>
                  <Link
                    href="/methodology#audit"
                    className="inline-block mt-5 text-[13px] text-accent hover:text-accent-hover transition-colors"
                  >
                    How the audit works
                  </Link>
                </Reveal>
              </div>

              <div className="lg:col-span-7">
                <Reveal className="border border-border rounded-sm bg-surface overflow-hidden">
                  <div className="px-4 py-3 border-b border-border bg-surface-2/60 flex items-center justify-between gap-3">
                    {/* Named and dated. A report headed only "AAPL audit report"
                        reads as current. Every figure on this page was struck
                        against one balance sheet on one date, and stating it is
                        the difference between a snapshot and a live number. */}
                    <span className="font-mono text-[11px] text-text-main">
                      {previewCompany?.ticker} audit report
                      {previewSpec?.valuation?.[0]?.reverse_dcf?.market_price_date && (
                        <span className="text-text-dim">
                          {' @ '}
                          {previewSpec.valuation[0].reverse_dcf.market_price_date}
                        </span>
                      )}
                    </span>
                    <span className="font-mono text-[10.5px] text-text-dim">
                      {passedCount} of {checks.length} passed
                      {skippedCount > 0 ? ` \u00b7 ${skippedCount} skipped` : ''}
                      {failedCount > 0 ? ` \u00b7 ${failedCount} failed` : ''}
                    </span>
                  </div>
                  {/* A 1px lattice rather than per-cell conditional borders. With a
                      two-column grid the last row holds one cell whenever the count
                      is odd, and index arithmetic cannot tell that apart, so the
                      bottom row picked up a border hanging off nothing. The gap
                      shows the container colour through, which is correct at any
                      count and at either breakpoint. */}
                  <ul className="grid grid-cols-1 sm:grid-cols-2 gap-px bg-border">
                    {checks.map((c) => {
                      const skipped = isSkipped(c)
                      const colour = skipped
                        ? 'text-text-dim'
                        : c.passed
                          ? 'text-positive'
                          : 'text-negative'
                      const mark = skipped ? 'SKIP' : c.passed ? 'PASS' : 'FAIL'
                      return (
                        <li
                          key={c.check_name}
                          className="bg-surface px-4 py-3 flex items-start gap-2.5 min-w-0"
                        >
                          <span
                            className={`font-mono text-[9.5px] font-bold tracking-wider mt-0.5 shrink-0 w-8 ${colour}`}
                          >
                            {mark}
                          </span>
                          <span className="min-w-0">
                            <span className="block font-mono text-[11.5px] text-text-main truncate">
                              {c.check_name}
                            </span>
                            {/* Most passing checks carry no detail, because there is
                                nothing to report. Rendering the empty element anyway
                                left a blank second line and made nine rows a
                                different height from the one that had something to
                                say. */}
                            {c.detail ? (
                              <span className="block text-[11px] text-text-dim leading-relaxed line-clamp-2">
                                {c.detail}
                              </span>
                            ) : null}
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                </Reveal>
              </div>
            </div>
          </section>
        )}

        {/* Close. A real closing band rather than a second hero: centred, so
            the action is the last thing on the page instead of sitting in a
            right-hand column with 204px of nothing under the prose. It is
            centred rather than left-aligned because a closing move wants to
            feel arrived-at, and the asymmetry the rest of the page uses reads
            as unfinished when there is nothing after it. */}
        <section className="section-band w-full max-w-[1400px] mx-auto px-4 sm:px-5">
          <div className="max-w-[620px] mx-auto text-center">
            <h2 className="text-[24px] sm:text-[29px] font-bold tracking-tight text-text-main leading-[1.12] text-balance">
              Start with a ticker.
            </h2>
            <p className="mt-4 text-[13.5px] text-text-muted leading-relaxed">
              No account, no upload, nothing stored on a server. Saved models live in this browser
              and nowhere else.
            </p>
            {/* The search is centred here, not on the component. TickerSearch is
                a max-w-[440px] block used in two places, and it is left-aligned
                in the hero because that sits in the left half of a grid. Adding
                mx-auto to the component would have centred it there too.

                Its Suspense fallback was centred, so the field appeared centred
                and then jumped 90px left the moment the client component
                hydrated. Half of the 620px container less the 440px field is
                exactly that 90px, which is how the field came to sit visibly
                left of the heading and the paragraph it belongs with. */}
            <div className="mt-6 flex justify-center">
              <Suspense
                fallback={<div className="h-12 w-full max-w-[440px] rounded-sm bg-surface border border-border" />}
              >
                <TickerSearch />
              </Suspense>
            </div>
            <p className="mt-5 text-[13px] text-text-dim leading-relaxed max-w-[52ch] mx-auto text-balance">
              Prefer to read first, or want a name covered that is not there?{' '}
              <Link href="/methodology" className="text-accent hover:text-accent-hover">
                How the valuation is built
              </Link>{' '}
              covers the model, the data sources and what it cannot do.{' '}
              <a
                href={`mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent('Valence ticker request')}`}
                className="text-accent hover:text-accent-hover"
              >
                Ask for a ticker
              </a>{' '}
              if one is missing.
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
        {/* No logo asset exists yet, so the wordmark is set as type rather than
            left as plain body text: tighter tracking and a slightly heavier
            weight so it reads as a deliberate mark, not as missing artwork. */}
        <Link
          href="/"
          className="text-[17px] font-bold tracking-[-0.01em] text-text-main leading-none"
        >
          Valence
        </Link>
        <nav className="flex items-center gap-5 text-[12.5px] text-text-muted">
          <Link href="/stock" className="hover:text-text-main transition-colors">
            All tickers
          </Link>
          <Link href="/methodology" className="hover:text-text-main transition-colors">
            Methodology
          </Link>
        </nav>
      </div>
    </header>
  )
}
