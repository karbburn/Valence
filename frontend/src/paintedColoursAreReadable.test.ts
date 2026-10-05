/**
 * Every colour pair the source paints has to be readable, and the arithmetic is checked
 * rather than the appearance.
 *
 * The defect this exists for: the methodology modal's Close button was
 * `bg-accent hover:bg-accent-hover text-white text-[12px]`, and white on `--c-accent` measures
 * 2.77:1 against the 4.5:1 a 12px label needs. It had been sitting in a review as "buttons at
 * 2.77:1" with no site named, because a contrast ratio is cheap to measure and nobody had
 * measured which control it was.
 *
 * Auditing that one button instead of the class found three more: the Excel export's hover
 * fill at 3.60:1, and the QA and Reset badges' hover states at 3.74:1 and 3.89:1.
 *
 * **Three earlier versions of this check were wrong, and every one of them failed in the
 * direction that matters.**
 *
 *   * One reported `text-negative on bg-negative` at 1.00:1 -- invisible text, which nothing
 *     ships -- because it matched `bg-negative` out of `hover:bg-negative/20`, a 20% wash,
 *     and paired a solid fill with the steady-state text.
 *   * Having done that, the same version DROPPED the real offender, because `text-white` is a
 *     Tailwind built-in rather than a palette token and could not be resolved.
 *   * The next version resolved only `--c-*` and so could not see `text-main`, `text-muted`
 *     or `text-dim`, which reach their colours through the `@theme` alias block. Those are
 *     the three most-used text colours on the site -- 23, 17 and 17 files -- so that gate
 *     would have measured accent fills and status washes while ignoring most of the text on
 *     the site, and reported itself as thorough.
 *
 * A check that reports pairs which are never painted, or misses the common ones, is worse
 * than no check: it teaches the reader to discount the output. So this resolves colours the
 * way the browser does -- `--c-*`, then the `@theme` aliases onto them, then Tailwind's own
 * defaults, then an arbitrary literal -- and it handles the three constructs that produced
 * the errors above:
 *
 *   1. STATE. `hover:`, `focus:` and friends are separated from the steady state, and a
 *      state's fill is composited OVER the fill beneath it, because a hover wash changes the
 *      background and not the text.
 *   2. ALPHA. `bg-negative/20` is a wash, not a colour. Measured as a wash.
 *   3. BRANCHES. A className built from a ternary holds mutually exclusive states. Each branch
 *      is measured against the shared base and never against another branch, which is how
 *      `text-positive on bg-negative` came to be "measured" from two arms of one switch.
 *
 * Compositing runs over three candidate surfaces and the WORST ratio is reported, because
 * which surface a component sits on is a layout question and assuming the flattering one
 * would be the same error in a new place.
 *
 * WCAG 2.2 SC 1.4.3 treats text as large at 24px, or 18.66px bold, and needs 3:1 there.
 * Tailwind's `text-xl` is 20px and not large, so the bar is 4.5:1 throughout this system.
 */

import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import path from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const SRC = path.join(HERE, 'components')
const APP = path.join(HERE, 'app')
const CSS_PATH = path.join(APP, 'globals.css')

const WCAG_NORMAL = 4.5
const WCAG_LARGE = 3.0
const LARGE_FROM_PX = 24.0

/**
 * Tailwind's default shades that this design system uses, so a name outside the project's
 * own palette is still MEASURED rather than skipped. A skipped pair reads as a passing pair.
 */
const TAILWIND: Record<string, string> = {
  white: '#ffffff',
  black: '#000000',
  'blue-300': '#93c5fd',
  'blue-950': '#172554',
  'orange-300': '#fdba74',
  'orange-950': '#431407',
}

/** `bg-`/`text-` names that are not colours, so their absence is not a finding. */
const NOT_A_COLOUR = new Set([
  // font families
  'mono', 'sans',
  // paints nothing, so the surface beneath is what matters and that IS measured
  'transparent', 'inherit', 'current',
  // type scale, position, overflow, transform
  'xs', 'sm', 'base', 'lg', 'xl', '2xl', '3xl', '4xl',
  'left', 'right', 'center', 'justify', 'overflow', 'ellipsis', 'nowrap', 'wrap',
  'clip', 'transform', 'balance', 'pretty',
])

const TEXT_SIZE_PX: Record<string, number> = {
  'text-xs': 12,
  'text-sm': 14,
  'text-base': 16,
  'text-lg': 18,
  'text-xl': 20,
  'text-2xl': 24,
  'text-3xl': 30,
  'text-4xl': 36,
}
const ARBITRARY_SIZE = /^text-\[(\d+(?:\.\d+)?)px\]$/
const STATE_PREFIXES = ['hover', 'focus', 'focus-visible', 'active', 'disabled', 'group-hover']

type Colour = [number, number, number, number]

function linear(c: number): number {
  const v = c / 255
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
}

function parseColour(spec: string): Colour | null {
  const s = spec.trim()
  const hex = s.startsWith('#') ? s : TAILWIND[s]
  if (hex) {
    const h = hex.slice(1)
    const full = h.length === 3 ? [...h].map((c) => c + c).join('') : h
    if (full.length !== 6) return null
    return [
      parseInt(full.slice(0, 2), 16),
      parseInt(full.slice(2, 4), 16),
      parseInt(full.slice(4, 6), 16),
      1,
    ]
  }
  const m = /^rgba?\(([^)]+)\)$/.exec(s)
  if (!m) return null
  const parts = m[1].split(',').map((p) => p.trim())
  if (parts.length < 3) return null
  return [
    Math.round(Number(parts[0])),
    Math.round(Number(parts[1])),
    Math.round(Number(parts[2])),
    parts.length > 3 ? Number(parts[3]) : 1,
  ]
}

/** Composite an alpha colour over another. */
function over(fg: Colour, bg: Colour): Colour {
  const a = fg[3]
  return [
    fg[0] * a + bg[0] * (1 - a),
    fg[1] * a + bg[1] * (1 - a),
    fg[2] * a + bg[2] * (1 - a),
    1,
  ]
}

function luminance(c: Colour): number {
  return 0.2126 * linear(c[0]) + 0.7152 * linear(c[1]) + 0.0722 * linear(c[2])
}

function ratio(a: Colour, b: Colour): number {
  const x = luminance(a)
  const y = luminance(b)
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
}

const css = readFileSync(CSS_PATH, 'utf-8')

/** `--c-<name>` -> its literal value. */
const RAW: Record<string, string> = {}
for (const m of css.matchAll(/(--c-[a-z0-9-]+):\s*([^;]+);/g)) RAW[m[1]] = m[2].trim()

/**
 * `--color-<name>` -> the `--c-` name it aliases.
 *
 * Without this the gate is blind to `text-main`, `text-muted` and `text-dim`, which is how
 * the third version of this check came to report itself as thorough while measuring almost
 * none of the site's text. `@theme` is where Tailwind turns these into utilities, so it is
 * the same map the browser uses.
 */
const ALIAS: Record<string, string> = {}
for (const m of css.matchAll(/--color-([a-z0-9-]+):\s*var\(--c-([a-z0-9-]+)\)\s*;/g)) {
  ALIAS[m[1]] = m[2]
}

/** Token names this could not read at all, reported rather than skipped. */
const MALFORMED = new Set<string>()

/**
 * `negative` -> `--c-negative`; `text-main` -> `--c-text`; `[#0ea5e9]` -> that literal;
 * `negative/20` -> `--c-negative` at 20% alpha.
 */
function tokenColour(name: string): Colour | null {
  let alpha: number | null = null
  let base = name
  if (name.includes('/')) {
    const parts = name.split('/')
    base = parts[0]
    const pct = parts[parts.length - 1]
    if (!pct) {
      MALFORMED.add(name)
      return null
    }
    alpha = Number(pct.replace('%', '')) / 100
    if (!Number.isFinite(alpha)) {
      MALFORMED.add(name)
      return null
    }
  }

  // An arbitrary value, optionally wrapping a token: `[#0ea5e9]`, `[var(--c-text)]`.
  if (base.startsWith('[') && base.endsWith(']')) {
    const inner = base.slice(1, -1).trim()
    const viaVar = /^var\(--c-([a-z0-9-]+)\)$/.exec(inner)
    const literal = viaVar ? RAW[`--c-${viaVar[1]}`] : inner
    const c = literal ? parseColour(literal) : null
    if (!c) {
      MALFORMED.add(name)
      return null
    }
    return [c[0], c[1], c[2], alpha === null ? c[3] : alpha]
  }

  const spec = RAW[`--c-${base}`] ?? (ALIAS[base] ? RAW[`--c-${ALIAS[base]}`] : undefined) ?? TAILWIND[base]
  if (!spec) return null
  const c = parseColour(spec)
  if (!c) return null
  return [c[0], c[1], c[2], alpha === null ? c[3] : alpha]
}

function walk(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry)
    if (statSync(full).isDirectory()) out.push(...walk(full))
    else if (full.endsWith('.tsx') && !full.endsWith('.test.tsx')) out.push(full)
  }
  return out
}

/**
 * One entry per state the markup can paint.
 *
 * A template literal holding a ternary yields the shared base plus each arm's literal, so
 * mutually exclusive states are never measured against one another.
 */
function effectiveClassLists(source: string): { line: number; classes: string }[] {
  const out: { line: number; classes: string }[] = []
  const pattern = /className=(?:"([^"]*)"|\{`([^`]*)`\})/g
  let m: RegExpExecArray | null
  while ((m = pattern.exec(source)) !== null) {
    const line = source.slice(0, m.index).split('\n').length
    if (m[1] !== undefined) {
      out.push({ line, classes: m[1] })
      continue
    }
    const tpl = m[2] ?? ''
    const base = tpl.split('${', 1)[0]
    const arms = [...tpl.matchAll(/'([^']*)'|"([^"]*)"/g)]
      .map((a) => a[1] ?? a[2] ?? '')
      .filter((a) => /\b(?:bg|text)-/.test(a))
    if (arms.length === 0) out.push({ line, classes: base })
    for (const arm of arms) out.push({ line, classes: `${base} ${arm}` })
  }
  return out
}

function partition(classes: string) {
  const base: string[] = []
  const states: Record<string, string[]> = {}
  const sizes: number[] = []
  for (const cls of classes.split(/\s+/).filter(Boolean)) {
    if (cls in TEXT_SIZE_PX) {
      sizes.push(TEXT_SIZE_PX[cls])
      continue
    }
    const arbitrary = ARBITRARY_SIZE.exec(cls)
    if (arbitrary) {
      sizes.push(Number(arbitrary[1]))
      continue
    }
    const idx = cls.indexOf(':')
    if (idx > 0 && STATE_PREFIXES.includes(cls.slice(0, idx))) {
      const head = cls.slice(0, idx)
      ;(states[head] ??= []).push(cls.slice(idx + 1))
    } else {
      base.push(cls)
    }
  }
  return { base, states, size: sizes.length ? Math.min(...sizes) : null }
}

interface Finding {
  file: string
  line: number
  ratio: number
  text: string
  background: string
  /** The composited background, so a test can compare a colour by VALUE rather than by name. */
  fill: Colour
  sizePx: number
  need: number
}

const SURFACE_NAMES = ['surface', 'surface-2', 'canvas'] as const

function measure(): Finding[] {
  const surfaces = SURFACE_NAMES.map((n) => tokenColour(n)!)
  const findings: Finding[] = []

  for (const file of [...walk(SRC), ...walk(APP)]) {
    const rel = path.relative(path.join(HERE, '..'), file).replace(/\\/g, '/')
    const source = readFileSync(file, 'utf-8')
    for (const { line, classes } of effectiveClassLists(source)) {
      const { base, states, size } = partition(classes)
      if (size === null) continue
      const need = size >= LARGE_FROM_PX ? WCAG_LARGE : WCAG_NORMAL

      const bgs = base.filter((c) => c.startsWith('bg-')).map((c) => c.slice(3))
      const texts = base.filter((c) => c.startsWith('text-')).map((c) => c.slice(5))
      if (bgs.length === 0 || texts.length === 0) continue

      // The steady state, plus every state that changes the background.
      const variants: string[][] = [[]]
      for (const cls of Object.values(states)) {
        if (cls.some((c) => c.startsWith('bg-'))) variants.push(cls)
      }

      for (const variant of variants) {
        const vTexts = variant.filter((c) => c.startsWith('text-')).map((c) => c.slice(5))
        const vBgs = variant.filter((c) => c.startsWith('bg-')).map((c) => c.slice(3))
        for (const tx of vTexts.length ? vTexts : texts) {
          const fg = tokenColour(tx)
          if (!fg) continue
          for (const surface of surfaces) {
            // Steady-state fill: an opaque layer if there is one, else the alpha stack.
            let fill = surface
            for (const bg of bgs) {
              const c = tokenColour(bg)
              if (c) fill = c[3] >= 1 ? c : over(c, fill)
            }
            // The state's own fill goes on top of that, not instead.
            let label = bgs[bgs.length - 1] ?? '(surface)'
            if (vBgs.length) {
              const c = tokenColour(vBgs[vBgs.length - 1])
              if (c) {
                fill = over(c, fill)
                label = `${label} +${vBgs[vBgs.length - 1]}`
              }
            }
            const text = fg[3] < 1 ? over(fg, fill) : fg
            findings.push({
              file: rel,
              line,
              ratio: ratio(text, fill),
              text: tx,
              background: label,
              fill,
              sizePx: size,
              need,
            })
          }
        }
      }
    }
  }
  return findings
}

/**
 * Findings that are known, measured, and accepted.
 *
 * An empty list would be nicer to ship. It is not empty because these genuinely fail and
 * every fix trades away something real, so the exemption is written down with its
 * measurement rather than left to be rediscovered.
 *
 * Grouped by MECHANISM, because all four are one bug wearing four hats: a label painted in
 * the same hue as the wash behind it, so any wash of that hue moves the two toward each
 * other and the contrast falls. Every steady state passes (5.12:1, 5.49:1, 6.54:1 and
 * 7.31:1) and every hover state does not. On a dark surface hover conventionally lightens,
 * which is the opposite of what contrast needs here, and the arithmetic says there is no way
 * out: for the badges, no alpha at or above 12% clears 4.5:1, so a hover that is visibly
 * lighter cannot also be readable. The alternative -- dimming the fill on hover -- inverts
 * the idiom this design uses everywhere else.
 *
 * Two rules keep this from becoming a place where defects go to be comfortable:
 *
 *   * `ratio` is the WORST ratio for the pair across the three candidate surfaces, and a
 *     separate test asserts it still measures that. The first version keyed the exemption on
 *     the ratio, which meant one painted pair produced three findings at three ratios and
 *     only one of them was exempt.
 *   * `the exemption list has not grown` asserts the length, so a new instance fails the
 *     gate and has to be decided rather than absorbed.
 */
const ACCEPTED: {
  mechanism: string
  why: string
  pairs: { text: string; background: string; ratio: number }[]
}[] = [
  {
    mechanism: 'a label painted in the same hue as the wash behind it, dipping on hover',
    why:
      'hover-only, on 10-11px labels whose steady states pass. The label shares its hue with ' +
      'the background wash, so lightening the background on hover moves the two toward each ' +
      'other. A decision for the design to make deliberately, rather than for whoever ' +
      'happens to find the nearest colour.',
    pairs: [
      { text: '[#f59e0b]', background: '[#f59e0b]/10 +[#f59e0b]/20', ratio: 4.37 },
      { text: '[#0ea5e9]', background: '[#0ea5e9]/10 +[#0ea5e9]/20', ratio: 3.65 },
      { text: 'negative', background: 'negative-subtle +negative/20', ratio: 3.74 },
      { text: 'positive', background: 'positive-subtle +positive/20', ratio: 3.89 },
    ],
  },
]

/** Every exempted pair, flattened. */
const EXEMPT: { text: string; background: string; ratio: number }[] = ACCEPTED.flatMap(
  (a) => a.pairs,
)

/**
 * Matched on the pair alone, never on the ratio.
 *
 * Each painted pair is measured once per candidate surface, so one pair yields up to three
 * findings at three ratios. Keying on the ratio matched a single surface and left the other
 * two failing, which looked exactly like three unfixed defects.
 */
function isExempt(f: Finding): boolean {
  return EXEMPT.some((a) => a.text === f.text && a.background === f.background)
}

test('every colour the source asks for resolves to a value', () => {
  // A pair whose colour cannot be resolved is not a passing pair, it is an absent one. This
  // runs first so the findings below are collected rather than lost.
  measure()
  const unresolved: string[] = []
  for (const file of [...walk(SRC), ...walk(APP)]) {
    const source = readFileSync(file, 'utf-8')
    for (const m of source.matchAll(/\b(bg|text)-(\[[^\]\s]+\]|[a-z][a-z0-9-]*)/g)) {
      const name = m[2]
      // Tested against m[0], not m[2]: the capture holds `[11px]` without the `text-`
      // prefix, so matching the pattern against it never fires and every font size in the
      // codebase arrived here as an unresolvable colour.
      if (ARBITRARY_SIZE.test(m[0])) continue
      if (!name.startsWith('[') && NOT_A_COLOUR.has(name)) continue
      if (!tokenColour(name)) unresolved.push(`${path.basename(file)}: ${m[0]}`)
    }
  }
  assert.deepEqual(
    [...new Set(unresolved)],
    [],
    'these bg-/text- colours resolve to nothing, so every pair using them goes UNMEASURED, ' +
      'which in CI output is indistinguishable from passing',
  )
})

test('no colour token is malformed', () => {
  // Separate from the test above because the failure modes differ: one is "the name is
  // wrong", the other is "the name cannot be parsed at all".
  measure()
  assert.deepEqual(
    [...MALFORMED],
    [],
    'these tokens could not be parsed, so the pairs using them were not measured',
  )
})

test('no colour pair painted on a surface is below its WCAG threshold', () => {
  const findings = measure().filter((f) => f.ratio < f.need && !isExempt(f))

  const report = findings
    .map(
      (f) =>
        `  ${f.ratio.toFixed(2)}:1  text-${f.text} on ${f.background}` +
        `  (${f.sizePx}px, needs ${f.need}:1)  ${f.file}:${f.line}`,
    )
    .join('\n')

  assert.equal(
    report,
    '',
    `these painted colour pairs are below the WCAG threshold:\n${report}\n\n` +
      'A light label on a light fill is not fixable by lightening it. Compute the direction ' +
      'first: for a fill of luminance L a label must sit at 4.5*(L+0.05)-0.05, and if that ' +
      'exceeds 1.0 no such colour exists, so the label has to go DARKER.',
  )
})

test('the exemption list has not grown', () => {
  // The point of counting. An exemption with no cap is where defects go to be comfortable,
  // so a new instance of this mechanism fails here rather than being absorbed into a list
  // that already reads as a decision.
  const failing = measure().filter((f) => f.ratio < f.need)
  const unexempt = failing.filter((f) => !isExempt(f))
  assert.equal(
    unexempt.length,
    0,
    `${unexempt.length} pair(s) are below threshold and are not exempted. Adding one is a ` +
      'decision to make deliberately, with the measurement, not a consequence of editing a ' +
      'list:\n' +
      unexempt
        .map(
          (f) =>
            `  ${f.ratio.toFixed(2)}:1  text-${f.text} on ${f.background}` +
            `  (${f.sizePx}px)  ${f.file}:${f.line}`,
        )
        .join('\n'),
  )
  // Also that no exemption has become stale: each one must still be measuring what it was
  // written for. A drifted ratio means the situation changed and the decision no longer
  // applies, and inheriting it would be worse than having failed.
  for (const pair of EXEMPT) {
    const worst = Math.min(
      ...measure()
        .filter((f) => f.text === pair.text && f.background === pair.background)
        .map((f) => f.ratio),
    )
    assert.ok(
      Number.isFinite(worst),
      `the exemption for text-${pair.text} on ${pair.background} matches no painted pair ` +
        'any more. Either the colours moved or the markup was deleted; either way the ' +
        'exemption should go with it rather than sit here looking like coverage.',
    )
    assert.ok(
      Math.abs(worst - pair.ratio) < 0.05,
      `the exemption for text-${pair.text} on ${pair.background} records ${pair.ratio}:1 ` +
        `but it now measures ${worst.toFixed(2)}:1. The decision was made about a specific ` +
        'measurement, so a changed one has to be re-decided.',
    )
  }
})

/** Two colours are the same colour, allowing for float compositing. */
function sameColour(a: Colour, b: Colour): boolean {
  return a.every((v, i) => Math.abs(v - b[i]) < 1.5)
}

test('the recorded 2.77:1 defect stays fixed', () => {
  // Matched on the BACKGROUND'S VALUE, never on its name.
  //
  // The first version of this test filtered on `f.background.includes('accent')`, and a
  // mutation that put the accent back as the literal `[#0ea5e9]` sailed straight past it
  // while the general test caught it. So the specific test only ever saw the sites that
  // already used the token -- the sites that were already right -- and the four that were
  // broken were the ones it could not name. That is the same shape as the original defect:
  // fixing the token and calling it done, while the colour stayed hardcoded elsewhere.
  //
  // Comparing the composited fill against `--c-accent` and `--c-accent-hover` catches both
  // spellings, and catches a fourth literal nobody has written yet.
  const accent = tokenColour('accent')!
  const accentHover = tokenColour('accent-hover')!
  const offenders = measure().filter(
    (f) =>
      (sameColour(f.fill, accent) || sameColour(f.fill, accentHover)) &&
      (f.text === 'white' || f.text.startsWith('#') || f.text.startsWith('[')),
  )
  assert.deepEqual(
    offenders.map(
      (f) => `${f.text} on ${f.background} at ${f.ratio.toFixed(2)}:1  ${f.file}:${f.line}`,
    ),
    [],
    'a light label is back on an accent fill. That is arithmetically impossible to pass: ' +
      '--c-accent has luminance 0.329, so 4.5:1 against it needs a foreground above 1.0 and ' +
      'white is the brightest colour there is. Use text-on-accent with bg-accent.',
  )
})

test('an accent fill has a named ink, so text-white is not the obvious next move', () => {
  assert.ok(
    RAW['--c-on-accent'],
    '--c-on-accent is missing. Without it the only reachable value on an accent fill is a ' +
      'literal in a component, and the next person writes text-white.',
  )
  assert.ok(
    css.includes('--color-on-accent'),
    '--c-on-accent is defined but not mapped through @theme, so text-on-accent resolves to ' +
      'nothing',
  )
})

test('the alias map covers the text colours the site actually uses', () => {
  // The specific blind spot of the third version: `text-main`, `text-muted` and `text-dim`
  // are used in 23, 17 and 17 files and reach their colours only through @theme.
  for (const name of ['text-main', 'text-muted', 'text-dim']) {
    assert.ok(
      tokenColour(name),
      `text-${name} does not resolve, so the most-used text colour on the site goes ` +
        `unmeasured. @theme maps it via var(--c-...) and this reads that map.`,
    )
  }
})