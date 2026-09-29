export const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL ?? 'https://valence.sourabhpradhan.in'

export const SITE_NAME = 'Valence'

export const SITE_DESCRIPTION =
  'Browser-based equity valuation and 3-statement financial modeling workbench for US and Indian equities: DCF, WACC, trading comps, PE returns, and a 31-tab Excel exporter.'

/**
 * Default page title. Uses a colon rather than a dash.
 *
 * An em-dash is the most recognisable tell of generated copy, and this string
 * reaches the title tag, the meta description, four Open Graph and Twitter
 * fields and the JSON-LD, so a single one here propagates to all of them.
 */
export const SITE_TITLE = `${SITE_NAME}: Equity Valuation & Financial Modeling Workbench`

export const AUTHOR = { name: 'Sourabh', url: 'https://www.sourabhpradhan.in/' }

/**
 * The brand share card, and the reason it is referenced rather than co-located.
 *
 * A file-based `opengraph-image` in a route segment is applied to that segment
 * and to its descendants — but a descendant that declares its own `openGraph`
 * object REPLACES the inherited image instead of merging with it, and silently
 * ships with no `og:image` at all. `/stock` and `/methodology` both declare
 * their own title, description and URL, so both were doing exactly that: correct
 * text, no picture, on every share of both pages.
 *
 * Referencing one public asset from a constant fixes it for any route and cannot
 * regress, because a route that adds its own `openGraph` has to spread this in
 * and so is looking at the block anyway. A new page should therefore always
 * write `images: [OG_IMAGE]` alongside its own title and description.
 *
 * The per-ticker card is the deliberate exception: it is generated from that
 * company's own valuation, so it stays a dynamic `opengraph-image` in its own
 * segment and deliberately does not use this.
 *
 * Must stay 1200x630. That is the canonical Open Graph card size, and the
 * dimensions are published alongside the URL so crawlers need not download the
 * file to learn them.
 */
export const OG_IMAGE = {
  url: `${SITE_URL.replace(/\/$/, '')}/opengraph.png`,
  width: 1200,
  height: 630,
  type: 'image/png',
  alt: `${SITE_NAME}: equity valuation and financial modeling workbench`,
}

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
 * A model is revalued when a newer market session closes, so the figure in the
 * served HTML is at most this stale. The window is shorter than a session on
 * purpose: it is what stops a page sitting on yesterday's close for the rest of
 * the day while the engine itself is already quoting today's, which would make
 * the headline price and the workbench disagree on the same page.
 */
export const REVALIDATE_SECONDS = 3600
