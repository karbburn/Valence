import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const API = readFileSync(new URL('./api.ts', import.meta.url), 'utf8')

/**
 * What the 503 message is allowed to claim.
 *
 * A 503 means the engine could not compile a company right now. It is not a verdict
 * on the company, and the two causes -- "the filings do not exist" and "we could not
 * reach the filings" -- are indistinguishable from outside. The message must not pick
 * one.
 *
 * It did. It said "no annual filings could be reached for it, so there is nothing to
 * model", which is a factual claim about a company the platform knows nothing about.
 * Adani Green files annually with its exchange; the page failed because a fetch did
 * not come back. A reader shown that sentence concludes the company has no
 * financials, which is not a thing this platform is entitled to assert, and which is
 * the exact state in which a reader is deciding whether to trust anything else on the
 * page.
 *
 * It also printed the internal storage key, uppercased. `ADANIGREEN_ADANIGREEN` is a
 * key in a JSON file, not a name, and putting it on screen tells the reader the
 * system is showing them its plumbing.
 */
function unavailableSource(): string {
  const start = API.indexOf('function unavailableMessage')
  assert.notEqual(start, -1, 'unavailableMessage is gone; the 503 path has no wording')
  return API.slice(start, API.indexOf('\n}', start))
}

test('the 503 message never claims the company has nothing to model', () => {
  const src = unavailableSource()
  assert.ok(
    !/there is nothing to model/i.test(src),
    'the message asserts a fact about the company that a transient fetch failure ' +
      'cannot establish'
  )
  assert.ok(
    !/no annual filings/i.test(src),
    'it states the filings do not exist when the truth is they were not reached'
  )
})

test('the 503 message never prints the internal storage key', () => {
  const src = unavailableSource()
  assert.ok(
    !/companyId\.toUpperCase\(\)/.test(src),
    'the id is a storage key; uppercasing it puts a JSON field name on screen'
  )
})

test('the 503 message says the failure is probably temporary', () => {
  const src = unavailableSource()
  assert.match(src, /temporary/i)
  // The sentence that does the real work: the company reports, we failed to reach
  // the report. Without it the message still reads as a verdict.
  assert.match(src, /company does file/i)
})

test('the 503 handler passes the ticker, not the whole id', () => {
  // `adanigreen_adanigreen` is the id. `ADANIGREEN` is what a person recognises.
  assert.match(
    API,
    /unavailableMessage\(companyId\.split\('_'\)\[0\],/,
    'the message must be given the ticker rather than the storage key'
  )
})

test('the retry advice does not invite the click that makes the wait worse', () => {
  const src = unavailableSource()
  assert.ok(
    !/retry in a few seconds/i.test(src),
    '"Retry in a few seconds" reads as advice to click again, and a second click is a ' +
      'second model build competing with the first'
  )
})