'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { slugFromPath } from '@/lib/tickers'
import { SOCIAL, CONTACT_EMAIL } from '@/lib/site'

/**
 * Not-found page.
 *
 * Distinguishes "no such ticker" from "in the universe but no model yet". At
 * thousands of tickers that difference is the gap between a dead end and a
 * roadmap, and a single flat message throws it away.
 */
export default function NotFound() {
  const pathname = usePathname()
  const slug = slugFromPath(pathname)
  const [known, setKnown] = useState<boolean | null>(null)

  // Only the async result sets state. The attempted slug is derived from the
  // pathname during render rather than mirrored into state, so navigating
  // between two unknown paths cannot leave a stale value behind.
  useEffect(() => {
    if (!slug) return
    let cancelled = false
    fetch(`/api/companies/resolve?slug=${encodeURIComponent(slug)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((body) => {
        if (cancelled) return
        // Resolves only for companies with a slug, so a hit here means the
        // ticker is real but its model cannot be built.
        setKnown(Boolean(body))
      })
      .catch(() => {
        if (!cancelled) setKnown(null)
      })
    return () => {
      cancelled = true
    }
  }, [slug])

  return (
    <div className="min-h-screen bg-canvas text-text-main font-sans flex flex-col">
      <main className="flex-1 w-full max-w-[1400px] mx-auto px-4 sm:px-5 py-16 sm:py-24">
        <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-text-dim">
          {slug ? `No model for ${slug}` : 'Not found'}
        </p>

        <h1 className="mt-3 text-[30px] sm:text-[40px] font-bold tracking-tight leading-[1.1] text-text-main max-w-[20ch]">
          {known
            ? 'This ticker is listed, but no model has been built for it yet.'
            : 'We could not find that ticker.'}
        </h1>

        <p className="mt-4 text-[14px] text-text-muted max-w-[60ch] leading-relaxed">
          {known
            ? 'It is in the covered universe, but the engine has not compiled a model for it. Financial statements could not be sourced from the filings we read, so there is nothing to show that would be honest.'
            : 'Check the ticker spelling, or browse the full list of companies with a working model.'}
        </p>

        <div className="mt-8 flex flex-wrap items-center gap-3">
          <Link
            href="/stock"
            className="inline-flex items-center h-9 px-4 bg-accent hover:bg-accent-hover text-canvas text-[13px] font-semibold rounded-sm transition-colors active:translate-y-[1px]"
          >
            Browse all tickers
          </Link>
          <Link
            href="/"
            className="inline-flex items-center h-9 px-4 bg-surface border border-border text-text-muted hover:text-text-main hover:bg-surface-2 text-[13px] font-medium rounded-sm transition-colors active:translate-y-[1px]"
          >
            Back to Valence
          </Link>
          <a
            href={`mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(`Valence ticker request: ${slug ?? ''}`)}`}
            className="inline-flex items-center h-9 px-4 text-[13px] text-accent hover:text-accent-hover border border-accent-border rounded-sm transition-colors active:translate-y-[1px]"
          >
            Request this ticker
          </a>
        </div>
      </main>

      <footer className="border-t border-border">
        <div className="w-full max-w-[1400px] mx-auto px-4 sm:px-5 py-5 flex flex-wrap items-center gap-x-5 gap-y-2 text-[12px] text-text-dim">
          <Link href="/" className="hover:text-text-main transition-colors">
            Home
          </Link>
          <Link href="/stock" className="hover:text-text-main transition-colors">
            All tickers
          </Link>
          <Link href="/methodology" className="hover:text-text-main transition-colors">
            Methodology
          </Link>
          <span className="ml-auto flex items-center gap-4">
            <a href={SOCIAL.github} className="hover:text-text-main transition-colors">
              GitHub
            </a>
            <a href={SOCIAL.linkedin} className="hover:text-text-main transition-colors">
              LinkedIn
            </a>
          </span>
        </div>
      </footer>
    </div>
  )
}
