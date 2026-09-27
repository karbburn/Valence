import type { ReactNode, ElementType } from 'react'

/**
 * Scroll-entry reveal.
 *
 * A class, not a component with a hook. The animation itself lives in
 * globals.css as a scroll-driven `view()` timeline, which means it needs no
 * JavaScript, cannot fail to run, and leaves the block exactly where it belongs
 * on a browser that does not support the feature.
 *
 * It moves without hiding. An earlier version faded blocks in from opacity 0
 * behind an IntersectionObserver, and any block whose observer had not fired
 * yet rendered as blank space. That is indistinguishable from a broken section
 * in a screenshot and in print, and it is a real risk for a visitor on a slow
 * connection. The worst case here is a few pixels of offset.
 *
 * Sequencing still happens: the reader's eye is walked down the page in the
 * intended order, which is the only reason any of this exists.
 */

interface RevealProps {
  children: ReactNode
  className?: string
  as?: ElementType
}

export function Reveal({ children, className = '', as: Tag = 'div' }: RevealProps) {
  return <Tag className={`reveal ${className}`.trim()}>{children}</Tag>
}

/**
 * Container for a staggered group.
 *
 * Stagger is expressed as a per-child animation-range offset rather than a
 * delay, because a delay does not compose with a scroll-driven timeline.
 */
export function RevealGroup({
  children,
  className = '',
  step = 0.04,
}: {
  children: ReactNode
  className?: string
  step?: number
}) {
  return (
    <div className={className} data-reveal-group={String(step)}>
      {children}
    </div>
  )
}

export function RevealItem({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return <div className={`reveal ${className}`.trim()}>{children}</div>
}
