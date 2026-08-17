'use client'

import { useState, useCallback, useRef } from 'react'
import { CompanySummary } from '@/lib/types'
import { searchCompanies } from '@/lib/api'

interface UseCompaniesReturn {
  searchResults: CompanySummary[]
  searching: boolean
  error: string | null
  search: (query: string) => void
  clearSearch: () => void
}

export function useCompanies(): UseCompaniesReturn {
  const [searchResults, setSearchResults] = useState<CompanySummary[]>([])
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const searchTimer = useRef<NodeJS.Timeout | null>(null)

  const search = useCallback((query: string) => {
    if (!query.trim()) {
      setSearchResults([])
      return
    }

    if (searchTimer.current) {
      clearTimeout(searchTimer.current)
    }

    searchTimer.current = setTimeout(async () => {
      setSearching(true)
      try {
        const results = await searchCompanies(query)
        setSearchResults(results)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Search failed')
      } finally {
        setSearching(false)
      }
    }, 200)
  }, [])

  const clearSearch = useCallback(() => {
    if (searchTimer.current) {
      clearTimeout(searchTimer.current)
    }
    setSearchResults([])
  }, [])

  return {
    searchResults,
    searching,
    error,
    search,
    clearSearch,
  }
}
