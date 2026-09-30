/**
 * A daily close must never be captioned as a live quote.
 *
 * On 2026-09-30 the Larsen & Toubro page carried an exchange close from
 * 2026-09-28 under the words "As of 2026-09-28 · Live". The date was right there,
 * so the reader had everything needed to see the number was two sessions old, and
 * the word told them the opposite.
 *
 * The backend is not confused about this. `_fetch_yfinance_history` is documented
 * as returning "a real exchange close — which is the engine's valuation basis
 * (previous close), not an intraday print", and `_fetch_yahoo_chart` as a
 * "Daily-close price". Only `_fetch_yfinance`, which reads `currentPrice` from
 * yfinance's `.info`, and the TwelveData path can carry a current price. The
 * frontend treated all four as live, so the two sources that provably cannot be
 * live were among the likeliest to be displayed.
 *
 * There is a second reason the word had to go. Company pages are prerendered as
 * static HTML and revalidated hourly, so no number on one is current to the minute
 * even when the source is a live feed. "Live" described the source rather than the
 * screen, and a reader cannot tell which they are looking at.
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  baseQuoteSource,
  classifyQuote,
  quoteCaption,
  quoteIsFlagged,
  quoteLabel,
  quoteTitle,
} from './quoteLabel.ts'

test('a yfinance history quote is a close, not a live print', () => {
  // The exact case from the L&T page.
  assert.equal(classifyQuote('yfinance_history', '2026-09-28'), 'close')
  const caption = quoteCaption('close', '2026-09-28')
  assert.ok(!caption.includes('Live'), `a close was captioned live: ${caption}`)
  assert.equal(caption, 'As of 2026-09-28 · Close')
  assert.ok(caption.includes('2026-09-28'), 'the date must still be shown')
})

test('the yahoo chart source is a close too', () => {
  assert.equal(classifyQuote('yahoo_chart', '2026-09-28'), 'close')
  assert.ok(!quoteLabel('close', '2026-09-28').includes('Live'))
})

test('a source that can carry a current price may say live', () => {
  assert.equal(classifyQuote('yfinance', '2026-09-30'), 'live')
  assert.equal(classifyQuote('twelvedata', '2026-09-30'), 'live')
})

test('no caption anywhere calls a close a live quote', () => {
  // Sweeps the whole vocabulary rather than the case that was reported, because
  // the classification is a lookup and the next source added could land in the
  // wrong set without anyone noticing.
  const sources = [
    'yfinance_history',
    'yahoo_chart',
    'yfinance',
    'twelvedata',
    'stale_cache:yfinance_history',
    'registry',
    'market_default',
    'market_default:INFY',
    'yfinance_history:successor_ticker',
    'something_new',
  ]
  for (const source of sources) {
    const kind = classifyQuote(source, '2026-09-28')
    const caption = quoteCaption(kind, '2026-09-28')
    const label = quoteLabel(kind, '2026-09-28')
    const title = quoteTitle(kind, '2026-09-28', baseQuoteSource(source))
    if (kind !== 'live') {
      for (const text of [caption, label, title]) {
        assert.ok(
          !/\bLive\b/.test(text),
          `source ${source} classified ${kind} produced live wording: ${text}`,
        )
      }
    }
  }
})

test('a live caption still says the page can lag, because it is static', () => {
  const title = quoteTitle('live', '2026-09-30', 'yfinance')
  assert.ok(/revalidated hourly/.test(title), title)
})

test('a successor quote is flagged and explained, never compared', () => {
  assert.equal(classifyQuote('yfinance_history:successor_ticker', '2026-09-28'), 'successor')
  assert.equal(quoteIsFlagged('successor'), true)
  assert.ok(quoteTitle('successor', '2026-09-28', 'yfinance_history').includes('not comparable'))
})

test('the fallback prefixes both resolve to a benchmark, on every screen', () => {
  // The two copies of this logic had drifted: QuickDCFView matched only the exact
  // strings, KPIBar also matched the prefix, so `market_default:INFY` was called a
  // benchmark on one page and printed bare on the other.
  for (const source of ['market_default', 'market_default:INFY', 'registry']) {
    assert.equal(classifyQuote(source, '2026-09-28'), 'benchmark', source)
    assert.equal(quoteIsFlagged('benchmark'), true, source)
  }
})

test('a price with no date is not presented as a close either', () => {
  assert.equal(classifyQuote('yfinance_history', null), 'undated')
  const caption = quoteCaption('undated', null)
  assert.ok(!caption.includes('2026-'), 'an undated quote must not invent a date')
  assert.ok(quoteTitle('undated', null, 'yfinance_history').includes('indicative'))
})
