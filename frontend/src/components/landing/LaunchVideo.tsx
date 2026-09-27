'use client'

import { useRef, useState } from 'react'
import Link from 'next/link'
import { Pause, Play } from 'lucide-react'

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

        {/* Play affordance. The whole frame stays a click target, but the pill is
            anchored top-left rather than centred. Centred put it straight over
            the 12.45%, which is the one number the card exists to show. Top-left
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

      {/* Caption row. Carries the visible play control, the accessibility
          statement, and the way to the assumptions. Not "recorded from the live
          workbench": the poster is a composed card, and a caption that
          misdescribes the thing above it is the same class of error as a
          caption that misdescribes a number. This one also survives a re-cut,
          because it points at the assumptions rather than the production. */}
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
        <span className="text-[11px] text-text-dim font-mono">Silent</span>
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
