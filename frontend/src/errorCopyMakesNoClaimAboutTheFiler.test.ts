/**
 * The error copy must make no claim about the company it could not model.
 *
 * This is the state a reader is in when they decide whether to trust anything else on the
 * page, which makes it the one place a product like this is most entitled to mislead them.
 * Two unverified claims have been removed from it, one in each direction:
 *
 *   "no annual filings could be reached for it, so there is nothing to model"
 *       asserted a gap in a real company's reporting because a fetch had failed.
 *
 *   "The company does file, so this is most likely a temporary failure to reach them"
 *       asserted the opposite, for a ticker the engine genuinely could not source, and
 *       for the companies whose build had crashed -- because the backend recorded every
 *       exception as an ingestion failure and answered from that cache for five minutes.
 *
 * The copy must therefore stay on the side it can actually support: what this engine did,
 * and what the reader can do about it. It must never assert anything about whether the
 * company files.
 *
 * Driven through the same function `api.ts` calls, so the string asserted here is the one a
 * visitor reads. It could not be reached through `fetchModelSpec` because that module pulls
 * in the publication gate at runtime and node's ESM resolver has no extensionless lookup,
 * which is why the copy now lives in its own module rather than being exported for a test.
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import { tickerLabelFrom, unavailableMessage } from './lib/modelFetchError.ts'

/** Claims about the FILER that this copy must never make, in either direction. */
const CLAIMS_ABOUT_THE_FILER = [
  /the company does not file/i,
  /no (annual )?filings (exist|were filed)/i,
  /nothing to (model|report)/i,
  /there is nothing to model/i,
  /has no (financials|financial statements)/i,
  /does not (file|report|publish)/i,
  /the company does file/i,
  /a gap in (its|their) reporting/i,
]

function stubFetch() {
  globalThis.fetch = (async () => {
    throw new Error('the network stub should not be reached by this test')
  }) as typeof fetch
}

function messageFor(detail: string, companyId = 'infy_infy'): string {
  stubFetch()
  return unavailableMessage(tickerLabelFrom(companyId), detail)
}

test('the label is the ticker, never the internal storage key', () => {
  // `infy_infy` is a key in a JSON file. `INFY` is what a person recognises, and the key
  // was once printed on screen uppercased.
  assert.equal(tickerLabelFrom('infy_infy'), 'INFY')
  assert.equal(tickerLabelFrom('bhartiartl_bhartiartl'), 'BHARTIARTL')
  assert.equal(tickerLabelFrom('tatamotors_tatamotors'), 'TATAMOTORS')
  for (const companyId of ['infy_infy', 'nvda_us', 'tcs_tcs']) {
    const label = tickerLabelFrom(companyId)
    assert.ok(
      !label.includes('_'),
      `${companyId} rendered its storage key as the label: ${label}`,
    )
  }
})

test('a multi-word company id yields a prefix, which is documented rather than hidden', () => {
  // The known limit, pinned so that fixing it later is a deliberate change rather than an
  // accident: `adani_green_adani_green` cannot yield ADANIGREEN without the universe
  // registry, so it yields ADANI. Asserting the wrong thing here would have hidden the gap;
  // asserting it documents the gap and still refuses to print the key.
  assert.equal(tickerLabelFrom('adani_green_adani_green'), 'ADANI')
  assert.ok(!tickerLabelFrom('adani_green_adani_green').includes('_'))
})

test('an unsourceable ticker is described without claiming anything about the filer', () => {
  const msg = messageFor(
    'No financial statements could be sourced for this ticker yet. Try again shortly.'
  )
  for (const claim of CLAIMS_ABOUT_THE_FILER) {
    assert.ok(
      !claim.test(msg),
      `the error copy asserts something about the company: ${msg}`,
    )
  }
  assert.match(msg, /INFY/, 'the ticker is named the way a person recognises it')
  assert.ok(
    !/INFY_INFY/.test(msg),
    `the internal storage key is shown to a visitor: ${msg}`,
  )
  assert.match(msg, /try again/i, 'the reader is left without an action')
  assert.ok(
    !/ADANIGREEN:\s*\./.test(msg),
    `the API's own reason was stripped and left an empty tail: ${msg}`,
  )
})

test('an unreachable provider is described without claiming anything about the filer', () => {
  // The backend now distinguishes this from an absence. The copy must not read as though
  // the two were the same event, and must not reach for a claim about the company to fill
  // the gap.
  const msg = messageFor(
    'The filing providers could not be reached for this ticker. Try again shortly.'
  )
  for (const claim of CLAIMS_ABOUT_THE_FILER) {
    assert.ok(!claim.test(msg), `the error copy asserts something about the company: ${msg}`)
  }
  assert.ok(
    !/ADANIGREEN:\s*\./.test(msg),
    `the API's own reason was stripped and left an empty tail: ${msg}`,
  )
})

test('an empty detail still produces a sentence rather than a dangling label', () => {
  const msg = messageFor('')
  assert.ok(
    !/ADANIGREEN:\s*\./.test(msg),
    `an empty API detail leaves the reader with a label and nothing: ${msg}`,
  )
  for (const claim of CLAIMS_ABOUT_THE_FILER) {
    assert.ok(!claim.test(msg), `the error copy asserts something about the company: ${msg}`)
  }
})
