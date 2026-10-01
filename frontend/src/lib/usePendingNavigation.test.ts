import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const HOOK = readFileSync(new URL('./usePendingNavigation.ts', import.meta.url), 'utf8')
const CARD = readFileSync(
  new URL('../components/CompanyCard.tsx', import.meta.url),
  'utf8'
)
const SEARCH = readFileSync(
  new URL('../components/landing/TickerSearch.tsx', import.meta.url),
  'utf8'
)

/**
 * Why navigation has to acknowledge itself.
 *
 * `router.push()` is fire-and-forget. Between the click and the first paint of the
 * destination nothing changes on screen, and on this site that gap is five seconds or
 * more because the destination compiles the model before it renders anything. A
 * visitor cannot distinguish a navigation in progress from a dropped click, so they
 * click again, and the second click is a second model build competing with the first
 * for the same throttle. The retry makes the wait worse.
 *
 * These assert the mechanism, because the symptom is a screenshot and nobody files
 * a bug saying "the page did not blink".
 */
test('navigation goes through a transition so pending is truthful', () => {
  assert.match(HOOK, /useTransition/, 'pending must come from a transition, not a timer')
  assert.match(HOOK, /startTransition\(\(\) => \{\s*router\.push\(href\)/)
})

test('only the activated row is marked pending', () => {
  // A list has to say WHICH item was chosen. Dimming all twenty tells the reader
  // something happened without telling them what they did.
  assert.match(HOOK, /pendingTo/)
  assert.match(HOOK, /setPendingTo\(key \?\? href\)/)
  assert.ok(
    /if \(pendingTo\) return/.test(HOOK),
    'extra clicks must be ignored while a navigation is in flight, or the retry ' +
      'problem is only half fixed'
  )
})

test('the coverage card marks itself pending on click', () => {
  assert.match(CARD, /usePendingNavigation/, 'the card must acknowledge the click')
  assert.match(CARD, /pendingTo === companyId/)
  assert.match(CARD, /aria-busy=\{isPending\}/, 'assistive tech needs the same signal')
})

test('a modified click still opens a new tab', () => {
  // Intercepting every click would silently break ctrl-click and middle-click, which
  // is a regression in exchange for a nicer pending state.
  assert.match(CARD, /metaKey \|\| e\.ctrlKey \|\| e\.shiftKey/)
})

test('the search dropdown marks the row it navigated from', () => {
  assert.match(SEARCH, /usePendingNavigation/)
  assert.match(SEARCH, /navigate\(stockPath\(c\.slug\), c\.company_id\)/)
  assert.match(SEARCH, /aria-busy=\{pendingTo === c\.company_id\}/)
  assert.ok(
    !/router\.push\(/.test(SEARCH),
    'a bare router.push bypasses the pending state, which is the defect itself'
  )
})