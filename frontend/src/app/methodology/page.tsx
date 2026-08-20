import type { Metadata } from 'next'
import { SITE_URL, SITE_NAME } from '@/lib/site'

export const metadata: Metadata = {
  title: 'Methodology',
  description: `How ${SITE_NAME} values a company: DCF and WACC (CAPM), reverse DCF, trading comps, football-field synthesis, PE returns, and the automated QA engine.`,
  alternates: { canonical: '/methodology' },
  openGraph: {
    title: `Methodology — ${SITE_NAME}`,
    description: `How ${SITE_NAME} values a company: DCF, WACC (CAPM), reverse DCF, trading comps, football-field synthesis, PE returns, and QA.`,
    url: `${SITE_URL}/methodology`,
  },
}

export default function MethodologyPage() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-12 sm:px-6">
      <div className="flex items-center gap-2 text-accent">
        <span className="h-2 w-2 rounded-full bg-accent" />
        <span className="text-xs font-semibold uppercase tracking-[0.2em]">Methodology</span>
      </div>

      <h1 className="mt-4 text-4xl font-extrabold text-text-main">
        How {SITE_NAME} values a company
      </h1>

      <p className="mt-6 text-lg leading-relaxed text-text-muted">
        {SITE_NAME} combines an absolute valuation (DCF) with a relative valuation (trading
        comps) and a sponsor-returns view (PE), all tied out by an automated QA engine.
      </p>

      <section className="mt-10">
        <h2 className="text-2xl font-bold text-text-main">DCF (Discounted Cash Flow)</h2>
        <p className="mt-3 leading-relaxed text-text-muted">
          {SITE_NAME} builds unlevered Free Cash Flow to Firm (FCFF) and discounts it at the
          Weighted Average Cost of Capital (WACC). Two terminal-value methods are supported: a
          Gordon-growth perpetuity and an Exit EV/EBITDA multiple. Enterprise Value bridges to
          Equity Value through net debt, then to an Implied Share Price using diluted shares.
        </p>
      </section>

      <section className="mt-10">
        <h2 className="text-2xl font-bold text-text-main">WACC (CAPM)</h2>
        <p className="mt-3 leading-relaxed text-text-muted">
          The cost of equity is estimated with the Capital Asset Pricing Model (CAPM); the cost
          of debt is tax-shielded. Equity and debt are weighted at market value to produce the
          discount rate used across the model.
        </p>
      </section>

      <section className="mt-10">
        <h2 className="text-2xl font-bold text-text-main">Reverse DCF</h2>
        <p className="mt-3 leading-relaxed text-text-muted">
          Given the current market price, {SITE_NAME} inverts the DCF with a closed-form formula
          to solve for the market-implied perpetuity growth rate, and pairs it with live 2D
          sensitivity grids (WACC vs. terminal growth, and WACC vs. exit multiple).
        </p>
      </section>

      <section className="mt-10">
        <h2 className="text-2xl font-bold text-text-main">
          Trading comps &amp; football field
        </h2>
        <p className="mt-3 leading-relaxed text-text-muted">
          The target is benchmarked against sector peers on EV/Sales, EV/EBITDA, P/E, FCF Yield
          %, and ROIC %. The results are synthesized into a football-field range across
          methodologies: 52-week range, DCF perpetuity, DCF multiple, comps P/E, comps
          EV/EBITDA, and analyst consensus.
        </p>
      </section>

      <section className="mt-10">
        <h2 className="text-2xl font-bold text-text-main">PE returns &amp; IRR</h2>
        <p className="mt-3 leading-relaxed text-text-muted">
          For a sponsor view, {SITE_NAME} models a 3-year and 5-year entry and exit, returning
          Exit Equity Value, MoIC (Multiple on Invested Capital), and Equity IRR (%) under
          Base, Bull, and Bear scenarios, with entry-price sensitivity grids.
        </p>
      </section>

      <section className="mt-10">
        <h2 className="text-2xl font-bold text-text-main">Automated QA engine</h2>
        <p className="mt-3 leading-relaxed text-text-muted">
          Nine validation checks confirm model integrity: balance-sheet balancing, cash-flow
          reconciliation, debt schedule ties, share-count consistency, DCF bridge tie-out, WACC
          bounds, and data quality.
        </p>
      </section>

      <section className="mt-10">
        <h2 className="text-2xl font-bold text-text-main">Excel exporter</h2>
        <p className="mt-3 leading-relaxed text-text-muted">
          The 30-tab workbook is 100% dynamic: detail schedules drive the forecast operating
          model, with live Excel formulas (CAPM, FCFF sums, cross-sheet references, 2D
          sensitivity grids, and live =IF(...) audit checks).
        </p>
      </section>
    </main>
  )
}
