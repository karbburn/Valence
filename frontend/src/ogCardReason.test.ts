/**
 * The share card must fit, and must name the check.
 *
 * A card is 1200x630 with a fixed layout and no scrolling, so a reason that runs long
 * does not degrade, it overflows: the first version of `firstReason` returned the whole
 * paragraph whenever the check name appeared in the first 60 characters, and the served
 * /stock/INFY card ran its text through the footer and off the bottom edge. Nothing about
 * that failure is visible from the source, which is why the function is exported and
 * pinned here rather than inspected.
 *
 * The card is also the surface a chat client unfurls as an IMAGE, so a withheld figure
 * here is copied out of context. It carries no figure at all now, and this asserts the
 * text that replaces it says which check stopped publication.
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import { ogCardReason } from './lib/ogCard.ts'

test('a long reason is cut to fit and keeps the check name', () => {
  const reason =
    "inputs_trace_to_a_filing: No filing contributed to this company's historicals, so the " +
    'valuation is not published as a valuation. Sources present: nse_filing, screener, ' +
    'yfinance_live. These figures may well be correct, but the platform has not verified ' +
    'any of them against a filing and cannot show a reader the document and line behind ' +
    'any single number. The statements and the audit trail remain available; what is ' +
    'withheld is the valuation built on top of them.'

  const out = ogCardReason(reason)

  assert.ok(
    out.length <= 230,
    `the card reason is ${out.length} characters; it overflows a 630px card: ${out}`,
  )
  assert.match(
    out,
    /^inputs_trace_to_a_filing:/,
    'the check name is the part a reader can act on, and the cut dropped it',
  )
  assert.match(
    out,
    /No filing contributed/,
    'the finding itself must survive, not just the check name',
  )
})

test('a reason with no check name is still cut', () => {
  const out = ogCardReason('x '.repeat(400))
  assert.ok(out.length <= 230, `unbounded: ${out.length} characters`)
})

test('a missing reason says what it could not do, and blames nobody', () => {
  const out = ogCardReason(undefined)
  assert.match(out, /could not verify/i)
  assert.ok(
    !/filing|check|inputs_trace/i.test(out),
    'the fallback must not name a specific cause it has no evidence for',
  )
})

test('a refusal may still name the figure it refuses', () => {
  // Deliberate, and the opposite of a leak. "implied share price -62.50 is not positive"
  // is how a reader checks that the engine refused for the reason it states; strip the
  // number and the refusal becomes unfalsifiable, which is the same error as hiding the
  // QA report. It is also arithmetically impossible to read -62.50 as a valuation, which
  // is what makes it safe where a positive figure would not be.
  //
  // The distinction that matters is the SIGN, and it is checked where it belongs: the
  // leak sweep refuses a positive withheld figure on any surface and permits a
  // non-positive one only inside a sentence carrying a refusal.
  const out = ogCardReason('valuation_is_meaningful: base: implied share price -62.50 is not positive.')
  assert.match(out, /-62\.50/)
  assert.match(out, /not positive/)
})
