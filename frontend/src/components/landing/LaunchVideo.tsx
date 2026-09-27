'use client'

import { useRef, useState } from 'react'
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
export function LaunchVideo() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [started, setStarted] = useState(false)

  return (
    <div className="relative">
      <div className="relative w-full aspect-video max-h-[600px] overflow-hidden rounded-sm border border-border bg-surface-3">
        <video
          ref={videoRef}
          className="absolute inset-0 w-full h-full object-cover object-top"
          poster="/media/valence-launch-poster.png"
          preload="none"
          muted
          playsInline
          controls
          onPlay={() => setStarted(true)}
          onPause={() => setStarted(false)}
        >
          <source src="/media/valence-launch.mp4" type="video/mp4" />
          Your browser cannot play embedded video.{' '}
          <a href="/media/valence-launch.mp4" className="text-accent underline">
            Download the clip
          </a>
          .
        </video>

        {/* Play affordance. Hidden once playing, so it never sits over the
            native controls or the frame itself. */}
        {!started && (
          <button
            type="button"
            onClick={() => videoRef.current?.play()}
            className="absolute inset-0 group flex items-center justify-center bg-canvas/40 hover:bg-canvas/25 transition-colors"
            aria-label="Play the clip"
          >
            <span className="flex items-center gap-3 h-12 pl-4 pr-6 rounded-sm bg-canvas/85 border border-border group-hover:border-accent-border group-hover:bg-surface-2 transition-colors">
              <Play className="w-5 h-5 text-accent fill-accent" aria-hidden />
              <span className="text-[13px] font-semibold text-text-main">Play the clip</span>
            </span>
          </button>
        )}
      </div>

      <p className="mt-2.5 text-[11px] text-text-dim font-mono">
        Recorded from the live workbench. Silent.
      </p>
    </div>
  )
}
