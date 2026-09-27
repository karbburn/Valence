import Link from 'next/link'
import { SOCIAL, CONTACT_EMAIL } from '@/lib/site'

const EXPLORE = [
  { href: '/stock', label: 'All tickers' },
  { href: '/methodology', label: 'Methodology' },
  { href: '/methodology#data-sources', label: 'Data sources' },
  { href: '/methodology#limitations', label: 'Model limitations' },
]

/**
 * Site footer.
 *
 * Three columns and no policies column. Every policy on a typical footer exists
 * to cover sign-in, accounts or tracking, and this product has none of those:
 * no auth, no accounts, no cookies, no analytics, no third-party scripts. A
 * column of links to policies nobody wrote would be worse than no column,
 * because on a product whose entire value is auditability it reads as noise.
 *
 * What replaces it is the question a reader actually has before trusting a
 * valuation number: where did the figures come from, and what can the model not
 * do. That content already exists and is linked rather than restated.
 */
export function SiteFooter() {
  return (
    <footer className="border-t border-border bg-surface-2/40 mt-auto">
      <div className="w-full max-w-[1400px] mx-auto px-4 sm:px-5">
        <div className="grid grid-cols-1 md:grid-cols-[1.5fr_1fr_1fr] gap-10 py-12">
          {/* Identity */}
          <div>
            <div className="flex items-baseline gap-2.5">
              <span className="font-bold text-[17px] tracking-[0.05em] text-text-main">
                Valence
              </span>
              <span className="font-mono text-[10px] text-text-dim">
                equity valuation workbench
              </span>
            </div>
            <p className="mt-3 text-[12.5px] text-text-muted leading-relaxed max-w-[38ch]">
              Equity valuation and 3-statement modelling for US and Indian listed companies. Runs
              in the browser, exports to Excel, and shows its working.
            </p>
          </div>

          {/* Explore */}
          <nav aria-labelledby="footer-explore">
            <h2
              id="footer-explore"
              className="font-mono text-[10px] uppercase tracking-[0.18em] text-text-dim"
            >
              Explore
            </h2>
            <ul className="mt-3.5 space-y-2">
              {EXPLORE.map((l) => (
                <li key={l.href}>
                  <Link
                    href={l.href}
                    className="text-[12.5px] text-text-muted hover:text-text-main hover:underline underline-offset-2 transition-colors"
                  >
                    {l.label}
                  </Link>
                </li>
              ))}
              <li>
                <a
                  href={`mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent('Valence ticker request')}`}
                  className="text-[12.5px] text-text-muted hover:text-text-main hover:underline underline-offset-2 transition-colors"
                >
                  Request a ticker
                </a>
              </li>
            </ul>
          </nav>

          {/* Data and trust */}
          <nav aria-labelledby="footer-data">
            <h2
              id="footer-data"
              className="font-mono text-[10px] uppercase tracking-[0.18em] text-text-dim"
            >
              Data and trust
            </h2>
            <ul className="mt-3.5 space-y-2">
              <li>
                <Link
                  href="/methodology#data-sources"
                  className="text-[12.5px] text-text-muted hover:text-text-main hover:underline underline-offset-2 transition-colors"
                >
                  Data sources
                </Link>
              </li>
              <li>
                <Link
                  href="/methodology#price-provenance"
                  className="text-[12.5px] text-text-muted hover:text-text-main hover:underline underline-offset-2 transition-colors"
                >
                  Price provenance
                </Link>
              </li>
              <li>
                <Link
                  href="/methodology#limitations"
                  className="text-[12.5px] text-text-muted hover:text-text-main hover:underline underline-offset-2 transition-colors"
                >
                  Model limitations
                </Link>
              </li>
              <li>
                <Link
                  href="/methodology#disclaimer"
                  className="text-[12.5px] text-text-muted hover:text-text-main hover:underline underline-offset-2 transition-colors"
                >
                  Not investment advice
                </Link>
              </li>
            </ul>
            <p className="mt-4 text-[11.5px] text-text-faint leading-relaxed">
              Saved models stay in this browser. Nothing is uploaded or synchronised.
            </p>
          </nav>
        </div>

        {/* Bottom bar */}
        <div className="border-t border-border py-5 flex flex-col-reverse sm:flex-row sm:items-center sm:justify-between gap-4">
          <div className="space-y-1">
            <p className="text-[11.5px] text-text-faint leading-relaxed max-w-[70ch]">
              Valuation output is model-generated, not a recommendation. Prices refresh daily;
              figures come from public filings and market data providers.
            </p>
            <p className="text-[11.5px] text-text-dim">
              Built by{' '}
              <a
                href={SOCIAL.portfolio}
                rel="me noopener noreferrer"
                target="_blank"
                className="text-text-muted hover:text-text-main underline underline-offset-2"
              >
                Sourabh Pradhan
              </a>
              .
            </p>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {[
              { href: SOCIAL.portfolio, label: 'Portfolio' },
              { href: SOCIAL.github, label: 'GitHub' },
              { href: SOCIAL.linkedin, label: 'LinkedIn' },
            ].map((s) => (
              <a
                key={s.label}
                href={s.href}
                rel="me noopener noreferrer"
                target="_blank"
                className="inline-flex items-center h-9 px-3 border border-border rounded-sm text-[12px] text-text-muted hover:text-text-main hover:bg-surface-2 transition-colors"
              >
                {s.label}
              </a>
            ))}
          </div>
        </div>
      </div>
    </footer>
  )
}
