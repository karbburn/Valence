import { SITE_URL, SITE_NAME, SITE_DESCRIPTION, SOCIAL, AUTHOR } from '@/lib/site'
import type { ModelSpecification } from '@/lib/types'
import type { ResolvedSlug } from '@/lib/tickers'
import { stockUrl } from '@/lib/tickers'

function graph() {
  return {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'Organization',
        '@id': `${SITE_URL}/#organization`,
        name: SITE_NAME,
        url: SITE_URL,
        logo: `${SITE_URL}/icon.png`,
        description: SITE_DESCRIPTION,
        // Kept in step with the footer, which renders from the same SOCIAL map.
        sameAs: [SOCIAL.github, SOCIAL.linkedin, SOCIAL.authorSite],
      },
      {
        '@type': 'WebSite',
        '@id': `${SITE_URL}/#website`,
        url: SITE_URL,
        name: SITE_NAME,
        description: SITE_DESCRIPTION,
        publisher: { '@id': `${SITE_URL}/#organization` },
        potentialAction: {
          '@type': 'SearchAction',
          // The landing page reads ?q= and prefills the ticker search, so this is
          // a working target rather than a declared one.
          target: `${SITE_URL}/?q={search_term_string}`,
          'query-input': 'required name=search_term_string',
        },
      },
      {
        '@type': 'SoftwareApplication',
        name: SITE_NAME,
        operatingSystem: 'Web',
        applicationCategory: 'FinanceApplication',
        description: SITE_DESCRIPTION,
        url: SITE_URL,
        offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
        publisher: { '@id': `${SITE_URL}/#organization` },
        // Named rather than left to the description, because these are the
        // capabilities a search engine classifies an application on and a reader
        // checks for. They match the capability list in llms.txt.
        featureList: [
          'Reverse DCF: market-implied perpetuity growth solver',
          'Discounted cash flow with CAPM WACC',
          'Gordon growth and exit multiple terminal values',
          'Trading comparables and football field ranges',
          'Private equity exit returns, MoIC and IRR',
          'Three-statement financial model with driver overrides',
          'Automated accounting, valuation and data quality audit',
          '31-tab live-formula Excel export',
        ],
      },
      {
        '@type': 'Person',
        '@id': `${SITE_URL}/#author`,
        name: AUTHOR.name,
        url: AUTHOR.url,
        sameAs: [SOCIAL.github, SOCIAL.linkedin],
      },
    ],
  }
}

function JsonLd({ data }: { data: object }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }}
    />
  )
}

/** Site-level graph. Emitted once, from the root layout. */
export function SiteJsonLd() {
  return <JsonLd data={graph()} />
}

interface StockJsonLdProps {
  company: ResolvedSlug
  spec: ModelSpecification | null
}

/**
 * Per-ticker graph, emitted on a ticker page alongside the site graph.
 *
 * Only the ticker-specific nodes. The site graph is emitted once by the root
 * layout, and repeating it here would declare Organization, WebSite,
 * SoftwareApplication and Person twice on the same document with identical
 * @ids, which is a duplicated structured-data claim rather than a richer one.
 *
 * A WebPage and a BreadcrumbList rather than a FinancialProduct: there is no
 * price being sold here, only a computed valuation, and describing a computed
 * figure as a product with an offer is the kind of structured data that gets a
 * site penalised.
 */
export function StockJsonLd({ company, spec }: StockJsonLdProps) {
  const url = stockUrl(SITE_URL, company.slug)
  const valuation =
    spec?.valuation?.find((v) => v.scenario === 'base') ?? spec?.valuation?.[0]
  const implied = valuation?.dcf_bridge?.implied_share_price
  const market = valuation?.reverse_dcf?.market_price

  const extra: object[] = [
    {
      '@type': 'WebPage',
      '@id': `${url}#webpage`,
      url,
      name: `${company.name} (${company.ticker}) DCF Valuation`,
      isPartOf: { '@id': `${SITE_URL}/#website` },
      about: { '@id': `${url}#company` },
      inLanguage: 'en',
    },
    {
      '@type': 'Corporation',
      '@id': `${url}#company`,
      name: company.name,
      tickerSymbol: company.ticker,
      url,
    },
    {
      '@type': 'BreadcrumbList',
      itemListElement: [
        { '@type': 'ListItem', position: 1, name: SITE_NAME, item: SITE_URL },
        { '@type': 'ListItem', position: 2, name: 'Tickers', item: `${SITE_URL}/stock` },
        {
          '@type': 'ListItem',
          position: 3,
          name: `${company.ticker}`,
          item: url,
        },
      ],
    },
  ]

  // Only stated when the figures actually came back, so the markup never
  // advertises a number the page does not show.
  if (implied != null || market != null) {
    // When the model was computed, and the session the benchmark price is from.
    //
    // A dataset with no date is a claim nobody can check. A citation engine
    // asked to quote a valuation has no way to tell a figure computed this
    // morning from one computed last spring, and a valuation carries a price
    // benchmark that moves every session, so the date of the two are not
    // interchangeable. Both are stated when they are known, because both change
    // what a reader can do with the number.
    const builtAt = spec?.metadata?.generation_date
    const priceDate = valuation?.reverse_dcf?.market_price_date
    const lastModified =
      builtAt != null
        ? new Date(builtAt).toISOString()
        : priceDate != null
          ? new Date(priceDate).toISOString()
          : undefined

    extra.push({
      '@type': 'Dataset',
      '@id': `${url}#valuation`,
      name: `${company.ticker} discounted cash flow valuation`,
      description:
        'Unlevered free cash flow to the firm valuation with base, bull and bear scenarios.',
      creator: { '@id': `${SITE_URL}/#organization` },
      isAccessibleForFree: true,
      ...(lastModified != null ? { dateModified: lastModified } : {}),
      ...(priceDate != null ? { temporalCoverage: priceDate } : {}),
      ...(implied != null ? { variableMeasured: 'DCF implied share price' } : {}),
      ...(market != null ? { measurementTechnique: 'Market price comparison' } : {}),
    })
  }

  return <JsonLd data={{ '@context': 'https://schema.org', '@graph': extra }} />
}
