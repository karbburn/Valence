import type { Metadata } from 'next'
import { SITE_URL, SITE_NAME, AUTHOR, SOCIAL } from '@/lib/site'

export const metadata: Metadata = {
  title: 'About',
  description: `What ${SITE_NAME} is, who it is for, the markets it covers, and how it is built. ${SITE_NAME} is a free, browser-based equity-valuation and financial-modeling workbench for US and Indian equities.`,
  alternates: { canonical: '/about' },
  openGraph: {
    title: `About ${SITE_NAME}`,
    description: `${SITE_NAME} is a free, browser-based equity-valuation and financial-modeling workbench for US and Indian equities.`,
    url: `${SITE_URL}/about`,
  },
}

export default function AboutPage() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-12 sm:px-6">
      <div className="flex items-center gap-2 text-accent">
        <span className="h-2 w-2 rounded-full bg-accent" />
        <span className="text-xs font-semibold uppercase tracking-[0.2em]">About</span>
      </div>

      <h1 className="mt-4 text-4xl font-extrabold text-text-main">
        What is {SITE_NAME}?
      </h1>

      <p className="mt-6 text-lg leading-relaxed text-text-muted">
        {SITE_NAME} is a free, browser-based equity-valuation platform and 3-statement
        financial-modeling workbench for public companies in the United States and India. It
        lets an analyst value a business end to end without leaving the browser: search a
        ticker, inspect a normalized three-statement model, override operating drivers, and
        instantly recompute a full discounted-cash-flow and relative-valuation analysis.
      </p>

      <h2 className="mt-10 text-2xl font-bold text-text-main">Who it is for</h2>
      <p className="mt-3 leading-relaxed text-text-muted">
        Equity research analysts, investors, and finance students who want institutional-grade
        valuation mechanics — DCF, WACC, trading comps, and PE returns — without standing up a
        spreadsheet or a paid terminal.
      </p>

      <h2 className="mt-10 text-2xl font-bold text-text-main">Markets & currencies</h2>
      <p className="mt-3 leading-relaxed text-text-muted">
        {SITE_NAME} supports US equities (NASDAQ/NYSE, reported in USD millions) and Indian
        equities (NSE/BSE, reported in INR crores), with dynamic currency and unit localization
        across every financial statement.
      </p>

      <h2 className="mt-10 text-2xl font-bold text-text-main">What it does</h2>
      <ul className="mt-3 space-y-2 text-text-muted">
        <li>• Driver-based 5-year forecasting across Base, Bull, and Bear scenarios.</li>
        <li>• DCF &amp; WACC buildup with Gordon-growth and exit-multiple terminal values.</li>
        <li>• Reverse DCF growth solvers and live 2D sensitivity grids.</li>
        <li>• Trading comps and football-field valuation-range synthesis.</li>
        <li>• PE exit returns, MoIC, and IRR waterfalls.</li>
        <li>• A 9-point automated accounting and model QA engine.</li>
        <li>• A 30-tab Excel exporter with live, dynamic formulas.</li>
      </ul>

      <h2 className="mt-10 text-2xl font-bold text-text-main">Technology</h2>
      <p className="mt-3 leading-relaxed text-text-muted">
        The core engine is Python 3.12 with Pydantic v2. The web API is FastAPI served with
        Uvicorn, the Excel renderer uses OpenPyXL and Pillow, and data is persisted in SQLite.
        The web dashboard is a Next.js application with a custom dark-theme design system.
      </p>

      <h2 className="mt-10 text-2xl font-bold text-text-main">Author</h2>
      <p className="mt-3 leading-relaxed text-text-muted">
        {SITE_NAME} is built by {AUTHOR.name}. Source code is available on{' '}
        <a
          href={SOCIAL.github}
          className="text-accent underline underline-offset-4"
          rel="noopener noreferrer"
          target="_blank"
        >
          GitHub
        </a>
        .
      </p>
    </main>
  )
}
