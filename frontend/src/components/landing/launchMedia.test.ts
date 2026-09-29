/**
 * The landing page has to actually reference the launch film, and reference it
 * correctly.
 *
 * Three things about this component fail silently, and all three did.
 *
 * The caption track's src was derived from the video URL by stripping a trailing
 * ".mp4". The video URL ends with its cache token, so the extension was never
 * stripped and the track resolved to a path naming no file. The video played, the
 * poster appeared, and only the track was missing, which nothing on the page
 * reports and no type check can see.
 *
 * A replaced film fails the same way. The file is copied to the same path, the
 * component is unchanged, the page renders, and a browser or CDN keeps serving
 * the bytes that were there before, so the change reaches nobody until the caches
 * expire on their own.
 *
 * A media file the component names but that is absent from public/ is a 404 on
 * every load, and the page looks finished while it is not.
 *
 * These are checked against the source and the filesystem rather than a running
 * server, because the unit tests run before the production build and starting a
 * server to assert a string would be a slower way to read a file.
 */

import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const COMPONENT = path.join(HERE, 'LaunchVideo.tsx')
const MEDIA = path.join(HERE, '..', '..', '..', 'public', 'media')

const source = readFileSync(COMPONENT, 'utf-8')

/** Every /media/... path the component names. */
function mediaPaths(): string[] {
  return [...source.matchAll(/['"](\/media\/[^'"?]+)/g)].map((m) => m[1])
}

/**
 * The filesystem path a URL constant resolves to, with any interpolation filled
 * in. A URL is built here from a bare path plus a cache token, so the extension
 * is never in the same string as the reference to it.
 */
function resolveUrlPath(name: string, depth = 0): string {
  assert.ok(depth < 5, 'the URL constants refer to each other in a cycle')
  // A bare path is a single-quoted literal; a URL with a cache token on it is a
  // template. Both forms are in the file, so both are read.
  const single = source.match(new RegExp(`const ${name} = '([^']+)'`))?.[1]
  const templated = source.match(new RegExp(`const ${name} = \`([^\`]+)\``))?.[1]
  const literal = single ?? templated
  assert.ok(literal, `could not resolve the ${name} constant`)

  const withoutQuery = literal.split('?')[0]
  const interpolated = withoutQuery.match(/\$\{([A-Z_]+)\}$/)
  if (!interpolated) return withoutQuery
  return resolveUrlPath(interpolated[1], depth + 1)
}

test('every media file the component references exists', () => {
  const referenced = new Set(mediaPaths())
  assert.ok(referenced.size >= 3, `expected video, poster and captions, got ${referenced.size}`)
  for (const rel of referenced) {
    const onDisk = path.join(MEDIA, path.basename(rel))
    assert.ok(
      existsSync(onDisk),
      `${rel} is referenced by LaunchVideo but is not in public/media`,
    )
  }
})

test('the caption track is not derived from the video URL', () => {
  // The bug: `${VIDEO_SRC.replace(/\.mp4$/, '')}.en.vtt`. VIDEO_SRC ends with its
  // cache token, so the anchored regex never matched and the src became
  // ".../valence-launch.mp4?v=TOKEN.en.vtt?v=TOKEN", which names no file.
  assert.ok(
    !/VIDEO_SRC\.replace/.test(source),
    'the caption src is derived from the video URL, which cannot work with a cache token on it',
  )

  const track = source.match(/<track[\s\S]*?\/>/)?.[0]
  assert.ok(track, 'the video has no <track> element')
  assert.match(track, /kind="captions"/)
  assert.match(track, /src=\{CAPTIONS_SRC\}/)
})

test('the caption track src names a vtt file, not the video', () => {
  const track = source.match(/<track[\s\S]*?\/>/)?.[0] ?? ''
  const name = track.match(/src=\{([A-Z_]+)\}/)?.[1]
  assert.ok(name, 'the track src is not a named constant')

  // Resolve the URL the way the browser will, following the indirection. The src
  // is a URL constant built from a bare path plus the cache token, so neither
  // string on its own shows the extension, and asserting on a literal would
  // pass for a URL that serves the wrong file.
  const barePath = resolveUrlPath(name)
  assert.match(barePath, /\.vtt$/, `${name} must name a .vtt file, got ${barePath}`)
  assert.ok(!barePath.includes('.mp4'), `${name} points at the video`)
})

test('every media URL carries the cache token', () => {
  // Without a token a replaced file is served from cache at the same path, which
  // is the whole reason MEDIA_REV exists.
  const rev = source.match(/const MEDIA_REV = '([^']+)'/)?.[1]
  assert.ok(rev, 'MEDIA_REV is not declared')

  const urls = [...source.matchAll(/`(\/media\/[^`]+)`/g)].map((m) => m[1])
  const withToken = urls.filter((u) => u.includes('${MEDIA_REV}'))
  assert.equal(
    withToken.length,
    urls.length,
    `not every media URL is tokenised: ${urls.filter((u) => !u.includes('${MEDIA_REV}')).join(', ')}`,
  )
})

test('the video carries a caption track and a poster', () => {
  assert.match(source, /poster=\{POSTER_SRC\}/)
  assert.match(source, /<track[\s\S]*?kind="captions"/)
  assert.match(source, /preload="none"/, 'the film must not be fetched before it is asked for')
})

test('the sound control is wired to the element, not only labelled', () => {
  // A label that says the film is silent while the element is muted describes the
  // element, not the film, and cannot be acted on.
  assert.match(source, /muted=\{!sound\}/, 'the video mute is not driven by the sound state')
  assert.match(source, /aria-pressed=\{sound\}/, 'the sound control reports no state')
  assert.ok(
    !/>Silent</.test(source),
    'the caption row still labels the film silent, which it is not',
  )
})
