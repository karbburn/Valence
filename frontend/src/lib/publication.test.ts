import { test } from 'node:test'
import assert from 'node:assert/strict'

import { mayPublishPrice, withheldReason } from './publication.ts'
import type { ModelCheckResult, ModelSpecification, PublicationVerdict } from './types.ts'

function specWith(...checks: Array<Partial<ModelCheckResult>>): ModelSpecification {
  return {
    qa: { checks: checks.map((c) => ({ passed: true, detail: '', ...c })) },
  } as unknown as ModelSpecification
}

const VERDICT_NOT_PUBLISHABLE: PublicationVerdict = {
  status: 'opinion_only',
  publishable: false,
  input_defect_checks_failed: ['valuation_is_meaningful'],
  other_checks_failed: [],
  reasons: [],
  summary: '',
}

test('the server verdict decides, not a list of check names held here', () => {
  // The regression this guards: the client used to recompute publication from its
  // own hardcoded copy of the defect-check names, five of them, while the server
  // held eight. The two had already diverged, and a model failing only a newer
  // check would have shown a price the API called opinion_only.
  //
  // Here the spec fails a check this file has never heard of. Reading the server's
  // verdict is the only way that can be handled correctly, and a name list can
  // only ever be right until someone adds a check.
  const spec = specWith({ check_name: 'a_check_added_next_year', passed: false, detail: 'boom' })

  assert.equal(
    mayPublishPrice(spec, VERDICT_NOT_PUBLISHABLE),
    false,
    'a server verdict of opinion_only must withhold the price even for an unknown check',
  )
  assert.equal(
    mayPublishPrice(spec, { ...VERDICT_NOT_PUBLISHABLE, publishable: true, status: 'publishable' }),
    true,
    'a server verdict of publishable must be honoured',
  )
})

test('without a verdict, a model failing the meaningfulness check is not published', () => {
  const spec = specWith({
    check_name: 'valuation_is_meaningful',
    passed: false,
    detail: 'implied share price -62.40 is not positive',
  })
  assert.equal(mayPublishPrice(spec), false)
})

test('a disagreeing valuation is still published', () => {
  // The check that must NOT suppress: disagreement with the market is a view, and
  // publishing one is the product working. Conflating "disagrees" with "cannot be
  // true" would suppress every interesting result the site has.
  const spec = specWith({
    check_name: 'implied_price_deviation_is_explainable',
    passed: false,
    detail: 'base: implied 147.37 against a market price of 329.40 is -55.3%',
  })
  assert.equal(mayPublishPrice(spec), true)
})

test('no checks and no verdict is not publishable', () => {
  // Absence of evidence is not evidence of a number.
  assert.equal(mayPublishPrice(specWith()), false)
  assert.equal(mayPublishPrice(null), false)
})

test('the withheld reason quotes what actually failed', () => {
  const spec = specWith(
    { check_name: 'valuation_is_meaningful', passed: false, detail: 'enterprise value is -2,972' },
  )
  const reason = withheldReason(spec)
  assert.ok(reason?.includes('enterprise value is -2,972'), reason)
})

test('a publishable model has no withheld reason', () => {
  // A spec with a passing meaningfulness check, not an empty one. An empty spec is
  // withheld by design -- absence of evidence is not evidence of a number -- so
  // asserting undefined against one would have been asserting the opposite rule.
  const spec = specWith({ check_name: 'valuation_is_meaningful', passed: true })
  assert.equal(mayPublishPrice(spec), true)
  assert.equal(withheldReason(spec), undefined)
})
