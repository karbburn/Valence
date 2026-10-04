/**
 * The workbench header has to fit the width it promises, and its overflow menu has to be a
 * complete substitute for the controls it hides.
 *
 * The defect: the header is a single non-wrapping row in a fixed 48px bar, and it needed
 * 1416px. MobileGuard promised the workbench worked from 900px. Measured in a browser on
 * 2026-10-04:
 *
 *     900px  overflows by 500   scenario chips, QA, Copy, Save, Library, Excel all cut off
 *    1024px  overflows by 392   QA, Copy, Save, Library, Excel cut off
 *    1280px  overflows by 136   Library and Excel cut off, the Excel export by 132px
 *    1366px  overflows by  50   Excel cut off
 *    1440px  fits
 *
 * So the Excel export was unreachable at EVERY width from 900px to 1439px, not merely at the
 * 1280px the review recorded. And because the row does not wrap, the overflow always lands on
 * whichever control sits furthest right, which is the primary export.
 *
 * The fix collapses the four export actions into a menu below 1440px, which brings the row to
 * 1163px. Above 1440px nothing changes at all.
 *
 * **These assertions are about the SOURCE, not the rendered page, and that is a limitation
 * worth stating rather than hiding.** The layout numbers were measured in a real browser and
 * are hydration-independent, so they stand. The menu's BEHAVIOUR could not be exercised: that
 * browser session did not hydrate at all, and no control on the page responded, including
 * ones that predate this change. So "the menu opens and its items work" is NOT verified by
 * anything here, and this file does not claim it is. What it does assert is that the two
 * class lists cannot disagree, that no action is reachable through only one of the two
 * presentations, and that the guard's stated minimum cannot drift away from the width the
 * header actually needs.
 *
 * That last one is the durable part. The original defect was a guard promising 900px against a
 * layout needing 1416px, and nothing compared the two numbers. `the guard admits no width the
 * header cannot render` is the check that would have caught it.
 */

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const COMPONENTS = path.join(HERE, 'components')
const header = readFileSync(path.join(COMPONENTS, 'Header.tsx'), 'utf-8')
const guard = readFileSync(path.join(COMPONENTS, 'MobileGuard.tsx'), 'utf-8')

/** The width at which the header row fits, measured in a browser. */
const MEASURED_FLOOR = 1163
/** The width at which every control fits inline, also measured. */
const INLINE_FLOOR = 1440

test('the inline actions and the overflow menu are never both visible', () => {
  // One decision expressed in two class lists, because Tailwind cannot say "the other one".
  // A mismatch shows up as every control appearing twice, which reads as a duplicate-control
  // bug rather than an overflow.
  //
  // Asserted PER BUTTON, by locating each button's own className, and not by counting
  // occurrences of `max-[1439px]:hidden` in the file. The counting version was fooled by this
  // very test's sibling: the Library button carries a comment explaining why it uses the
  // max-width variant and not `hidden sm:flex`, and that comment contains the string twice.
  // So the count stayed above the threshold after a real button had been unhidden, and a
  // mutation that put the row back to 1416px passed. A source scan that cannot tell code from
  // commentary about the code is not measuring what it claims to.
  const buttons: [string, string][] = [
    ['onCopySummary', 'Copy memo'],
    ['onSave', 'Save'],
    ['onOpenSaved', 'Library'],
    ['onExportExcel', 'Excel'],
  ]

  const hideWidths = new Set<string>()
  for (const [handler, label] of buttons) {
    // The opening <button ...> tag carrying this onClick, then its className.
    const tag = new RegExp(
      `<button[^>]*onClick=\\{${handler}\\}[^>]*className="([^"]*)"`,
      's',
    ).exec(header)
    assert.ok(tag, `could not find the inline button for ${label} (onClick={${handler}})`)
    const classes = tag[1]
    const hide = /max-\[(\d+)px\]:hidden/.exec(classes)
    assert.ok(
      hide,
      `the inline ${label} button has no max-width hide, so below ${INLINE_FLOOR}px it ` +
        `renders alongside the menu and the row goes back to overflowing`,
    )
    hideWidths.add(hide[1])
  }

  assert.equal(
    hideWidths.size,
    1,
    `the inline buttons hide at different widths: ${[...hideWidths].join(', ')}. They must ` +
      `all hide together or the row overflows at some widths and not others.`,
  )

  const menuWrap = /min-\[(\d+)px\]:hidden/.exec(header)
  assert.ok(menuWrap, 'the overflow menu wrapper has no min-width hide, so it would show at 1440px too')
  assert.equal(
    Number(menuWrap[1]),
    INLINE_FLOOR,
    `the menu appears at ${menuWrap[1]}px but the inline controls are kept until ` +
      `${[...hideWidths][0]}px. Between the two widths either both are visible or neither is.`,
  )
})

test('the overflow menu carries every action the inline row carries', () => {
  // The four inline buttons and the four menu entries must stay the same set. An action
  // reachable only inline is off-screen at exactly the widths the menu exists to serve, and
  // an action reachable only from the menu disappears entirely at 1440px and above.
  //
  // Two regions, because they live in two places: ACTION_ITEMS is declared above the return,
  // and the inline buttons are inside the nav. Reading the menu out of the nav -- which the
  // first version of this test did -- finds nothing and reports it as a missing entry.
  const itemsStart = header.indexOf('const ACTION_ITEMS')
  assert.ok(itemsStart > 0, 'ACTION_ITEMS is gone from the header')
  const items = header.slice(itemsStart, header.indexOf('\n  ]', itemsStart))

  const navStart = header.indexOf('aria-label="Model actions"')
  assert.ok(navStart > 0, 'the actions nav is missing from the header')
  const nav = header.slice(navStart, header.indexOf('</nav>', navStart))

  const handlers: [string, string][] = [
    ['copy', 'onCopySummary'],
    ['save', 'onSave'],
    ['library', 'onOpenSaved'],
    ['excel', 'onExportExcel'],
  ]

  for (const [key, handler] of handlers) {
    const keyIndex = items.indexOf(`key: '${key}'`)
    assert.ok(keyIndex >= 0, `the overflow menu has no entry for ${key}`)
    const run = /run: \(\) => runAction\((on[A-Za-z]+)\)/.exec(items.slice(keyIndex, keyIndex + 400))
    assert.ok(run, `the menu entry for ${key} does not call runAction`)
    assert.equal(
      run[1],
      handler,
      `the menu entry for ${key} calls ${run[1]} but the inline button calls ${handler}. ` +
        `One of them would do something the other does not.`,
    )
    const entry = items.slice(keyIndex, items.indexOf('},', keyIndex))
    assert.ok(
      key === 'save' || entry.includes('hint:'),
      `the menu entry for ${key} has no hint, so the inline button's explanation is lost ` +
        `with it. Save never had a title, so it is the only one exempt.`,
    )
  }

  // And the inline row still wires each handler.
  for (const [, handler] of handlers) {
    assert.ok(
      new RegExp(`onClick={${handler}}`).test(nav),
      `the inline button for ${handler} is gone, so the control is unreachable above 1440px`,
    )
  }

  assert.equal(
    (items.match(/^\s+key: '/gm) ?? []).length,
    handlers.length,
    'the menu has a different number of entries than the inline row has buttons',
  )
})

test('the menu is a real disclosure, not a div that happens to be clickable', () => {
  for (const [what, needle] of [
    ['the trigger declares aria-haspopup', 'aria-haspopup="menu"'],
    ['the trigger reports its state', 'aria-expanded={actionsOpen}'],
    ['the panel is a menu', 'role="menu"'],
    ['each entry is a menu item', 'role="menuitem"'],
    ['the panel is labelled', 'aria-label="Model actions"'],
    ['Escape closes it', "e.key !== 'Escape'"],
    ['a click outside closes it', "addEventListener('pointerdown', onPointerDown)"],
    ['both listeners are removed on unmount', "removeEventListener('pointerdown', onPointerDown)"],
    ['Escape returns focus to the trigger', 'actionsButtonRef.current?.focus()'],
  ] as [string, string][]) {
    assert.ok(header.includes(needle), `${what} is missing: ${needle} not found in Header.tsx`)
  }
})

test('the guard admits no width the header cannot render', () => {
  // The durable check. The original defect was a guard promising 900px against a layout
  // needing 1416px, and nothing anywhere compared the two numbers.
  const m = /min-\[(\d+)px\]:hidden/.exec(guard)
  assert.ok(m, 'MobileGuard no longer states a minimum width, so it admits every viewport')
  const stated = Number(m[1])

  assert.equal(
    stated,
    MEASURED_FLOOR,
    `MobileGuard admits ${stated}px. The header row was measured to fit at ${MEASURED_FLOOR}px ` +
      `and to overflow by 1px at ${MEASURED_FLOOR - 1}px, so a threshold above ` +
      `${MEASURED_FLOOR} needlessly hides a working workbench and a threshold below it admits ` +
      `one with controls off the edge.`,
  )

  // The number is also stated to the visitor, in two places. If those drift from the class,
  // the guard and its own message disagree, which is the defect one layer down.
  const inCopy = [...guard.matchAll(/at least (\d+)px wide/g)].map((x) => Number(x[1]))
  assert.deepEqual(
    inCopy,
    [stated, stated],
    `the prose says ${JSON.stringify(inCopy)}px while the class says ${stated}px`,
  )
  assert.ok(
    guard.includes(`MINIMUM VIEWPORT: ${stated}PX`),
    `the badge does not state ${stated}px`,
  )
})

test('the measured floor is recorded where the layout is, not only in the guard', () => {
  // The number came from a browser sweep. A comment that cites it next to the class lists is
  // what lets the next person check it rather than re-derive it from a guess.
  assert.ok(
    header.includes(String(MEASURED_FLOOR)),
    `Header.tsx does not mention the measured floor of ${MEASURED_FLOOR}px, so the number in ` +
      `MobileGuard has no visible derivation`,
  )
  assert.ok(
    header.includes(String(INLINE_FLOOR)),
    `Header.tsx does not mention the ${INLINE_FLOOR}px inline width either`,
  )
})