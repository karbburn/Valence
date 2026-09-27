'use client'

import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Search, Loader2 } from 'lucide-react'
import type { CompanySummary } from '@/lib/types'
import { stockPath } from '@/lib/tickers'
import { getCurrencySymbol } from '@/lib/formatters'

/**
 * The page's primary action.
 *
 * The search is the call to action rather than a button that leads to a page
 * containing a search box. Every audience this page serves for comes to act on a
 * ticker, so putting one step between them and the model is a step they may not
 * take.
 *
 * Reads ?q= on mount, which is what makes the SearchAction in the site JSON-LD a
 * working target rather than a declared one.
 */
export function TickerSearch() {
  // The landing page mounts two of these and /stock mounts one, all on the same
  // document. A fixed id duplicated every <label for> target and left
  // aria-controls pointing at the wrong listbox on all but one instance.
  // Colons are legal in an id but break querySelector, so they are stripped.
  const uid = useId().replace(/:/g, '')
  const inputId = `ticker-input-${uid}`
  const listboxId = `ticker-listbox-${uid}`

  const router = useRouter()
  const searchParams = useSearchParams()
  const prefill = searchParams.get('q') ?? ''

  const [query, setQuery] = useState(prefill)
  const [results, setResults] = useState<CompanySummary[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [highlight, setHighlight] = useState(0)
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const search = useCallback(async (q: string): Promise<CompanySummary[]> => {
    const res = await fetch(`/api/companies/search?q=${encodeURIComponent(q)}&limit=8`)
    if (!res.ok) return []
    return res.json()
  }, [])

  // Prefill from ?q= and take focus, so a search-engine or AI-assistant result
  // lands the visitor one keystroke from a model.
  //
  // Every setState here sits in a promise callback rather than the effect body.
  // Setting state synchronously in an effect triggers a cascading render, and
  // this one runs on every visit. The spinner is deliberately skipped: the
  // prefill is a single request behind a full page load, and a flash of loading
  // state on entry reads as a glitch rather than as feedback.
  useEffect(() => {
    if (!prefill) return
    inputRef.current?.focus()
    let cancelled = false
    void search(prefill).then((found) => {
      if (cancelled || found.length === 0) return
      setResults(found)
      setOpen(true)
    })
    return () => {
      cancelled = true
    }
  }, [prefill, search])

  useEffect(() => {
    const onClickAway = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClickAway)
    return () => document.removeEventListener('mousedown', onClickAway)
  }, [])

  const onChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const q = e.target.value
    setQuery(q)
    if (timer.current) clearTimeout(timer.current)
    if (!q.trim()) {
      setResults([])
      setOpen(false)
      setLoading(false)
      return
    }
    setLoading(true)
    timer.current = setTimeout(() => {
      void search(q).then((found) => {
        setResults(found)
        setHighlight(0)
        setOpen(found.length > 0)
        setLoading(false)
      })
    }, 200)
  }

  const choose = (c: CompanySummary) => {
    setOpen(false)
    // A result without a slug has no canonical page, so fall back to the index
    // rather than pushing a URL that would 404.
    router.push(c.slug ? stockPath(c.slug) : '/stock')
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      setOpen(false)
      inputRef.current?.blur()
      return
    }
    if (!open || results.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlight((p) => (p + 1) % results.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlight((p) => (p - 1 + results.length) % results.length)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (results[highlight]) choose(results[highlight])
    }
  }

  return (
    <div ref={rootRef} className="relative w-full max-w-[440px]">
      <label htmlFor={inputId} className="sr-only">
        Search a ticker or company
      </label>
      <div className="relative">
        {loading ? (
          <Loader2
            className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-accent animate-spin"
            aria-hidden
          />
        ) : (
          <Search
            className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-text-dim"
            aria-hidden
          />
        )}
        <input
          ref={inputRef}
          id={inputId}
          name="ticker"
          type="text"
          role="combobox"
          aria-expanded={open && results.length > 0}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-label="Search a ticker or company"
          placeholder="Search a ticker, e.g. NVDA or TCS"
          value={query}
          onChange={onChange}
          onKeyDown={onKeyDown}
          onFocus={() => results.length > 0 && setOpen(true)}
          className="w-full h-12 bg-surface border border-border-interactive rounded-sm pl-10 pr-4 text-[14px] text-text-main placeholder:text-text-faint focus:border-accent-border transition-colors"
        />
      </div>

      {open && results.length > 0 && (
        <ul
          id={listboxId}
          role="listbox"
          aria-label="Matching companies"
          className="absolute left-0 right-0 top-[52px] z-50 max-h-[320px] overflow-y-auto bg-surface border border-border rounded-sm shadow-pop divide-y divide-border list-none m-0 p-0"
        >
          {results.map((c, i) => {
            const sym = getCurrencySymbol(c.currency)
            return (
              <li
                key={c.company_id}
                role="option"
                aria-selected={i === highlight}
                onMouseEnter={() => setHighlight(i)}
                onClick={() => choose(c)}
                className={`px-3.5 py-2.5 cursor-pointer flex items-center justify-between gap-3 transition-colors ${
                  i === highlight ? 'bg-surface-2' : ''
                }`}
              >
                <span className="flex items-center gap-2.5 min-w-0">
                  <span className="font-mono text-[11px] font-bold text-accent-hover bg-accent-subtle border border-accent-border rounded-sm px-1.5 py-0.5 shrink-0">
                    {c.ticker}
                  </span>
                  <span className="min-w-0">
                    <span className="block text-[13px] text-text-main truncate">{c.name}</span>
                    <span className="block font-mono text-[10px] text-text-dim truncate">
                      {c.exchange} {sym ? `· ${c.currency}` : ''}
                    </span>
                  </span>
                </span>
                <span className="font-mono text-[10px] text-text-faint shrink-0">
                  {c.onboarding_status === 'onboarded' ? 'Ready' : 'On demand'}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
