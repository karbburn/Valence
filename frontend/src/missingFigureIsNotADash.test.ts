/**
 * A missing figure is marked "n/a" and never with a dash.
 *
 * `noValue.ts` already argues this, and the argument is the product's: these are financial
 * tables, a horizontal stroke already means a negative number, and `-5.0%` and "the engine
 * produced no figure" were the same glyph in the same column at the same size. A reader
 * scanning for downside could not tell a loss from a gap, and a screen reader announced
 * the same word for both.
 *
 * The four formatters ignored that and returned an em-dash, so the codebase carried both
 * conventions at once: 30 call sites pass `NO_VALUE` themselves and the formatter said
 * something else for whoever did not. Two marks for one fact, chosen by which component
 * asked, is the defect. The fix is one import, and this file is what stops the em-dash
 * coming back through a fifth formatter.
 *
 * A negative number and a missing number must also remain distinguishable in the OUTPUT,
 * not merely in the source: that is the property the mark exists to preserve, and it is
 * only observable by formatting both and comparing.
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import { fmtMoney, fmtNum, fmtPct, fmtPrice } from './lib/formatters.ts'
import { NO_VALUE } from './lib/noValue.ts'

const MISSING: Array<[string, number | null | undefined]> = [
  ['null', null],
  ['undefined', undefined],
  ['NaN', NaN],
]

test('no formatter renders a missing figure as a dash', () => {
  for (const [label, value] of MISSING) {
    for (const [name, out] of [
      ['fmtNum', fmtNum(value)],
      ['fmtNum(2dp)', fmtNum(value, 2)],
      ['fmtPrice', fmtPrice(value, 'INR')],
      ['fmtPrice USD', fmtPrice(value, 'USD')],
      ['fmtMoney', fmtMoney(value, 'INR')],
      ['fmtMoney USD', fmtMoney(value, 'USD')],
      ['fmtPct', fmtPct(value)],
    ] as Array<[string, string]>) {
      assert.equal(
        out,
        NO_VALUE,
        `${name}(${label}) rendered ${JSON.stringify(out)}. A dash in a financial table ` +
          `reads as a negative number, and the engine declining to produce a figure is a ` +
          `different fact.`,
      )
      assert.ok(
        !/[—–-]/.test(out),
        `${name}(${label}) rendered a stroke: ${JSON.stringify(out)}`,
      )
    }
  }
})

test('a negative figure and a missing one render differently', () => {
  // The reason the mark exists. Asserted on the rendered output of both, because the
  // distinction is invisible in the source once the constant is factored out.
  const negative = fmtPct(-5, 1)
  const missing = fmtPct(null)

  assert.equal(negative, '-5.0%')
  assert.equal(missing, NO_VALUE)
  assert.notEqual(negative, missing)

  // USD values arrive in millions, so 2,500,000 is $2.50T and not $2.50B. The first
  // version of this test asserted B and failed against correct code: the formatter's unit
  // convention is not the one a reader assumes, and the test was the thing that was wrong.
  const negMoney = fmtMoney(-2_500_000, 'USD')
  assert.equal(negMoney, '-$2.50T')
  assert.equal(fmtMoney(null, 'USD'), NO_VALUE)
  assert.notEqual(negMoney, fmtMoney(null, 'USD'))
})

test('a real figure still formats, so the guard is not swallowing values', () => {
  assert.equal(fmtNum(1079.32, 2), '1,079.32')
  assert.equal(fmtPrice(1079.32, 'INR'), '₹1,079.32')
  assert.equal(fmtPrice(156.48, 'USD'), '$156.48')
  assert.equal(fmtPct(12.746, 1), '12.7%')
  assert.equal(fmtMoney(172_239.57, 'INR'), '₹1.72L Cr')
  assert.equal(fmtMoney(2_500, 'USD'), '$2.5B')
})
