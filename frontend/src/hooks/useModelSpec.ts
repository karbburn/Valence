'use client'

import { useState, useCallback, useRef, useEffect } from 'react'
import { ModelSpecification } from '@/lib/types'
import { fetchModelSpec, recomputeModel, revertDriver, revertAll } from '@/lib/api'

interface UseModelSpecReturn {
  spec: ModelSpecification | null
  loading: boolean
  error: string | null
  companyId: string
  loadModel: (companyId: string) => Promise<void>
  applySpec: (spec: ModelSpecification) => void
  recompute: (driverKey: string, value: number, scenario?: string) => Promise<void>
  revert: (driverKey: string, scenario?: string, period?: string) => Promise<void>
  resetAll: (scenario?: string) => Promise<void>
}

export function useModelSpec(initialCompanyId = 'infy_infy'): UseModelSpecReturn {
  const [spec, setSpec] = useState<ModelSpecification | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [companyId, setCompanyId] = useState(initialCompanyId)

  const companyIdRef = useRef(companyId)
  useEffect(() => {
    companyIdRef.current = companyId
  }, [companyId])

  const debounceTimer = useRef<NodeJS.Timeout | null>(null)

  const loadModel = useCallback(async (id: string) => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchModelSpec(id)
      setSpec(data)
      setCompanyId(id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, [])

  const applySpec = useCallback((next: ModelSpecification) => {
    setSpec(next)
    setCompanyId(next.metadata.company_id)
  }, [])

  const recompute = useCallback(
    async (driverKey: string, value: number, scenario = 'base') => {
      if (debounceTimer.current) {
        clearTimeout(debounceTimer.current)
      }

      return new Promise<void>((resolve) => {
        debounceTimer.current = setTimeout(async () => {
          try {
            // Read from current ref to prevent stale closure during company switching
            const updated = await recomputeModel(companyIdRef.current, {
              driver_key: driverKey,
              value,
              scenario,
            })
            setSpec(updated)
          } catch (err) {
            setError(err instanceof Error ? err.message : 'Recompute failed')
          } finally {
            resolve()
          }
        }, 300)
      })
    },
    []
  )

  const revert = useCallback(
    async (driverKey: string, scenario = 'base', period = 'FY27') => {
      try {
        const updated = await revertDriver(companyIdRef.current, driverKey, period, scenario)
        setSpec(updated)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Revert failed')
      }
    },
    []
  )

  const resetAll = useCallback(
    async (scenario = 'base') => {
      try {
        const updated = await revertAll(companyIdRef.current, scenario)
        setSpec(updated)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Reset all failed')
      }
    },
    []
  )

  return { spec, loading, error, companyId, loadModel, applySpec, recompute, revert, resetAll }
}
