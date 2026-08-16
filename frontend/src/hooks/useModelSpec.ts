'use client'

import { useState, useCallback, useRef } from 'react'
import { ModelSpecification } from '@/lib/types'
import { fetchModelSpec, recomputeModel, revertDriver } from '@/lib/api'

interface UseModelSpecReturn {
  spec: ModelSpecification | null
  loading: boolean
  error: string | null
  companyId: string
  loadModel: (companyId: string) => Promise<void>
  recompute: (driverKey: string, value: number, scenario?: string) => Promise<void>
  revert: (driverKey: string, scenario?: string) => Promise<void>
}

export function useModelSpec(initialCompanyId = 'infy_infy'): UseModelSpecReturn {
  const [spec, setSpec] = useState<ModelSpecification | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [companyId, setCompanyId] = useState(initialCompanyId)

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

  const recompute = useCallback(
    async (driverKey: string, value: number, scenario = 'base') => {
      if (debounceTimer.current) {
        clearTimeout(debounceTimer.current)
      }

      return new Promise<void>((resolve) => {
        debounceTimer.current = setTimeout(async () => {
          try {
            const updated = await recomputeModel(companyId, {
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
    [companyId]
  )

  const revert = useCallback(
    async (driverKey: string, scenario = 'base') => {
      try {
        const updated = await revertDriver(companyId, driverKey, 'FY27', scenario)
        setSpec(updated)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Revert failed')
      }
    },
    [companyId]
  )

  return { spec, loading, error, companyId, loadModel, recompute, revert }
}
