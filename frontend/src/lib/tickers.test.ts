/**
 * Slug rules and the allowlist boundary.
 *
 * Run with: node --test --experimental-strip-types src/lib/tickers.test.ts
 *
 * These are the functions every per-ticker route depends on, and the shape gate
 * is the only thing standing between a public URL and the model endpoint. The
 * routing itself is exercised against a running server; what is pinned here is
 * the pure logic, which is where a regression would be silent.
 */

import test from 'node:test'
import assert from 'node:assert/strict'

import {
  SLUG_PATTERN,
  isValidSlug,
  normalizeSlug,
  stockPath,
  stockUrl,
  slugFromPath,
  isBareTickerPath,
} from './tickers.ts'

// --------------------------------------------------------------------------- //
// Shape gate
// --------------------------------------------------------------------------- //

test('accepts a bare ticker', () => {
  assert.equal(isValidSlug('NVDA'), true)
  assert.equal(isValidSlug('LT'), true)
  assert.equal(isValidSlug('BRK.B'), true)
  assert.equal(isValidSlug('BAJAJ-AUTO'), true)
})

test('accepts a disambiguated sibling', () => {
  assert.equal(isValidSlug('INFY-NYSE'), true)
  assert.equal(isValidSlug('ABCD-1234567'), true)
})

test('rejects anything that could escape a path or reach a query', () => {
  const hostile = [
    '',
    ' ',
    '..',
    '../..',
    '../../etc/passwd',
    'NVDA/../../secret',
    'NVDA;DROP TABLE',
    'NVDA?x=1',
    'NVDA#frag',
    'a'.repeat(33),
    '-leading-dash',
    '.leading-dot',
  ]
  for (const bad of hostile) {
    assert.equal(isValidSlug(bad), false, `${JSON.stringify(bad)} should be rejected`)
  }
})

test('rejects non-strings without throwing', () => {
  assert.equal(isValidSlug(null), false)
  assert.equal(isValidSlug(undefined), false)
  // Cast because the point of the case is runtime behaviour on untrusted input,
  // which is exactly the input the type system is supposed to prevent.
  assert.equal(isValidSlug(42 as unknown as string), false)
  assert.equal(isValidSlug({} as unknown as string), false)
  assert.equal(isValidSlug([] as unknown as string), false)
})

test('tolerates surrounding whitespace, because the route strips before checking', () => {
  assert.equal(isValidSlug('  NVDA  '), true)
})

test('pattern and predicate agree', () => {
  for (const candidate of ['NVDA', 'BRK.B', 'INFY-NYSE', '../x', 'A'.repeat(40)]) {
    assert.equal(
      isValidSlug(candidate),
      SLUG_PATTERN.test(candidate.trim()),
      `disagreement on ${candidate}`
    )
  }
})

// --------------------------------------------------------------------------- //
// Normalisation
// --------------------------------------------------------------------------- //

test('normalises case', () => {
  assert.equal(normalizeSlug('nvda'), 'NVDA')
  assert.equal(normalizeSlug('Nvda'), 'NVDA')
  assert.equal(normalizeSlug('  infy-nyse  '), 'INFY-NYSE')
})

test('normalisation is idempotent', () => {
  assert.equal(normalizeSlug(normalizeSlug('brk.b')), 'BRK.B')
})

// --------------------------------------------------------------------------- //
// Paths
// --------------------------------------------------------------------------- //

test('builds the canonical stock path', () => {
  assert.equal(stockPath('NVDA'), '/stock/NVDA')
  assert.equal(stockPath('INFY-NYSE'), '/stock/INFY-NYSE')
})

test('encodes a slug that needs it', () => {
  // BRK.B is valid unencoded, but the builder must not emit a raw character that
  // some proxy or CDN decides to normalise differently.
  assert.equal(stockPath('BRK.B'), '/stock/BRK.B')
  assert.equal(stockPath('A B'), '/stock/A%20B')
})

test('builds an absolute url without doubling the slash', () => {
  assert.equal(
    stockUrl('https://valence.sourabhpradhan.in', 'NVDA'),
    'https://valence.sourabhpradhan.in/stock/NVDA'
  )
  assert.equal(
    stockUrl('https://valence.sourabhpradhan.in/', 'NVDA'),
    'https://valence.sourabhpradhan.in/stock/NVDA'
  )
})

// --------------------------------------------------------------------------- //
// Reading a slug back out of a path
// --------------------------------------------------------------------------- //

test('reads a slug from the canonical path', () => {
  assert.equal(slugFromPath('/stock/NVDA'), 'NVDA')
  assert.equal(slugFromPath('/stock/INFY-NYSE'), 'INFY-NYSE')
})

test('reads a slug from the bare alias path', () => {
  // A popstate handler has to cope with whichever form the address bar holds.
  assert.equal(slugFromPath('/NVDA'), 'NVDA')
  assert.equal(slugFromPath('/infy-nyse'), 'INFY-NYSE')
})

test('reads a slug from a nested path without being fooled by it', () => {
  assert.equal(slugFromPath('/a/b/c'), null)
  assert.equal(slugFromPath('/stock/a/b'), null)
})

test('returns null for paths that carry no candidate', () => {
  assert.equal(slugFromPath('/'), null)
  assert.equal(slugFromPath('/a/b/c'), null)
  assert.equal(slugFromPath('/stock/a/b'), null)
  assert.equal(slugFromPath('/stock/..'), null)
  assert.equal(slugFromPath('/%2e%2e%2f'), null)
})

test('reserved route names are never read as tickers', () => {
  // A single word is indistinguishable from a ticker by shape, so the route
  // names are excluded explicitly. Without this, /stock parses as a ticker
  // called "stock" and the index page looks like a broken company.
  for (const reserved of ['/stock', '/methodology', '/api', '/_next', '/icon']) {
    assert.equal(slugFromPath(reserved), null, `${reserved} should not parse as a slug`)
    assert.equal(isBareTickerPath(reserved), false, `${reserved} should not be an alias`)
  }
})

test('a single unknown word is still a candidate, and the allowlist decides', () => {
  // Shape alone cannot tell /ZZZZ from /NVDA. It is returned as a candidate and
  // the server route resolves it, which returns 404 for anything unknown.
  assert.equal(slugFromPath('/ZZZZ'), 'ZZZZ')
})

test('returns null for a malformed segment', () => {
  assert.equal(slugFromPath('/stock/..'), null)
  assert.equal(slugFromPath('/%2e%2e%2f'), null)
})

// --------------------------------------------------------------------------- //
// Bare-path detection
// --------------------------------------------------------------------------- //

test('identifies the bare alias that should redirect', () => {
  assert.equal(isBareTickerPath('/NVDA'), true)
  assert.equal(isBareTickerPath('/nvda'), true)
  assert.equal(isBareTickerPath('/INFY-NYSE'), true)
})

test('does not treat canonical or non-ticker paths as aliases', () => {
  assert.equal(isBareTickerPath('/stock/NVDA'), false)
  assert.equal(isBareTickerPath('/'), false)
  assert.equal(isBareTickerPath('/stock'), false)
  assert.equal(isBareTickerPath('/a/b'), false)
})
