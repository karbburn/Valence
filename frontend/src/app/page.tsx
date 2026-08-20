import type { Metadata } from 'next'
import DashboardClient from '@/components/DashboardClient'

export const metadata: Metadata = {
  alternates: { canonical: '/' },
}

const stats = [
  { value: '30-tab', label: 'Excel model export' },
  { value: '9-point', label: 'Automated QA engine' },
  { value: 'US + India', label: 'NASDAQ/NYSE & NSE/BSE' },
  { value: '3', label: 'Base / Bull / Bear scenarios' },
]

const capabilities = [
  'Driver-based 5-year 3-statement forecasting',
  'DCF & WACC (CAPM) with dual terminal values',
  'Reverse DCF & 2D sensitivity grids',
  'Trading comps & football-field synthesis',
  'PE exit returns, MoIC & IRR waterfalls',
  'Live Excel formulas in every tab',
]

export default function HomePage() {
  return (
    <>
      {/* Server-rendered, crawlable intro — the primary GEO/SEO surface. */}
      <section className="w-full border-b border-border bg-canvas">
        <div className="mx-auto w-full max-w-[1680px] px-4 py-10 sm:px-5 sm:py-14">
          <div className="flex items-center gap-2 text-accent">
            <span className="h-2 w-2 rounded-full bg-accent" />
            <span className="text-xs font-semibold uppercase tracking-[0.2em]">
              Free · Browser-based · US + India
            </span>
          </div>

          <h1 className="mt-4 max-w-4xl text-4xl font-extrabold leading-tight text-text-main sm:text-5xl">
            Institutional-grade equity valuation, in your browser.
          </h1>

          <p className="mt-4 max-w-3xl text-base text-text-muted sm:text-lg">
            Valence is a free financial-modeling workbench that values US (NASDAQ/NYSE) and
            Indian (NSE/BSE) equities end to end — DCF and WACC, trading comps,
            football-field synthesis, PE returns, and a 30-tab Excel exporter with live
            formulas.
          </p>

          <dl className="mt-8 grid max-w-4xl grid-cols-2 gap-4 sm:grid-cols-4">
            {stats.map((s) => (
              <div
                key={s.label}
                className="rounded-lg border border-border bg-surface px-4 py-4"
              >
                <dt className="text-2xl font-bold text-text-main">{s.value}</dt>
                <dd className="mt-1 text-xs text-text-muted">{s.label}</dd>
              </div>
            ))}
          </dl>

          <ul className="mt-8 grid max-w-4xl grid-cols-1 gap-2 sm:grid-cols-2">
            {capabilities.map((c) => (
              <li key={c} className="flex items-start gap-2 text-sm text-text-muted">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                {c}
              </li>
            ))}
          </ul>
        </div>
      </section>

      <DashboardClient />
    </>
  )
}
