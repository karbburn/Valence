'use client'

import { useRef, useState } from 'react'
import Link from 'next/link'
import { Play } from 'lucide-react'

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
const MEDIA_REV = '2026-09-27a'

const VIDEO_SRC = `/media/valence-launch.mp4?v=${MEDIA_REV}`
const POSTER_SRC = `/media/valence-launch-poster.jpg?v=${MEDIA_REV}`

export function LaunchVideo() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [started, setStarted] = useState(false)

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
          muted
          playsInline
          controls
          onPlay={() => setStarted(true)}
          onPause={() => setStarted(false)}
        >
          <source src={VIDEO_SRC} type="video/mp4" />
          Your browser cannot play embedded video.{' '}
          <a href={VIDEO_SRC} className="text-accent underline">
            Download the clip
          </a>
          .
        </video>

        {/* Play affordance. The whole frame stays a click target, but there is no
            dimming scrim behind it. A 40% near-black wash over the frame was
            tuned for a dark screen recording and turned a light title card into
            a grey one. The pill carries its own background, so it stays legible
            over any frame without touching the image. */}
        {!started && (
          <button
            type="button"
            onClick={() => videoRef.current?.play()}
            className="absolute inset-0 group flex items-center justify-center"
            aria-label="Play the clip"
          >
            <span className="flex items-center gap-3 h-12 pl-4 pr-6 rounded-sm bg-canvas/90 border border-border group-hover:border-accent-border group-hover:bg-surface-2 transition-colors">
              <Play className="w-5 h-5 text-accent fill-accent" aria-hidden />
              <span className="text-[13px] font-semibold text-text-main">Play the clip</span>
            </span>
          </button>
        )}
      </div>

      {/* Not "recorded from the live workbench". The poster is a composed title
          card, and a caption that misdescribes the thing above it is the same
          class of error as a caption that misdescribes a number. This one also
          survives a re-cut, because it points at the assumptions rather than
          describing the production. */}
      <p className="mt-2.5 text-[11px] text-text-dim font-mono">
        Silent.{' '}
        <Link href="/methodology" className="text-accent hover:text-accent-hover transition-colors">
          How the valuation is built
        </Link>
      </p>
    </div>
  )
}
