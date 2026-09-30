/**
 * A model that is not read from the accounts must say so.
 *
 * The product claims every published figure matches an official filing. That is true
 * for nine of the twenty-three shipped companies and false for the other fourteen,
 * because a Screener.in export or a market feed is a real number about a real
 * company but not the number the filer published.
 *
 * The tie-out has measured what the difference costs, which is what makes this a
 * correctness matter rather than a disclosure nicety: the Infosys ADR publishes
 * 1,043 of current investments where its own 20-F says 1,365, and no non-current
 * investments where the filing says 942. A reader shown only the valuation has no
 * way to know which kind of number they are looking at, and the two support
 * different amounts of confidence.
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { provenanceLabel, provenanceTitleText, provenanceTone } from './provenance.ts'

test('a filing-derived model says it came from the filer', () => {
  const tone = provenanceTone(true, 'sec_edgar')
  assert.equal(tone, 'filing')
  const label = provenanceLabel(true, 'sec_edgar', { sec_edgar: 127, yfinance_live: 6 })
  assert.equal(label, 'From SEC EDGAR')
})

test('a market-fed model says it did not come from the accounts', () => {
  assert.equal(provenanceTone(false, null), 'market')
  const label = provenanceLabel(false, null, { yfinance_live: 81 })
  assert.ok(label.includes('not the accounts'), label)
  assert.ok(label.includes('market feed'), label)
})

test('a fixture-fed model does not blame a third-party aggregator', () => {
  // The files the screener reader parses are not Screener.in exports. They are
  // written by `generate_sources.py` in this repository, which hand-enters the
  // numbers and whose own comment calls the most recent year an estimate. Naming
  // Screener.in would attribute hand-entered figures to a named data provider, and
  // a reader checking that provider would find nothing.
  const label = provenanceLabel(false, null, { screener: 75, yfinance_live: 15 })
  assert.ok(!/Screener/i.test(label), `a fixture was attributed to Screener.in: ${label}`)
  assert.ok(/fixture/i.test(label), label)
  assert.ok(!/SEC|EDGAR|filing/i.test(label), `a fixture was presented as a filing: ${label}`)
})

test('a mixed model is neither claimed nor denied', () => {
  assert.equal(provenanceTone(false, 'nse_filing'), 'mixed')
  const label = provenanceLabel(false, 'nse_filing', { nse_filing: 260, screener: 305 })
  assert.ok(/Mostly/i.test(label), label)
  assert.ok(label.includes('NSE filing'), label)
})

test('a flag alone cannot talk the page into the filing claim', () => {
  // Defence in depth against the backend's own flag being wrong or repurposed: the
  // page only says "from the accounts" when a real filing source is behind it.
  assert.notEqual(provenanceTone(true, 'screener'), 'filing')
  assert.notEqual(provenanceTone(true, 'yfinance_live'), 'filing')
  assert.notEqual(provenanceTone(true, null), 'filing')
  assert.equal(provenanceTone(true, 'screener'), 'market')
  assert.ok(
    !/SEC|EDGAR/i.test(provenanceLabel(true, 'screener', { screener: 75 })),
    'a screener flag must not produce a filing claim',
  )
})

test('the hover text justifies the claim in both directions', () => {
  const filing = provenanceTitleText({
    filing_derived: true,
    filing_source: 'sec_edgar',
    data_sources: { sec_edgar: 127, yfinance_live: 6 },
  })
  assert.ok(/tied to a filing/i.test(filing), filing)

  const feed = provenanceTitleText({
    filing_derived: false,
    filing_source: null,
    data_sources: { yfinance_live: 81 },
  })
  assert.ok(/NOT read from the filer/i.test(feed), feed)
  assert.ok(/differing/i.test(feed), 'the measured disagreement belongs in the explanation')
})

test('an unrecorded source says so rather than implying one', () => {
  const title = provenanceTitleText({ filing_derived: null, data_sources: null })
  assert.ok(/does not record/i.test(title), title)
  assert.equal(
    provenanceLabel(false, null, null),
    'Source not recorded',
  )
})

test('no model is ever described as filing-derived without a filing source', () => {
  // The claim is the whole point, so it is guarded: nothing may say "from the
  // accounts" unless an actual filing source is behind it.
  for (const [derived, source, sources] of [
    [false, null, { yfinance_live: 81 }],
    [false, null, { screener: 75 }],
    [null, null, {}],
  ] as const) {
    const title = provenanceTitleText({
      filing_derived: derived,
      filing_source: source,
      data_sources: sources,
    })
    assert.ok(!/can be tied to a filing/i.test(title), title)
  }
})

test('a filing_derived flag cannot carry the filing claim by itself', () => {
  // The regression this guards: the flag said filing-derived, the source named a
  // local fixture, and the hover text read "These figures are read from the
  // filer's own accounts: a local fixture file. Every published number on this
  // page can be tied to a filing." The label beside it said "not the accounts".
  //
  // The original test only ever passed derived=false or null, so the one case
  // that matters -- the flag asserting exactly what the source contradicts -- was
  // never exercised. A guard tested only in its passing state is not a guard.
  for (const source of ['screener', 'local_export', 'yfinance_live', 'twelvedata']) {
    const title = provenanceTitleText({
      filing_derived: true,
      filing_source: source,
      data_sources: { [source]: 75 },
    })
    assert.ok(
      !/can be tied to a filing/i.test(title),
      `a ${source}-sourced model was described as tied to a filing: ${title}`,
    )
    assert.ok(
      !/read from the filer.s own accounts/i.test(title),
      `a ${source}-sourced model was described as read from the accounts: ${title}`,
    )
  }
})

test('a filing_derived flag with no source is called a disagreement', () => {
  // One of the two is wrong. A reader told which can act; a reader handed a
  // confident answer cannot.
  const title = provenanceTitleText({
    filing_derived: true,
    filing_source: null,
    data_sources: { sec_edgar: 105 },
  })
  assert.ok(!/can be tied to a filing/i.test(title), title)
  assert.ok(/disagree|not established/i.test(title), title)
})
