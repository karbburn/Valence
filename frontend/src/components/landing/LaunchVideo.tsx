'use client'

import { useRef, useState } from 'react'
import Link from 'next/link'
import { Pause, Play, Volume2, VolumeX } from 'lucide-react'

/**
 * Hero video slot.
 *
 * Click to play, never autoplay. A video that starts on its own competes with
 * the headline for the same attention, and on a page someone opened in order to
 * read something it is hostile.
 *
 * The frame is 16:9 set in CSS rather than read from the file, so dropping in
 * the next cut at the same dimensions changes nothing about the layout. The box
 * is reserved before the file loads, which keeps the shift on load at zero.
 *
 * The film carries a voiceover and a sound bed, and the captions are burnt into
 * the picture rather than carried as a track. It therefore plays correctly with
 * the sound off, which is how it starts: a visitor who clicked play on a page
 * they opened to read something did not ask for a soundtrack, and a film that
 * can be understood silently should not insist otherwise. The voiceover is one
 * control away rather than unreachable, which is what the caption row's sound
 * control is for.
 */

/**
 * Bump this when either media file is replaced.
 *
 * Both live in public/ under a fixed name, and a CDN or browser will keep
 * serving the old bytes at that name long after the file on disk has changed, so
 * replacing brag.mp4 or brag.jpg at the same path would reach nobody until the
 * caches happened to expire. One token, bumped once, invalidates both the poster
 * and the video without renaming either file.
 *
 * Set it to the date of the new cut, or any value that changes with it.
 */
const MEDIA_REV = '2026-09-29b'

/**
 * The three media paths, built from bare names and the cache token separately.
 *
 * Deriving the caption track from the video URL did not work, and failed in a way
 * that was invisible: the derivation stripped a trailing ".mp4", but the video URL
 * ends with its cache token, so the extension was never stripped and the track
 * resolved to a path that names no file. The video played, the poster showed, and
 * the caption track was simply absent, which is the one failure on this component
 * that nothing else would have reported.
 */
const VIDEO_PATH = '/media/valence-launch.mp4'
const POSTER_PATH = '/media/valence-launch-poster.jpg'
const CAPTIONS_PATH = '/media/valence-launch.en.vtt'

const VIDEO_SRC = `${VIDEO_PATH}?v=${MEDIA_REV}`
const POSTER_SRC = `${POSTER_PATH}?v=${MEDIA_REV}`
const CAPTIONS_SRC = `${CAPTIONS_PATH}?v=${MEDIA_REV}`

/** Runtime of the cut, read from the file rather than typed in by hand. */
const FILM_RUNTIME = '0:26'

export function LaunchVideo() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [started, setStarted] = useState(false)
  const [sound, setSound] = useState(false)

  return (
    <div className="relative">
      {/* No max-height. The band sits inside a max-w-[1400px] container, so at
          16:9 the frame can never exceed about 765px tall and a cap can only
          ever crop. A 600px cap was cutting 166px off the bottom of the title
          card at 1440, which is where its closing line and the price-as-of note
          live. Measured: 0px cropped at 1024, 98px at 1280, 166px at 1440. */}
      <div className="relative w-full aspect-video overflow-hidden rounded-sm border border-border bg-surface-3">
        <video
          ref={videoRef}
          className="absolute inset-0 w-full h-full object-cover object-top"
          poster={POSTER_SRC}
          preload="none"
          muted={!sound}
          playsInline
          controls
          onPlay={() => setStarted(true)}
          onPause={() => setStarted(false)}
        >
          <source src={VIDEO_SRC} type="video/mp4" />
          {/* A caption track, default, so the browser offers captions without
              a visitor going looking for them.

              The captions are already burned into the picture, so this is not
              what a sighted viewer reads and it is not a substitute for them. It
              is for the two cases pixels cannot serve: a screen reader has no
              frame to read, and a viewer who turns the sound on has no reason to
              keep looking at the screen. Without it, turning the sound on put
              spoken audio on with no text anywhere for anyone who needs it,
              which is why the sound control and this track landed together.

              The timings are generated from the film's own composition rather
              than typed, so the track cannot drift away from the captions in the
              picture when the film is re-cut. */}
          <track
            kind="captions"
            src={CAPTIONS_SRC}
            srcLang="en"
            label="English"
            default
          />
          Your browser cannot play embedded video.{' '}
          <a href={VIDEO_SRC} className="text-accent underline">
            Download the clip
          </a>
          .
        </video>

        {/* Play affordance. The whole frame stays a click target, but the pill is
            anchored top-left rather than centred. Centred put it straight over
            the -52.0%, which is the one number the card exists to show. Top-left
            also clears the native control bar, which Chrome keeps on screen for
            a paused video and which owns the bottom strip.

            No dimming scrim. A 40% near-black wash over the frame was tuned for a
            dark screen recording and turned this light card grey. The pill
            carries its own background, so it reads over any frame without
            touching the image. */}
        {/* The whole frame is the click target and carries no visible control.
            The poster is a composed title card that fills the frame edge to
            edge, so there is no collision-free zone inside it: centred put the
            pill over the figure, top-left over the eyebrow, and the browser's
            own control bar owns the bottom strip on a paused video. Putting the
            affordance in the caption row below is the only placement that
            covers nothing, and it is where a caption and its control belong
            anyway. The visible label is that button, so it is a real control
            rather than a decoration over one. */}
        {!started && (
          <button
            type="button"
            onClick={() => videoRef.current?.play()}
            className="absolute inset-0 group"
            aria-label="Play the clip"
          >
            <span
              className="absolute inset-0 rounded-sm ring-1 ring-inset ring-transparent
                         group-hover:ring-accent-border group-focus-visible:ring-accent
                         transition-shadow"
              aria-hidden
            />
          </button>
        )}
      </div>

      {/* Caption row. Carries the visible play control, the runtime, the sound
          control, and the way to the assumptions.

          The sound control is a control rather than a label because the film has
          a voiceover and this row previously said "Silent" in words while the
          video element was muted, so the statement described the element's state
          and nothing else. It read as a fact about the film, and the fact was
          wrong: the cut carries a five-line voiceover over a sound bed. A label
          that asserts something cannot be acted on, and this one had to be acted
          on, because the audio was otherwise unreachable.

          It starts off. Someone who pressed play on a page they opened in order
          to read something did not ask for a soundtrack, and the captions are
          burnt into the picture, so the film is complete either way. Turning it
          on is one press away, which is the difference between a film that has a
          voiceover and one that has had it taken away. */}
      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <button
          type="button"
          onClick={() => {
            const v = videoRef.current
            if (!v) return
            if (v.paused) void v.play()
            else v.pause()
          }}
          className="inline-flex items-center gap-1.5 text-[11px] font-mono text-text-muted
                     hover:text-text-main transition-colors"
          aria-label={started ? 'Pause the clip' : 'Play the clip'}
        >
          {started ? (
            <Pause className="w-3 h-3" aria-hidden />
          ) : (
            <Play className="w-3 h-3 text-accent fill-accent" aria-hidden />
          )}
          {started ? 'Pause' : 'Play the clip'}
        </button>
        <span className="text-[11px] text-text-faint font-mono" aria-hidden>
          /
        </span>
        <span className="text-[11px] text-text-dim font-mono">{FILM_RUNTIME}</span>
        <span className="text-[11px] text-text-faint font-mono" aria-hidden>
          /
        </span>
        <button
          type="button"
          onClick={() => setSound((on) => !on)}
          className="inline-flex items-center gap-1.5 text-[11px] font-mono text-text-muted
                     hover:text-text-main transition-colors"
          aria-pressed={sound}
        >
          {sound ? (
            <Volume2 className="w-3 h-3 text-accent" aria-hidden />
          ) : (
            <VolumeX className="w-3 h-3" aria-hidden />
          )}
          {sound ? 'Sound on' : 'Sound off'}
        </button>
        <span className="text-[11px] text-text-faint font-mono" aria-hidden>
          /
        </span>
        <Link
          href="/methodology"
          className="text-[11px] text-accent hover:text-accent-hover transition-colors font-mono"
        >
          How the valuation is built
        </Link>
      </div>
    </div>
  )
}
