import { ImageResponse } from 'next/og'
import { notFound } from 'next/navigation'
import { getModelSpecServer, resolveSlugServer } from '@/lib/serverApi'
import { mayPublishPrice, withheldReason } from '@/lib/publication'
import { ogCardReason } from '@/lib/ogCard'
import { isValidSlug, normalizeSlug } from '@/lib/tickers'

// Segment config must be a literal: Next reads it statically, so an imported
// constant is rejected. Keep in step with REVALIDATE_SECONDS in lib/site.ts.
export const revalidate = 3600

// The file-based image convention only writes og:image:width and og:image:height
// if the segment declares them, and the root pages do declare theirs. Without
// these a share card is served at an unknown size to anything that would rather
// not fetch it first. Must match the size passed to ImageResponse below.
export const size = { width: 1200, height: 630 }
export const contentType = 'image/png'

type Params = { params: Promise<{ ticker: string }> }

/**
 * Share card for a single ticker.
 *
 * Shows the implied price against the market price, because that comparison is
 * the one number a reader deciding whether to open the link actually wants. The
 * palette is the app's own canvas, surface and accent so a shared card does not
 * read as a different product from the page it links to.
 */
export default async function Image({ params }: Params) {
  const { ticker } = await params
  if (!isValidSlug(ticker)) notFound()

  const company = await resolveSlugServer(normalizeSlug(ticker))
  if (!company) notFound()

  const spec = await getModelSpecServer(company.company_id)
  const valuation =
    spec?.valuation?.find((v) => v.scenario === 'base') ?? spec?.valuation?.[0]

  const currency = spec?.metadata?.currency || 'USD'
  const symbol = currency === 'INR' ? '₹' : '$'
  const fmt = (n: number | null | undefined) =>
    n == null ? null : `${symbol}${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

  // The verdict governs the card exactly as it governs the page.
  //
  // This is the surface a chat client unfurls and a social card renders as an
  // IMAGE, so a withheld figure here is worse than a withheld figure in the meta
  // description: it is copied out of context, with no sentence beside it saying the
  // model is withheld, and it is the version that ends up pasted into a thread.
  // `getModelSpecServer` already nulls the price, so the guard is on the verdict
  // rather than on the value being null, which would also fire on a genuine absence.
  const publishable = mayPublishPrice(spec)
  const reason = withheldReason(spec)

  const implied = publishable ? fmt(valuation?.dcf_bridge?.implied_share_price) : null
  const market = fmt(valuation?.reverse_dcf?.market_price)
  const wacc = valuation?.wacc?.wacc

  const delta =
    publishable &&
    valuation?.dcf_bridge?.implied_share_price != null &&
    valuation?.reverse_dcf?.market_price
      ? valuation.dcf_bridge.implied_share_price - valuation.reverse_dcf.market_price
      : null
  const deltaPct =
    delta != null && valuation?.reverse_dcf?.market_price
      ? (delta / valuation.reverse_dcf.market_price) * 100
      : null

  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          padding: '64px',
          backgroundColor: '#080c14',
          color: '#f8fafc',
          fontFamily: 'sans-serif',
        }}
      >
        {/* Top: wordmark and ticker badge */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <div style={{ width: 12, height: 12, borderRadius: 12, backgroundColor: '#0ea5e9' }} />
            <div style={{ fontSize: 26, fontWeight: 800, letterSpacing: 5, color: '#f8fafc' }}>
              VALENCE
            </div>
          </div>
          <div
            style={{
              fontSize: 30,
              fontWeight: 700,
              color: '#0ea5e9',
              border: '1px solid rgba(14,165,233,0.4)',
              borderRadius: 6,
              padding: '8px 20px',
              backgroundColor: 'rgba(14,165,233,0.08)',
            }}
          >
            {company.ticker}
          </div>
        </div>

        {/* Middle: company name and the valuation comparison */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ fontSize: 46, fontWeight: 700, color: '#f8fafc', lineHeight: 1.15 }}>
            {company.name}
          </div>
          <div style={{ fontSize: 26, color: '#94a3b8' }}>
            {publishable
              ? 'DCF implied value against market price'
              : 'Valuation withheld, and the model says why'}
          </div>

          {publishable ? (
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 56, marginTop: 28 }}>
              <Stat label="Implied" value={implied} color="#f8fafc" />
              <Stat label="Market" value={market} color="#94a3b8" />
              {deltaPct != null && (
                <Stat
                  label="Difference"
                  value={`${deltaPct >= 0 ? '+' : ''}${deltaPct.toFixed(1)}%`}
                  color={deltaPct >= 0 ? '#10b981' : '#ef4444'}
                />
              )}
            </div>
          ) : (
            /* Withheld. The card used to print the figure for twelve India models, which
               is the worst surface in the product for it: a chat client unfurls this as
               an IMAGE, so the number arrives with no sentence attached and is copied out
               of context. It names the check that stopped publication, because a card
               that says only "withheld" invites the reader to assume a loading failure
               rather than a decision the engine made and can defend. */
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 10,
                marginTop: 28,
                maxWidth: 940,
              }}
            >
              <div style={{ fontSize: 34, fontWeight: 700, color: '#f59e0b' }}>
                No valuation published
              </div>
              <div style={{ fontSize: 21, color: '#94a3b8', lineHeight: 1.4 }}>
                {ogCardReason(reason)}
              </div>
            </div>
          )}
        </div>

        {/* Bottom: model basis and domain */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontSize: 24,
            color: '#64748b',
          }}
        >
          <div style={{ display: 'flex', gap: 28 }}>
            <span>Unlevered FCFF</span>
            {wacc != null && <span>WACC {wacc.toFixed(1)}%</span>}
            <span>Base scenario</span>
          </div>
          <div style={{ color: '#0ea5e9' }}>valence.sourabhpradhan.in</div>
        </div>
      </div>
    ),
    { width: 1200, height: 630 }
  )
}

function Stat({ label, value, color }: { label: string; value: string | null; color: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ fontSize: 20, color: '#64748b', letterSpacing: 1 }}>{label.toUpperCase()}</div>
      <div style={{ fontSize: 52, fontWeight: 700, color }}>{value ?? '-'}</div>
    </div>
  )
}
