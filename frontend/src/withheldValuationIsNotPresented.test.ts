/**
 * A withheld valuation must not appear on any surface a reader or a crawler can see.
 *
 * The product's rule is that a valuation is published only where a filing is behind it, and
 * twelve India models are `opinion_only`. `implied_share_price` is still COMPUTED for every
 * model -- the verdict governs whether it may be SHOWN, not whether it exists -- so any
 * surface that formats it without reading the verdict publishes exactly the number the
 * product says it withholds.
 *
 * Two did, and both were found by reading served HTML rather than by reading this source:
 *
 *   1. `generateMetadata` built the meta description from `v.implied` with no verdict check.
 *      Live, /stock/INFY's headline read "n/a" while its description read
 *      "DCF implied value 1,079.32 vs 1,035.00 market". The meta description is the
 *      outermost surface in the product: what Google indexes, what Slack and X unfurl, what
 *      an answer engine quotes.
 *
 *   2. The DCF bridge's last row printed the implied share price in green, about 800px below
 *      the "n/a" headline, in the most emphatic styling on the page -- for a reader who
 *      simply scrolled.
 *
 * Both now gate on `mayPublishPrice`. These tests pin the SOURCE, because a source-level
 * test runs in CI where no server exists, and because the failure mode is a component
 * forgetting the check rather than the check being wrong.
 *
 * Deliberately NOT asserted here: that `implied_share_price` is absent from the served HTML
 * altogether. It remains in the serialized RSC payload as data, next to
 * `publication.publishable: false`. Removing it from the payload would change the API
 * contract that the Excel and JSON export paths read, and a number present as data beside
 * its own "not published" verdict is not a claim. What must never happen is the number being
 * PRESENTED as a valuation, and that is what these tests check.
 */

import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { test } from 'node:test'
import assert from 'node:assert/strict'

const ROOT = join(import.meta.dirname, '..')

function source(rel: string): string {
  return readFileSync(join(ROOT, rel), 'utf8')
}

test('the meta description does not format an implied price without the verdict', () => {
  const src = source('src/app/stock/[ticker]/page.tsx')

  // It must consult the verdict.
  assert.match(
    src,
    /mayPublishPrice\(spec\)/,
    'page.tsx must read the publication verdict before formatting any implied price',
  )

  // And the description branch must be gated by it. Checking for the gate on the SAME
  // expression that formats the price is what stops this regressing: a file can import
  // mayPublishPrice and still ignore it.
  assert.match(
    src,
    /mayPublish && v\?\.implied/,
    'the meta description branch must be gated on the verdict, not only on the value being present',
  )

  assert.ok(
    !/const description = v\?\.implied/.test(src),
    'the description is still built from the presence of a value alone, which is how ' +
      'twelve withheld valuations reached the meta description',
  )
})

test('the DCF bridge row does not print the implied share price when withheld', () => {
  const src = source('src/components/DCFSchedule.tsx')

  assert.match(
    src,
    /priceWithheld\s*\?\s*'not published/,
    'the bridge row must show a withheld message instead of the figure',
  )

  // The unguarded form is the defect: the price interpolated with no condition around it.
  const unguarded = /\{currencySym\}\{fmtNum\(bridge\.equity_value\)\}\s+.{0,4}\s*\{currencySym\}\{fmtNum\(bridge\.implied_share_price/
  assert.ok(
    !unguarded.test(src),
    'the bridge row still interpolates implied_share_price directly; it must sit in the ' +
      'else branch of the withheld check',
  )
})

test('the gate used by the page is the shared helper, not a second copy of the rule', () => {
  const page = source('src/app/stock/[ticker]/page.tsx')
  const schedule = source('src/components/DCFSchedule.tsx')

  assert.match(
    page,
    /from '@\/lib\/publication'/,
    'the page must import the verdict helper rather than re-deriving the rule',
  )
  assert.match(
    schedule,
    /priceWithheld/,
    'DCFSchedule must derive its gate from the shared helper',
  )

  // A hand-kept list of failing check names is the pattern this project has hit five times,
  // so a new one appearing in a component is worth failing on.
  assert.ok(
    !/inputs_trace_to_a_filing/.test(page),
    'page.tsx references a check name directly; that duplicates the server-side list and ' +
      'has drifted before',
  )
})