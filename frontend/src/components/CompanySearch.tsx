'use client'

import React, { useState, useRef, useEffect, useId } from 'react'
import { Search, Loader2 } from 'lucide-react'
import { CompanySummary } from '@/lib/types'
import { useCompanies } from '@/hooks/useCompanies'

export interface CompanySearchProps {
  onSelectCompany: (company: CompanySummary) => void
}

export function CompanySearch({ onSelectCompany }: CompanySearchProps) {
  const [query, setQuery] = useState('')
  const [isOpen, setIsOpen] = useState(false)
  const [highlightIndex, setHighlightIndex] = useState(0)

  const { searchResults, searching, search, clearSearch } = useCompanies()
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  // React useId() contains colons (e.g. ":r0:") which break CSS selectors
  // and some assistive tech — strip them for a safe DOM id.
  const listboxId = useId().replace(/:/g, '')

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Keep the highlighted option visible while arrowing through long result lists.
  useEffect(() => {
    if (!isOpen) return
    rootRef.current
      ?.querySelector(`[data-option-index="${highlightIndex}"]`)
      ?.scrollIntoView({ block: 'nearest' })
  }, [highlightIndex, isOpen])

  const openWith = (resultsAvailable: boolean) => {
    setIsOpen(resultsAvailable)
    setHighlightIndex(0)
  }

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const q = e.target.value
    setQuery(q)
    if (q.trim()) {
      search(q)
      openWith(true)
    } else {
      clearSearch()
      setIsOpen(false)
    }
  }

  const handleSelect = (c: CompanySummary) => {
    onSelectCompany(c)
    setQuery('')
    clearSearch()
    setIsOpen(false)
    inputRef.current?.blur()
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      setIsOpen(false)
      inputRef.current?.blur()
      return
    }
    if (!isOpen || searchResults.length === 0) return

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        setHighlightIndex((prev) => (prev + 1) % searchResults.length)
        break
      case 'ArrowUp':
        e.preventDefault()
        setHighlightIndex((prev) => (prev - 1 + searchResults.length) % searchResults.length)
        break
      case 'Home':
        e.preventDefault()
        setHighlightIndex(0)
        break
      case 'End':
        e.preventDefault()
        setHighlightIndex(searchResults.length - 1)
        break
      case 'Enter':
        e.preventDefault()
        if (searchResults[highlightIndex]) handleSelect(searchResults[highlightIndex])
        break
    }
  }

  return (
    <div ref={rootRef} className="relative w-36 sm:w-44 md:w-52 lg:w-56">
      <div className="relative">
        {searching ? (
          <Loader2 className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-accent animate-spin" aria-hidden />
        ) : (
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-dim" aria-hidden />
        )}
        <input
          ref={inputRef}
          id="company-search-input"
          name="company-search"
          type="text"
          role="combobox"
          aria-expanded={isOpen}
          aria-controls={isOpen ? listboxId : undefined}
          aria-haspopup="listbox"
          aria-autocomplete="list"
          aria-activedescendant={
            isOpen && searchResults[highlightIndex]
              ? `${listboxId}-opt-${highlightIndex}`
              : undefined
          }
          aria-label="Search companies by ticker or name"
          placeholder="Search ticker or company…"
          value={query}
          onChange={handleInputChange}
          onFocus={() => {
            if (query.trim() && searchResults.length > 0) setIsOpen(true)
          }}
          onKeyDown={handleKeyDown}
          className="w-full h-8 bg-surface-3 border border-border-interactive rounded-sm pl-8 pr-3 text-[12px] text-text-main placeholder:text-text-faint transition-colors"
        />
      </div>

      {isOpen &&
        (searchResults.length === 0 && !searching ? (
          <div className="absolute left-0 top-9 w-80 px-4 py-3 text-[11px] text-text-dim bg-surface border border-border rounded-sm shadow-pop z-50" role="status">
            No matching companies in the US/India universe.
          </div>
        ) : (
        <div
          id={listboxId}
          role="listbox"
          aria-label="Matching companies"
          aria-busy={searching}
          className="absolute left-0 top-9 w-80 max-h-80 overflow-y-auto bg-surface border border-border rounded-sm shadow-pop z-50 divide-y divide-border"
        >
          {searchResults.map((c, i) => {
              const isUS = c.market === 'us'
              const isOnboarded = c.onboarding_status === 'onboarded'
              const isHighlighted = i === highlightIndex

              return (
                <div
                  key={c.company_id}
                  id={`${listboxId}-opt-${i}`}
                  data-option-index={i}
                  role="option"
                  aria-selected={isHighlighted}
                  onClick={() => handleSelect(c)}
                  onMouseEnter={() => setHighlightIndex(i)}
                  className={`px-3 py-2 cursor-pointer flex items-center justify-between transition-colors ${
                    isHighlighted ? 'bg-surface-2' : ''
                  }`}
                >
                  <div className="flex items-center space-x-2 min-w-0 pr-2">
                    <span className="font-mono font-bold text-[11px] text-text-main bg-canvas border border-border px-1.5 py-0.5 rounded-sm shrink-0">
                      {c.ticker}
                    </span>
                    <div className="min-w-0">
                      <div className="text-[12px] font-semibold text-text-main truncate">
                        {c.name}
                      </div>
                      <div className="text-[10px] text-text-dim truncate">
                        {c.sector || 'Equities'} · {c.exchange || (isUS ? 'SEC EDGAR' : 'NSE')}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center space-x-1.5 shrink-0">
                    <span
                      title={
                        isOnboarded
                          ? 'Precomputed model loads instantly'
                          : 'Financials are ingested live on selection'
                      }
                      className={`text-[10px] font-medium px-1.5 py-0.5 rounded-sm border cursor-help ${
                        isOnboarded
                          ? 'bg-positive-subtle text-positive border-positive/30'
                          : 'bg-accent-subtle text-accent-hover border-accent-border'
                      }`}
                    >
                      {isOnboarded ? 'Instant' : 'Live build'}
                    </span>
                    <span
                      title={isUS ? 'Listed in the US' : 'Listed in India'}
                      className={`text-[10px] font-medium px-1.5 py-0.5 rounded-sm border cursor-help ${
                        isUS
                          ? 'bg-blue-950/60 text-blue-300 border-blue-800'
                          : 'bg-orange-950/60 text-orange-300 border-orange-800'
                      }`}
                    >
                      {c.market.toUpperCase()}
                    </span>
                  </div>
                </div>
              )
            })}
        </div>
        ))}
    </div>
  )
}
