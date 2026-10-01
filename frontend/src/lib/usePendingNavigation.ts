'use client'

import { useRouter } from 'next/navigation'
import { useCallback, useState, useTransition } from 'react'

/**
 * Navigation that acknowledges the click before the page arrives.
 *
 * The problem this exists for: `router.push()` is fire-and-forget. Between the
 * click and the first paint of the destination there is no visible change at all,
 * and on a valuation page that gap is five seconds or more, because the destination
 * compiles the model before it renders anything. A visitor who clicks a ticker and
 * sees the page simply not change has no way to tell a working navigation from a
 * dropped click. They click again. Some of them click three or four times, and each
 * extra click is another model build competing for the same throttle.
 *
 * The fix is not a spinner. It is acknowledgement: the thing they touched shows
 * that it has been touched, immediately, and stays honest about how long the wait
 * is. `startTransition` is what makes it truthful -- the transition is pending for
 * exactly as long as the navigation and the render it is waiting on, rather than
 * for a guessed duration.
 *
 * `pendingTo` is the key of whatever was clicked, so a list can mark the one row
 * that was activated rather than greying out the whole page. Marking everything
 * would tell the reader nothing about which of twenty rows they chose.
 */
export function usePendingNavigation() {
  const router = useRouter()
  const [isPending, startTransition] = useTransition()
  const [pendingTo, setPendingTo] = useState<string | null>(null)

  const navigate = useCallback(
    (href: string, key?: string) => {
      if (pendingTo) return // already navigating; ignore the extra clicks
      setPendingTo(key ?? href)
      startTransition(() => {
        router.push(href)
      })
    },
    [pendingTo, router]
  )

  return { navigate, isPending, pendingTo }
}