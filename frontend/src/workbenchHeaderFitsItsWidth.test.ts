/**
 * The workbench header has to fit the width it promises, and its overflow menus have to be
 * complete substitutes for the controls they hide.
 *
 * THE DEFECT: the header is a single non-wrapping row in a fixed 48px bar, and it needed
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
 * THE FIX, in two steps:
 *
 * 1. 2026-10-04: the four export actions collapse into a menu below 1440px, which brings the
 *    row to 1163px (exact, per-pixel sweep), and the guard was corrected from its stale 900px
 *    promise to 1163px in the same change. Admitting fewer widths is better than admitting
 *    widths with controls off-screen, but it walled off every 900 to 1162px visitor.
 * 2. 2026-10-06: below 1163px the row is compacted rather than truncated -- the view tabs
 *    relocate into a labelled menu, the QA badge shows its icon in all four states, the
 *    wordmark gives its 73px back, the scenario gap number moves to the chip's tooltip. No
 *    control is removed, only relocated. Worst-case row requirement measured on the widest
 *    composition found (long company name at the badge's 190px cap, longest view label,
 *    widest in-band search): 839.5px below 1024, 855.5px from 1024 to 1162. The guard is
 *    therefore restored to 900px, the promise the product started with, with 60px clear.
 *    The 840 to 899px remainder would fit the row alone and is deliberately not claimed: the
 *    body was verified only from 900px up, and no common device lands in that band.
 *
 * BOUNDARY SEMANTICS, measured from the generated stylesheet on 2026-10-06: this build
 * compiles `max-[Npx]` to `@media not (min-width: Npx)`, which is STRICTLY below N rather
 * than up to it. A pair stated as max-1162 / min-1163 therefore leaves exactly 1162px with
 * both presentations on screen -- measured: tabs and trigger together there, the row
 * overflowing to 1276px -- and max-1439 / min-1440 put the four inline actions beside their
 * own menu at vw1439, overflowing to 1447px. Both pairs now state the same number on both
 * sides, which partitions exactly under these semantics, and the tests below pin it.
 *
 * WHAT IS VERIFIED WHERE, stated rather than assumed:
 *
 * - Layout numbers were measured in a real browser and are hydration-independent: the 2026-
 *   10-04 sweep above, and on 2026-10-06 the compact band's worst case plus a boundary sweep
 *   across 899/900/1161/1162/1163/1439/1440 showing exactly one presentation at each width
 *   and document scroll equal to viewport at all of them.
 * - Menu BEHAVIOUR was exercised live in a hydrated browser on 2026-10-06: both menus open
 *   and report aria-expanded, list their entries, close on selection, on Escape and on an
 *   outside click; Escape returns focus to the trigger; selecting a view switches the mode
 *   in every place it is expressed; the scenario radios respond. (This environment had been
 *   non-hydrating because the dev server blocks its dev resources for the 127.0.0.1 origin;
 *   `allowedDevOrigins` in next.config.ts restored it.)
 * - What THIS file asserts is the source-level contract, which cannot drift silently: the
 *   paired class lists cannot disagree, no action lives in only one presentation, every QA
 *   state keeps its word off the narrow band while its aria-label keeps it for assistive
 *   tech, the header's h1 and the guard's h1 stay pinned to the same width, and the guard's
 *   stated minimum can neither admit what the row cannot render nor sit far above what it
 *   needs.
 *
 * The last one is the durable part. The original defect was a guard promising 900px against
 * a layout needing 1416px, and nothing anywhere compared the two numbers -- and its mirror,
 * a guard far ABOVE what the layout needs, is how 900 became 1163 while the compact row
 * fits 839.5px, hiding a workbench that works.
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

/** The width the workbench is promised from; MobileGuard's stated minimum. */
const MEASURED_FLOOR = 900
/** The compact row's worst-case fit width, measured: 839.5px, rounded up. */
const MEASURED_NEED = 840
/** Where the tabs take the row inline again; exact, per-pixel sweep. */
const COMPACT_FLOOR = 1163
/** The width where every control fits inline, also measured. */
const INLINE_FLOOR = 1440

test('the inline actions and the overflow menu are never both visible', () => {
  // One decision expressed in two class lists, because Tailwind cannot say "the other one".
  // A mismatch shows up as every control appearing twice, which reads as a duplicate-control
  // bug rather than an overflow.
  //
  // Asserted PER BUTTON, by locating each button's own className, and not by counting
  // occurrences of the hide class in the file. The counting version was fooled by this very
  // test's sibling: the Library button carries a comment explaining why it uses the
  // max-width variant and not `hidden sm:flex`, and that comment contains the string. So
  // the count stayed above the threshold after a real button had been unhidden, and a
  // mutation that put the row back to 1416px passed. A source scan that cannot tell code
  // from commentary about the code is not measuring what it claims to.
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

  // The menu wrapper, found by the ref that owns it rather than by the first hide class in
  // the file: the view-menu wrapper now also carries a min-width hide, and matching that
  // one would compare the wrong pair.
  const menuTag = /ref=\{actionsRef\}[^>]*className="([^"]*)"/.exec(header)
  assert.ok(menuTag, 'the overflow menu wrapper is gone from the header')
  const menuHide = /min-\[(\d+)px\]:hidden/.exec(menuTag[1])
  assert.ok(
    menuHide,
    'the overflow menu wrapper has no min-width hide, so it would show at 1440px too',
  )

  // Same number on both sides, because max-[N] compiles to strictly-below-N in this build
  // (measured from the generated stylesheet, 2026-10-06). max-1439 against min-1440 is the
  // classic complementary pair and it leaves width 1439 showing both presentations --
  // measured live at vw1439: inline actions beside their own menu, docScroll 1447.
  assert.equal(
    Number(menuHide[1]),
    Number([...hideWidths][0]),
    `the menu hides from ${menuHide[1]}px while the inline buttons hide below ` +
      `${[...hideWidths][0]}px. Under this build's strictly-below max semantics the two ` +
      `numbers must be equal or the width between them shows both or neither.`,
  )
  assert.equal(
    Number(menuHide[1]),
    INLINE_FLOOR,
    `the actions pair hides at ${menuHide[1]}px but the measured inline floor is ` +
      `${INLINE_FLOOR}px`,
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

test('the view menu carries the same disclosure contract as the actions menu', () => {
  // The compact band replaced three always-visible tabs with this menu, so it inherits the
  // whole contract rather than a reduced version. Two menus that behave differently when a
  // keyboard user is in the header would be a worse defect than either menu.
  for (const [what, needle] of [
    ['the trigger declares aria-haspopup', 'aria-haspopup="menu"'],
    ['the trigger reports its state', 'aria-expanded={viewsOpen}'],
    ['the trigger names the current view', 'Workspace view, currently'],
    ['the panel is a menu', 'role="menu"'],
    ['the panel is labelled', 'aria-label="Workspace view"'],
    ['each entry is a menu item radio', 'role="menuitemradio"'],
    ['each entry marks the live view', 'aria-checked={active}'],
    ['Escape closes it', 'viewsButtonRef.current?.focus()'],
    ['a click outside closes it', 'viewsRef.current?.contains(e.target as Node)'],
    ['selecting closes before switching', 'closeViews()'],
  ] as [string, string][]) {
    assert.ok(header.includes(needle), `${what} is missing: ${needle} not found in Header.tsx`)
  }

  // Both presentations render from the same MODES source and drive the same onModeChange,
  // so the menu cannot drift into offering a different set of views than the tabs did.
  assert.equal(
    (header.match(/MODES\.map/g) ?? []).length,
    2,
    'the tabs and the view menu must both map MODES, or the two presentations offer ' +
      'different views at different widths',
  )
  assert.equal(
    (header.match(/onModeChange\(m\.id\)/g) ?? []).length,
    2,
    'the tabs and the view menu must both call onModeChange with the mode id, or selecting ' +
      'a view from the menu leaves the rest of the page showing the old one',
  )
})

test('the view tabs exist as exactly one presentation at any width', () => {
  // One decision in two class lists, like the actions pair, and the same-number rule applies
  // because max-[N] compiles to strictly-below-N in this build. Stated as max-1162 against
  // min-1163 it left exactly 1162px rendering both the tabs and the trigger -- measured
  // 2026-10-06 at vw1162: four header children where three belong, docScroll 1276.
  const tabTag = /<div[^>]*role="tablist"[^>]*className="([^"]*)"/.exec(header)
  assert.ok(tabTag, 'the workspace tablist is gone from the header')
  const tabHide = /max-\[(\d+)px\]:hidden/.exec(tabTag[1])
  assert.ok(
    tabHide,
    'the tablist has no max-width hide, so it stays inline where the row cannot fit it',
  )

  const viewsTag = /ref=\{viewsRef\}[^>]*className="([^"]*)"/.exec(header)
  assert.ok(viewsTag, 'the view menu wrapper is gone from the header')
  const viewsHide = /min-\[(\d+)px\]:hidden/.exec(viewsTag[1])
  assert.ok(viewsHide, 'the view menu wrapper has no min-width hide, so it would show at 1163px too')

  assert.equal(
    Number(tabHide[1]),
    Number(viewsHide[1]),
    `the tablist hides below ${tabHide[1]}px while the menu hides from ${viewsHide[1]}px. ` +
      `Under this build's strictly-below max semantics the two numbers must be equal, or ` +
      `the width between them shows both presentations at once.`,
  )
  assert.equal(
    Number(tabHide[1]),
    COMPACT_FLOOR,
    `the view pair switches at ${tabHide[1]}px but the measured compact band ends at ` +
      `${COMPACT_FLOOR}px`,
  )
})

test('every QA state keeps its word off the narrow band and its status in the label', () => {
  // Below 1163px the badge is an icon in all four states, so its width stops depending on
  // which model is open. `not_run` is not a loading blip: it is what a model with no QA
  // checks renders for as long as the page is open, and as text it measured 83.5px against
  // the 34px an icon costs -- which alone would push the row's worst case past 889px. The
  // aria-label, unchanged at every width, is what keeps the status for assistive tech.
  const start = header.indexOf('QA Status')
  assert.ok(start > 0, 'the QA badge is gone from the header')
  const qa = header.slice(start, header.indexOf('</button>', start))

  assert.equal(
    (qa.match(/max-\[1163px\]:hidden/g) ?? []).length,
    4,
    'all four QA states must hide their word together at the compact boundary; one state ' +
      'keeping its text makes the row width depend on model state',
  )
  assert.ok(
    qa.includes('<Clock'),
    'the pending state renders no icon, so below 1163px its badge has nothing to show',
  )
  assert.ok(
    qa.includes('QA report:'),
    'the aria-label template is gone, so screen readers lose the QA status at every width',
  )
  assert.ok(
    qa.includes('checks have not run yet'),
    'the pending aria-label is gone; the icon alone does not say what it means',
  )
  assert.ok(
    qa.includes('title="Open the automated model audit report"'),
    'the tooltip is gone, so the icon is unexplained for pointer users',
  )
  for (const word of ['Model valid', 'skipped', 'failed', 'QA pending']) {
    assert.ok(qa.includes(word), `the ${word} status text is gone from the QA badge`)
  }
})

test('the guard admits no width the header cannot render, and hides little that works', () => {
  // The durable check. The original defect was a guard promising 900px against a layout
  // needing 1416px, and nothing anywhere compared the two numbers.
  const m = /min-\[(\d+)px\]:hidden/.exec(guard)
  assert.ok(m, 'MobileGuard no longer states a minimum width, so it admits every viewport')
  const stated = Number(m[1])

  assert.equal(
    stated,
    MEASURED_FLOOR,
    `MobileGuard admits ${stated}px while the workbench is promised from ${MEASURED_FLOOR}px`,
  )

  // Admits no width the compact row cannot render. The binding requirement is the sub-1024
  // one (839.5px, rounded up to MEASURED_NEED); from 1024 the search field grows to 224px
  // and the row needs 855.5px, which fits from 1024 by construction.
  assert.ok(
    stated >= MEASURED_NEED,
    `the guard admits ${stated}px but the compact row was measured to need ${MEASURED_NEED}px ` +
      `in its worst composition, so from ${stated}px up the controls run off the edge`,
  )

  // And does not hide far more than the row needs. 900 - 840 = 60, inside this bound. The
  // guard that stood at 1163 was 263px above the compact row's requirement, which is the
  // original defect inverted: not controls off the edge, but a working workbench replaced
  // by a minimum-width page across every 900 to 1162px laptop and tablet.
  assert.ok(
    stated - MEASURED_NEED <= 100,
    `the guard hides from ${stated}px up while the row needs only ${MEASURED_NEED}px; a ` +
      `threshold this far above the measurement gives back no band to visitors`,
  )

  assert.ok(
    MEASURED_FLOOR < COMPACT_FLOOR,
    'the guard must stay below the width where the inline row takes over, or the compact ' +
      'band it exists for is never reachable',
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

test('the header heading and the guard expose exactly one h1 per viewport', () => {
  // The guard carries its own h1 for the viewport it owns. Matching the two breakpoints is
  // what keeps exactly one of them exposed: with the guard at 1163 and the header h1 at
  // 900, the accessibility tree held two h1s across the whole 900 to 1162 band (measured
  // 2026-10-06), and with mismatched numbers there is also a band with none at all.
  const h1Tag = /<h1[^>]*className="([^"]*)"/.exec(header)
  assert.ok(h1Tag, 'the workbench header no longer has its h1')
  const h1Break = /min-\[(\d+)px\]:flex/.exec(h1Tag[1])
  assert.ok(
    h1Break,
    'the header h1 is not gated on a min-width, so it renders on phones where the guard owns the page',
  )
  const guardBreak = /min-\[(\d+)px\]:hidden/.exec(guard)
  assert.ok(guardBreak, 'the guard has no min-width gate')
  assert.equal(
    Number(h1Break[1]),
    Number(guardBreak[1]),
    `the header h1 appears at ${h1Break[1]}px while the guard hides at ${guardBreak[1]}px: ` +
      `between those widths both headings sit in the accessibility tree, outside them neither does`,
  )
})

test('the measured numbers are recorded where the layout is, not only in the guard', () => {
  // The numbers came from browser sweeps. Comments that cite them next to the class lists
  // are what lets the next person check them rather than re-derive them from a guess.
  for (const n of [MEASURED_FLOOR, COMPACT_FLOOR, INLINE_FLOOR]) {
    assert.ok(
      header.includes(String(n)),
      `Header.tsx does not mention ${n}px, so the number in MobileGuard has no visible derivation`,
    )
  }
  for (const n of ['839.5', '855.5']) {
    assert.ok(
      header.includes(n),
      `Header.tsx does not cite the measured worst-case requirement of ${n}px, so the floor ` +
        `has no visible derivation`,
    )
  }
})
