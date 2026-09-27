import type { Metadata } from 'next'
import Link from 'next/link'
import { SITE_URL, SITE_NAME, CONTACT_EMAIL } from '@/lib/site'
import { SiteFooter } from '@/components/SiteFooter'

export const metadata: Metadata = {
  title: 'Methodology',
  description:
    'How Valence builds a valuation: unlevered FCFF discounted at WACC, the enterprise-to-equity bridge, three scenarios, where the financial data comes from, and what the model cannot do.',
  alternates: { canonical: `${SITE_URL}/methodology` },
  openGraph: {
    title: `Methodology · ${SITE_NAME}`,
    description:
      'Unlevered FCFF at WACC, the enterprise-to-equity bridge, three scenarios, and an audit engine that reports its own failures.',
    url: `${SITE_URL}/methodology`,
  },
}

const SECTIONS = [
  { id: 'model', label: 'The model' },
  { id: 'wacc', label: 'Discount rate' },
  { id: 'bridge', label: 'Enterprise to equity' },
  { id: 'scenarios', label: 'Scenarios' },
  { id: 'data-sources', label: 'Data sources' },
  { id: 'price-provenance', label: 'Price provenance' },
  { id: 'audit', label: 'The audit engine' },
  { id: 'limitations', label: 'Limitations' },
  { id: 'disclaimer', label: 'Disclaimer' },
]

export default function MethodologyPage() {
  return (
    <div className="min-h-screen bg-canvas text-text-main font-sans flex flex-col">
      <header className="border-b border-border bg-surface/95 backdrop-blur-md sticky top-0 z-40">
        <div className="w-full max-w-[1400px] mx-auto px-4 sm:px-5 h-[56px] flex items-center justify-between">
          <Link href="/" className="font-bold text-[16px] tracking-[0.05em] text-text-main">
            Valence
          </Link>
          <nav className="flex items-center gap-4 text-[12px] text-text-muted">
            <Link href="/stock" className="hover:text-text-main transition-colors">
              All tickers
            </Link>
            <Link href="/" className="hover:text-text-main transition-colors">
              Home
            </Link>
          </nav>
        </div>
      </header>

      <main className="flex-1 w-full max-w-[1400px] mx-auto px-4 sm:px-5 py-12 sm:py-16">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-12">
          {/* Contents rail. Sticky on desktop, a wrapping row on mobile. */}
          <nav
            aria-label="On this page"
            className="lg:col-span-3 order-2 lg:order-1"
          >
            <div className="lg:sticky lg:top-[76px]">
              <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-text-dim mb-3">
                On this page
              </p>
              <ul className="flex flex-wrap gap-x-4 gap-y-1.5 lg:flex-col lg:gap-y-1.5">
                {SECTIONS.map((s) => (
                  <li key={s.id}>
                    <a
                      href={`#${s.id}`}
                      className="text-[12.5px] text-text-muted hover:text-accent transition-colors"
                    >
                      {s.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </nav>

          <article className="lg:col-span-9 order-1 lg:order-2 max-w-[72ch]">
            <h1 className="text-[30px] sm:text-[40px] font-bold tracking-tight leading-[1.1] text-text-main">
              Methodology
            </h1>
            <p className="mt-4 text-[15px] text-text-muted leading-relaxed">
              Valence computes a valuation from stated assumptions and public filings. This page
              states how that number is produced, where the inputs come from, and what the model
              cannot do. Every figure in the workbench is the output of the steps below, and you can
              change any driver and watch what it does.
            </p>

            <Section id="model" title="The model">
              <p>
                Intrinsic value is the present value of <strong>unlevered free cash flow to the
                firm</strong>, discounted at the weighted average cost of capital. FCFF is net
                operating profit after tax, plus depreciation and amortisation, less capital
                expenditure and the change in net working capital.
              </p>
              <p>
                A net income or free cash flow to equity model omits the cash a company must spend
                on capital expenditure and working capital. Those are real uses of cash, so leaving
                them out overstates what is available to shareholders.
              </p>
              <p>
                Stock-based compensation is deducted as a real economic cost. It is non-cash under
                accounting rules, but it transfers value to employees and dilutes holders, so
                treating it as free would overstate intrinsic value.
              </p>
            </Section>

            <Section id="wacc" title="Discount rate">
              <p>
                WACC is built from the capital structure and the cost of each source. The cost of
                equity comes from CAPM using a live risk-free rate, the company&apos;s own beta, and
                an equity risk premium. The cost of debt uses the company&apos;s interest expense
                against its reported borrowings, tax-effected at the effective rate.
              </p>
              <p>
                Beta, the risk-free rate and the equity risk premium are analyst-calibrated inputs
                rather than fetched values. They are surfaced in the WACC breakdown panel in the
                workbench so you can see exactly what went into the rate.
              </p>
            </Section>

            <Section id="bridge" title="Enterprise to equity">
              <p>
                The discounted cash flows give an enterprise value. Equity value is that figure
                adjusted for net debt or net cash, minority interest, and any preferred stock,
                then divided by the share count resolved from the listing structure.
              </p>
              <p>
                The bridge is shown in full in the DCF schedule, so a difference between the
                enterprise value and the equity value can be traced line by line rather than taken
                on trust.
              </p>
            </Section>

            <Section id="scenarios" title="Scenarios">
              <p>
                Every model runs three scenarios: base, bull and bear. They differ in the growth
                fade, margin path, capital intensity and working capital assumptions. The implied
                price for each is shown against the current market price, which is what the header
                strip reports.
              </p>
              <p>
                Driver overrides you set in the panel are recorded against the model-generated
                baseline, so any change can be reverted and the original value is never lost.
              </p>
            </Section>

            <Section id="data-sources" title="Data sources">
              <p>Financial statements are read from public filings and market data providers:</p>
              <ul>
                <li>
                  <strong>United States:</strong> SEC EDGAR company filings, primarily Form 10-K and
                  10-Q.
                </li>
                <li>
                  <strong>India:</strong> published financial statements for NSE and BSE listed
                  companies.
                </li>
                <li>
                  <strong>Share counts and market prices:</strong> daily closing quotes from free
                  market data providers, refreshed once per day.
                </li>
              </ul>
              <p>
                Reported line items are mapped to a canonical taxonomy before anything is
                calculated, so a line labelled differently between two filings still lands in the
                same place in the model.
              </p>
            </Section>

            <Section id="price-provenance" title="Price provenance">
              <p>
                Prices are a daily close, not a live tick. The KPI bar labels every market price
                with the date it was taken and the source it came from, and a provider that fails
                leaves the last known good quote in place marked stale rather than substituting a
                placeholder.
              </p>
              <p>
                Because a close is up to a day old, treat the implied-versus-market difference as a
                comparison against the last close, not against a real-time quote.
              </p>
            </Section>

            <Section id="audit" title="The audit engine">
              <p>
                Every model runs a set of structural checks before it is served: that the forecast
                balance sheet balances, that the cash flow statement articulates with the income
                statement, that peer multiples are measured on the same basis as the company they
                are compared to, that the enterprise bridge uses the net figure from the right
                balance sheet date, and that the WACC in the Excel export reproduces the number in
                the API.
              </p>
              <p>
                The results are in the QA panel in the header. A model with failing checks is
                served anyway, with the failures listed. The panel reports what the model got wrong
                rather than hiding it, and a check that cannot run is marked skipped rather than
                quietly counted as a pass.
              </p>
            </Section>

            <Section id="limitations" title="Limitations">
              <p>Stated plainly, because a model that overstates its reach is not useful:</p>
              <ul>
                <li>
                  Not every listed company has a model. Where financial statements cannot be
                  sourced from the filings read, no model is built and the ticker page says so
                  rather than showing an empty result.
                </li>
                <li>
                  Financial sector companies are out of scope. Bank and insurance balance sheets do
                  not fit an enterprise-value bridge, so they are excluded from the universe
                  entirely.
                </li>
                <li>
                  Forecasts are the model&apos;s own arithmetic, not consensus estimates. No
                  sell-side figure is used anywhere.
                </li>
                <li>
                  Calibrated inputs such as beta and the equity risk premium are analyst judgement,
                  not measurement. They are shown so they can be disagreed with.
                </li>
                <li>
                  Saved models are stored in your browser only. They are not uploaded, not
                  synchronised, and clearing site data removes them.
                </li>
              </ul>
            </Section>

            <Section id="disclaimer" title="Disclaimer">
              <p>
                Valence computes a valuation from stated assumptions and public filings. The output
                is the model&apos;s own arithmetic, not a view on whether to buy or sell anything.
                Assumptions are yours to change, and the model shows what each change does. Check
                the source filings before relying on any figure here.
              </p>
              <p>
                Nothing on this site is investment advice. Past performance and modelled forecasts
                do not indicate future results.
              </p>
              <p>
                Spotted a figure that looks wrong, or want a ticker covered?{' '}
                <a
                  href={`mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent('Valence feedback')}`}
                  className="text-accent hover:text-accent-hover"
                >
                  Send a note
                </a>
                .
              </p>
            </Section>
          </article>
        </div>
      </main>

      <SiteFooter />
    </div>
  )
}

function Section({
  id,
  title,
  children,
}: {
  id: string
  title: string
  children: React.ReactNode
}) {
  return (
    <section id={id} className="mt-12 scroll-mt-[76px] first:mt-14">
      <h2 className="text-[19px] font-bold tracking-tight text-text-main pb-2 border-b border-border mb-4">
        {title}
      </h2>
      <div className="space-y-3.5 text-[14px] text-text-muted leading-relaxed [&_strong]:text-text-main [&_ul]:space-y-2 [&_li]:pl-4 [&_li]:relative [&_li]:before:content-['-'] [&_li]:before:absolute [&_li]:before:left-0 [&_li]:before:text-text-faint [&_a]:underline">
      {children}
    </div>
    </section>
  )
}
