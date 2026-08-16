'use client'

import React, { useState, useRef, useEffect } from 'react'
import { Search, Loader2 } from 'lucide-react'
import { CompanySummary } from '@/lib/types'
import { useCompanies } from '@/hooks/useCompanies'

export interface CompanySearchProps {
  onSelectCompany: (companyId: string, ticker: string, name: string) => void
}

export function CompanySearch({ onSelectCompany }: CompanySearchProps) {
  const [query, setQuery] = useState('')
  const [isOpen, setIsOpen] = useState(false)
  const [highlightIndex, setHighlightIndex] = useState(0)

  const { searchResults, searching, search, clearSearch } = useCompanies()
  const dropdownRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node) &&
        inputRef.current &&
        !inputRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const q = e.target.value
    setQuery(q)
    setHighlightIndex(0)
    if (q.trim()) {
      search(q)
      setIsOpen(true)
    } else {
      clearSearch()
      setIsOpen(false)
    }
  }

  const handleSelect = (c: CompanySummary) => {
    onSelectCompany(c.company_id, c.ticker, c.name)
    setQuery('')
    clearSearch()
    setIsOpen(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!isOpen || searchResults.length === 0) return

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlightIndex((prev) => (prev + 1) % searchResults.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlightIndex((prev) => (prev - 1 + searchResults.length) % searchResults.length)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (searchResults[highlightIndex]) {
        handleSelect(searchResults[highlightIndex])
      }
    } else if (e.key === 'Escape') {
      setIsOpen(false)
    }
  }

  return (
    <div className="relative w-64 select-none">
      {/* Search Input */}
      <div className="relative">
        {searching ? (
          <Loader2 className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#0ea5e9] animate-spin" />
        ) : (
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#64748b]" />
        )}
        <input
          ref={inputRef}
          type="text"
          placeholder="Search ticker or company..."
          value={query}
          onChange={handleInputChange}
          onFocus={() => {
            if (query.trim() && searchResults.length > 0) setIsOpen(true)
          }}
          onKeyDown={handleKeyDown}
          className="w-full h-8 bg-[#0d1220] border border-[#2a3652] rounded-[4px] pl-8 pr-3 text-[12px] text-[#f8fafc] placeholder-[#475569] focus:outline-none focus:border-[#0ea5e9] focus:ring-1 focus:ring-[#0ea5e9]/30 transition-colors"
        />
      </div>

      {/* Dropdown Results */}
      {isOpen && (
        <div
          ref={dropdownRef}
          className="absolute left-0 top-9 w-80 max-h-80 overflow-y-auto bg-[#111622] border border-[#1e283d] rounded-[4px] shadow-2xl z-50 divide-y divide-[#1e283d]"
        >
          {searchResults.length === 0 ? (
            <div className="px-4 py-3 text-[11px] text-[#64748b]">
              No matching companies found in US/India universe
            </div>
          ) : (
            searchResults.map((c, i) => {
              const isUS = c.market === 'us'
              const isOnboarded = c.onboarding_status === 'onboarded'
              const isHighlighted = i === highlightIndex

              return (
                <div
                  key={c.company_id}
                  onClick={() => handleSelect(c)}
                  onMouseEnter={() => setHighlightIndex(i)}
                  className={`px-3 py-2 cursor-pointer flex items-center justify-between transition-colors ${
                    isHighlighted ? 'bg-[#192030]' : 'hover:bg-[#192030]/60'
                  }`}
                >
                  <div className="flex items-center space-x-2 min-w-0 pr-2">
                    <span className="font-mono font-bold text-[11px] text-[#f8fafc] bg-[#080c14] border border-[#1e283d] px-1.5 py-0.5 rounded-[3px] shrink-0">
                      {c.ticker}
                    </span>
                    <div className="min-w-0">
                      <div className="text-[12px] font-semibold text-[#f8fafc] truncate">
                        {c.name}
                      </div>
                      <div className="text-[10px] text-[#64748b] truncate">
                        {c.sector || 'Equities'} · {c.exchange || (isUS ? 'SEC_EDGAR' : 'NSE')}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center space-x-1.5 shrink-0">
                    <span
                      className={`text-[9px] font-bold px-1.5 py-0.5 rounded-[2px] border ${
                        isOnboarded
                          ? 'bg-[#10b981]/10 text-[#10b981] border-[#10b981]/30'
                          : 'bg-[#0ea5e9]/10 text-[#7dd3fc] border-[#0ea5e9]/30'
                      }`}
                    >
                      {isOnboarded ? 'INSTANT' : 'LIVE'}
                    </span>
                    <span
                      className={`text-[9px] font-bold px-1.5 py-0.5 rounded-[2px] border ${
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
            })
          )}
        </div>
      )}
    </div>
  )
}
