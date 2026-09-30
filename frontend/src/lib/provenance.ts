/**
 * What a model's numbers were read from, in words a reader can act on.
 *
 * The product claims every published figure matches an official filing. That holds
 * for nine of the twenty-three shipped companies and not for the other fourteen,
 * because a Screener.in export or a market feed is a real number about a real
 * company but not the number the filer published. The tie-out has measured what
 * that costs: the Infosys ADR carries 1,043 of current investments where its own
 * 20-F says 1,365, and no non-current investments where the filing says 942.
 *
 * A reader deciding whether to trust a valuation needs to know which they are
 * looking at, and the difference is not a detail — it is the whole claim.
 *
 * `screener` is deliberately not treated as a filing source. It is a third-party
 * aggregator whose own documentation says its figures may differ from the filings,
 * and the ingestion already ranked it as secondary for exactly that reason.
 */

/** A human name for a source key, for the ones a reader might recognise. */
const SOURCE_NAMES: Record<string, string> = {
  sec_edgar: 'SEC EDGAR',
  nse_filing: 'NSE filing',
  bse_filing: 'BSE filing',
  // NOT "Screener.in". The files parsed by the screener reader are not exports
  // from Screener.in: they are produced by `backend/data/sources/generate_sources.py`
  // and `generate_us_sources.py`, which are tracked in this repository and write
  // hand-entered numbers into a Screener-shaped workbook. The generator's own
  // comment on the most recent year reads "FY26 values are estimates (unverified
  // at fixture date)", and the engine was publishing that year as `reported`
  // because the file it read said so.
  //
  // So naming a third-party aggregator here would be a worse error than the one it
  // replaced: it would attribute hand-entered figures to a named data provider, and
  // a reader checking that provider would find nothing.
  screener: 'a local fixture file',
  yfinance_live: 'market feed',
  yfinance: 'market feed',
  yahoo_chart: 'market feed',
  twelvedata: 'market feed',
}

export type ProvenanceTone = 'filing' | 'mixed' | 'aggregated' | 'market'

/**
 * Sources that carry a filer's own accounts. Mirrors the backend's set so the page
 * cannot be talked into the filing claim by a flag alone: if the backend ever says
 * `filing_derived` for something that is not actually a filing source, the page
 * still refuses to call it one.
 */
const FILING_SOURCES = new Set(['sec_edgar', 'nse_filing', 'bse_filing'])

export function provenanceTone(
  filingDerived: boolean | null | undefined,
  filingSource: string | null | undefined,
): ProvenanceTone {
  const hasFiling = !!filingSource && FILING_SOURCES.has(filingSource)
  if (filingDerived && hasFiling) return 'filing'
  if (hasFiling) return 'mixed'
  return 'market'
}

export function provenanceLabel(
  filingDerived: boolean | null | undefined,
  filingSource: string | null | undefined,
  dataSources?: Record<string, number> | null,
): string {
  const tone = provenanceTone(filingDerived, filingSource)
  switch (tone) {
    case 'filing':
      return `From ${SOURCE_NAMES[filingSource!] ?? filingSource}`
    case 'mixed':
      return `Mostly ${SOURCE_NAMES[filingSource!] ?? filingSource}, partly other sources`
    default: {
      // Name what actually supplied the rows rather than asserting a category.
      const rows = Object.entries(dataSources ?? {})
        .filter(([, n]) => n > 0)
        .sort((a, b) => b[1] - a[1])
      if (!rows.length) return 'Source not recorded'
      const [top, count] = rows[0]
      const name = SOURCE_NAMES[top] ?? top
      return count === rows.reduce((s, r) => s + r[1], 0)
        ? `From ${name}, not the accounts`
        : `Mostly ${name}, not the accounts`
    }
  }
}

/** The hover explanation, which is where the distinction is actually justified. */
export function provenanceTitleText(meta: {
  filing_derived?: boolean | null
  filing_source?: string | null
  data_sources?: Record<string, number> | null
} | null | undefined): string {
  if (!meta) return ''
  const rows = Object.entries(meta.data_sources ?? {})
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1])
  if (!rows.length) {
    return 'This model does not record which sources supplied its figures.'
  }
  const breakdown = rows
    .map(([k, n]) => `${SOURCE_NAMES[k] ?? k}: ${n} figure${n === 1 ? '' : 's'}`)
    .join(', ')

  if (meta.filing_derived) {
    return (
      'These figures are read from the filer\'s own accounts: ' +
      `${breakdown}. Every published number on this page can be tied to a filing.`
    )
  }
  return (
    'These figures are NOT read from the filer\'s accounts. They come from a market ' +
    `data provider: ${breakdown}. They are real numbers about a real company, but ` +
    'they are the provider\'s figures and not the filer\'s, and a tie-out against ' +
    'the accounts has found them differing. Treat the valuation accordingly.'
  )
}
