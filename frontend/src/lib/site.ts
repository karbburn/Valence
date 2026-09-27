export const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL ?? 'https://valence.sourabhpradhan.in'

export const SITE_NAME = 'Valence'

export const SITE_DESCRIPTION =
  'Browser-based equity valuation and 3-statement financial modeling workbench for US and Indian equities: DCF, WACC, trading comps, PE returns, and a 30-tab Excel exporter.'

/**
 * Default page title. Uses a colon rather than a dash.
 *
 * An em-dash is the most recognisable tell of generated copy, and this string
 * reaches the title tag, the meta description, four Open Graph and Twitter
 * fields and the JSON-LD, so a single one here propagates to all of them.
 */
export const SITE_TITLE = `${SITE_NAME}: Equity Valuation & Financial Modeling Workbench`

export const AUTHOR = { name: 'Sourabh', url: 'https://www.sourabhpradhan.in/' }

// Single source of truth for the author's profiles. The footer renders from
// this rather than hardcoding URLs, and SOCIAL feeds the Organization
// sameAs in the JSON-LD, so the three stay in step.
export const SOCIAL = {
  portfolio: 'https://www.sourabhpradhan.in/',
  github: 'https://github.com/karbburn',
  linkedin: 'https://www.linkedin.com/in/sourabh-pradhan07',
  authorSite: AUTHOR.url,
  twitter: '@sourabh',
}

// Real, monitored contact. Also used as the SEC EDGAR User-Agent contact, which
// their fair-access policy requires; the two must not drift apart.
export const CONTACT_EMAIL = 'karbburn@gmail.com'

/**
 * Maximum number of ticker pages prerendered at build time.
 *
 * Each prerendered page embeds a full ModelSpecification of roughly 175 KB, so
 * this is a build-output budget rather than a taste decision. Beyond the cap,
 * pages render on first request and are then cached by the route revalidate
 * window. Lowering it costs first-request latency; raising it costs build size.
 */
export const PRERENDER_LIMIT = 175

/**
 * Hours a rendered ticker page and its model payload stay fresh.
 *
 * Market prices are refreshed once daily, so an hourly window keeps the page
 * well inside the price refresh cadence without re-rendering on every visit.
 */
export const REVALIDATE_SECONDS = 3600
