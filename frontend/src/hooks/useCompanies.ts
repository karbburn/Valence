'use client'

import { useState, useCallback, useRef } from 'react'
import { CompanySummary } from '@/lib/types'
import { fetchCompanies, searchCompanies } from '@/lib/api'

interface UseCompaniesReturn {
  companies: CompanySummary[]
  searchResults: CompanySummary[]
  loading: boolean
  searching: boolean
  error: string | null
  loadCompanies: () => Promise<void>
  search: (query: string) => Promise<void>
  clearSearch: () => void
}

export function useCompanies(): UseCompaniesReturn {
  const [companies, setCompanies] = useState<CompanySummary[]>([])
  const [searchResults, setSearchResults] = useState<CompanySummary[]>([])
  const [loading, setLoading] = useState(false)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const searchTimer = useRef<NodeJS.Timeout | null>(null)

  const loadCompanies = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchCompanies()
      setCompanies(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch companies')
    } finally {
      setLoading(false)
    }
  }, [])

  const search = useCallback(async (query: string) => {
    if (!query.trim()) {
      setSearchResults([])
      return
    }

    if (searchTimer.current) {
      clearTimeout(searchTimer.current)
    }

    return new Promise<void>((resolve) => {
      searchTimer.current = setTimeout(async () => {
        setSearching(true)
        try {
          const results = await searchCompanies(query)
          setSearchResults(results)
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Search failed')
        } finally {
          setSearching(false)
          resolve()
        }
      }, 200)
    })
  }, [])

  const clearSearch = useCallback(() => {
    setSearchResults([])
  }, [])

  return {
    companies,
    searchResults,
    loading,
    searching,
    error,
    loadCompanies,
    search,
    clearSearch,
  }
}
