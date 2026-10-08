/**
 * A withheld valuation must not appear on any surface a reader or a crawler can see.
 *
 * The product's rule is that a valuation is published only where a filing is behind it, and
 * twelve India models are `opinion_only`. `implied_share_price` is still COMPUTED for every
 * model -- the verdict governs whether it may be SHOWN, not whether it exists -- so any
 * surface that formats it without reading the verdict publishes exactly the number the
 * product says it withholds.
 *
 * Four did, and every one was found by reading SERVED output rather than by reading source:
 *
 *   1. `generateMetadata` built the meta description from `v.implied` with no verdict check.
 *      Live, /stock/INFY's headline read "n/a" while its description read
 *      "DCF implied value 1,079.32 vs 1,035.00 market". The meta description is the
 *      outermost surface in the product: what Google indexes, what Slack and X unfurl, what
 *      an answer engine quotes.
 *
 *   2. The DCF bridge's last row printed the implied share price in green, about 800px below
 *      the "n/a" headline, in the most emphatic styling on the page.
 *
 *   3. The OpenGraph card rendered the price as an IMAGE. A withheld figure there is worse
 *      than in the description: it is copied out of context, with no sentence beside it
 *      saying the model is withheld, and it is the version that ends up in a chat thread.
 *
 *   4. The homepage rail and the /stock index marked fourteen withheld models "Ready", with
 *      no reason anywhere on the page.
 *
 * WHY THESE TESTS ARE BEHAVIOURAL, AND WHY THE PREVIOUS VERSION WAS WORTHLESS
 *
 * The previous version of this file read `page.tsx` and `DCFSchedule.tsx` as text and
 * asserted that the strings `mayPublish && v?.implied` and `priceWithheld ? 'not
 * published` were present. It passed continuously while all four leaks above were live and
 * served, because a regex over source cannot tell whether the gate it found is the gate the
 * value passes through. `mayPublish && v?.implied` was in the file, in the `delta`
 * computation, while the description itself was built from `v?.implied` alone one line
 * later. The test was green over a page that published twelve withheld valuations.
 *
 * A source scan is a guard on the shape of the code. The failure mode here is a value
 * reaching a formatter by a path the scan does not model, and the only thing that observes
 * that path is running the code. So every assertion below calls the function that decides,
 * or reads the string that is actually served.
 */

import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { mayPublishPrice, withheldReason, withholdUnpublishedPrice } from './lib/publication.ts'
import type { ModelSpecWithVerdict, PublicationVerdict } from './lib/types.ts'

/**
 * A model the server refused to publish, carrying a real implied price.
 *
 * The price is present on purpose. That is the state the engine is actually in: the solve
 * runs, the number exists, and the verdict says it may not be shown. A fixture with the
 * price already absent would pass every test here while the product leaked, because it
 * would test the empty case.
 */
function withheldSpec(): ModelSpecWithVerdict {
  return {
    metadata: { company_id: 'infy_infy', ticker: 'INFY', name: 'Infosys', currency: 'INR' },
    valuation: [
      {
        scenario: 'base',
        dcf_bridge: {
          enterprise_value: 1_234_567,
          equity_value: 987_654,
          shares_outstanding: 100,
          implied_share_price: 1079.32,
        },
        reverse_dcf: { market_price: 1035.0 },
      },
    ],
    publication: {
      status: 'opinion_only',
      publishable: false,
      reasons: ['inputs_trace_to_a_filing: no filing contributed to this company'],
    },
  } as unknown as ModelSpecWithVerdict
}

function publishableSpec(): ModelSpecWithVerdict {
  return {
    ...withheldSpec(),
    publication: {
      status: 'publishable',
      publishable: true,
      reasons: [],
    },
  } as unknown as ModelSpecWithVerdict
}

test('a withheld model keeps its computed price in the payload it is given', () => {
  // The starting position, stated so a later change cannot quietly redefine it. The
  // engine computes the number; the verdict decides whether it may be shown. A test
  // suite that assumed the payload was already clean would pass while the page leaked.
  const spec = withheldSpec()
  assert.equal(spec.valuation[0].dcf_bridge.implied_share_price, 1079.32)
  assert.equal(mayPublishPrice(spec), false)
})

test('mayPublishPrice refuses a verdict of false and no verdict at all', () => {
  // The handoff recorded a wrong diagnosis here: that this function was broken and
  // should be rewritten to fail closed. It already did. It is correct, and the fix was
  // somewhere else entirely. Pinned so the next reader does not "repair" it again.
  const spec = withheldSpec()

  assert.equal(
    mayPublishPrice(spec),
    false,
    'a verdict of publishable: false must refuse',
  )
  assert.equal(
    mayPublishPrice(spec, { publishable: false } as PublicationVerdict),
    false,
    'an explicitly passed verdict of false must refuse',
  )
  assert.equal(
    mayPublishPrice({ ...spec, publication: undefined } as unknown as ModelSpecWithVerdict),
    false,
    'a payload carrying no verdict must refuse, not fall through to publishable',
  )
  assert.equal(
    mayPublishPrice(null),
    false,
    'no spec must refuse',
  )
  assert.equal(
    mayPublishPrice(publishableSpec()),
    true,
    'a publishable verdict must permit, or the nine published models lose their price',
  )
})

test('withholdUnpublishedPrice removes the figure from every scenario of a withheld model', () => {
  const spec = withheldSpec()
  spec.valuation.push({
    ...spec.valuation[0],
    scenario: 'bull',
    dcf_bridge: { ...spec.valuation[0].dcf_bridge, implied_share_price: 1402.1 },
  } as never)

  const shown = withholdUnpublishedPrice(spec)

  assert.equal(
    shown.valuation[0].dcf_bridge.implied_share_price,
    null,
    'the base scenario still carries the withheld price',
  )
  assert.equal(
    shown.valuation[1].dcf_bridge.implied_share_price,
    null,
    'gating only the first scenario leaves bull and bear printing it',
  )
})

test('withholdUnpublishedPrice leaves the evidence a reader needs to disagree', () => {
  // Withholding the price must not withhold the inputs it was derived from. The
  // product's claim is "here is what we ran, and here is why we will not call it a
  // valuation", and a page that hides the bridge too has made that claim
  // unfalsifiable, which is the mistake the API docstring warns about.
  const shown = withholdUnpublishedPrice(withheldSpec())
  const bridge = shown.valuation[0].dcf_bridge

  assert.equal(bridge.enterprise_value, 1_234_567)
  assert.equal(bridge.equity_value, 987_654)
  assert.equal(bridge.shares_outstanding, 100)
  assert.equal(shown.valuation[0].reverse_dcf.market_price, 1035.0)
  assert.equal(
    shown.publication?.publishable,
    false,
    'the verdict must survive, or the page cannot say WHY it withheld',
  )
  assert.match(
    withheldReason(shown) ?? '',
    /inputs_trace_to_a_filing/,
    'the reason a reader is shown must name the check that failed',
  )
})

test('the terminal share survives withholding while the price does not', () => {
  // The KPI bar shows "Terminal value 72.0% of EV" beside EV and equity from
  // pv_terminal_value over enterprise_value, and it shows it on withheld pages
  // too. That is only safe because the gate nulls the implied price alone. If a
  // later change widens the gate to the bridge, the ratio silently becomes n/a;
  // if it narrows the gate, a positive withheld price renders beside it.
  const spec = withheldSpec()
  spec.valuation[0].dcf_bridge.pv_terminal_value = 888_888
  spec.valuation[0].dcf_bridge.sum_pv_fcff = 345_679

  const shown = withholdUnpublishedPrice(spec)
  const bridge = shown.valuation[0].dcf_bridge

  assert.equal(
    bridge.implied_share_price,
    null,
    'a positive withheld price must not render anywhere, including beside TV%',
  )
  assert.equal(
    bridge.enterprise_value,
    1_234_567,
    'EV must survive withholding or the terminal share cannot be computed',
  )
  assert.equal(
    bridge.pv_terminal_value,
    888_888,
    'PV TV must survive withholding or the terminal share cannot be computed',
  )
  const tvPct = (bridge.pv_terminal_value / bridge.enterprise_value) * 100
  assert.ok(
    tvPct > 0 && tvPct <= 100,
    `the terminal share must be a positive share of EV, got ${tvPct}`,
  )
})

test('withholdUnpublishedPrice does not touch a model the server published', () => {
  const spec = publishableSpec()
  const shown = withholdUnpublishedPrice(spec)

  assert.equal(
    shown.valuation[0].dcf_bridge.implied_share_price,
    1079.32,
    'the gate removed the price from a PUBLISHABLE model. Nine of twenty-three models '
      + 'publish, and a gate that withholds from them too is a defect of the same '
      + 'shape as the leak: a rule applied without reading its input.',
  )
})

test('withholdUnpublishedPrice returns null and undefined untouched', () => {
  // A cold or sleeping backend degrades to null and the route renders a shell that the
  // client fills in. Throwing here would turn a degraded page into a 500.
  assert.equal(withholdUnpublishedPrice(null), null)
  assert.equal(withholdUnpublishedPrice(undefined), undefined)
})

test('withholdUnpublishedPrice does not mutate the specification it was given', () => {
  // It clones the valuation array rather than editing in place, because the same
  // object is the API response for the exports and for the client cache. An in-place
  // edit would remove the figure from `/api/model/{id}` as a side effect of rendering
  // a page, which is the API contract the Excel and JSON exports read.
  const spec = withheldSpec()
  withholdUnpublishedPrice(spec)

  assert.equal(
    spec.valuation[0].dcf_bridge.implied_share_price,
    1079.32,
    'the call mutated its argument, so serving a page rewrote the API payload',
  )
})

test('the boundary every server-rendered page reads a model through withholds the price', () => {
  // The wiring, which is the one thing a behavioural test cannot reach: the functions
  // above are pure, and a pure function nobody calls protects nothing. Read as text
  // rather than by importing, because `serverApi.ts` reaches `process.env` and `fetch`
  // at module scope and importing it here would test the environment instead of the
  // call.
  //
  // This is a source scan, and it is here DELIBERATELY and ONLY for the call site. The
  // leak this file exists to prevent was not a wrong rule, it was a rule applied in the
  // wrong place; the wrongness of a rule is decided behaviourally and the placement is
  // only visible in the text.
  const serverApi = readFileSync(join(import.meta.dirname, 'lib', 'serverApi.ts'), 'utf8')
  assert.match(
    serverApi,
    /return withholdUnpublishedPrice\(/,
    'getModelSpecServer must withhold the unpublished price at the boundary. It is the ' +
      'single function the ticker page, the OpenGraph card, the homepage rail and the ' +
      'prerender all read a model through. Without it, each surface has to remember the ' +
      'verdict alone, and of the six that did, four forgot.',
  )

  // The client-side fetch path is a second boundary, not a variant of the first: a cold
  // backend degrades the server fetch to null and the browser fetches the model itself,
  // so a gate applied only on the server leaves the degraded path ungated.
  const clientApi = readFileSync(join(import.meta.dirname, 'lib', 'api.ts'), 'utf8')
  assert.match(
    clientApi,
    /withholdUnpublishedPrice\(/,
    'the client fetch path must withhold too, or a cold backend reintroduces the leak ' +
      'on exactly the pages that could least afford it',
  )
})
