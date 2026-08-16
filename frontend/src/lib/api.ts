import { CompanySummary, ModelSpecification, RecomputeRequest, SavedModelHeader } from './types'

export type { CompanySummary, SavedModelHeader, RecomputeRequest } from './types'

const BASE = '' // proxied via next.config.ts rewrites

export async function fetchModelSpec(companyId: string): Promise<ModelSpecification> {
  const res = await fetch(`${BASE}/api/model/${companyId}`)
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.status }))
    throw new Error(detail.detail || `Failed to load ${companyId}`)
  }
  return res.json()
}

export async function recomputeModel(
  companyId: string,
  req: RecomputeRequest
): Promise<ModelSpecification> {
  const res = await fetch(`${BASE}/api/model/recompute?company_id=${companyId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ period: 'FY27', scenario: 'base', ...req }),
  })
  if (!res.ok) throw new Error('Recompute failed')
  return res.json()
}

export async function revertDriver(
  companyId: string,
  driverKey: string,
  period = 'FY27',
  scenario = 'base'
): Promise<ModelSpecification> {
  const res = await fetch(`${BASE}/api/model/revert?company_id=${companyId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ driver_key: driverKey, period, scenario }),
  })
  if (!res.ok) throw new Error('Revert failed')
  return res.json()
}

export async function fetchCompanies(): Promise<CompanySummary[]> {
  const res = await fetch(`${BASE}/api/companies`)
  if (!res.ok) throw new Error('Failed to load companies')
  return res.json()
}

export async function searchCompanies(
  query: string,
  limit = 15
): Promise<CompanySummary[]> {
  const res = await fetch(
    `${BASE}/api/companies/search?q=${encodeURIComponent(query)}&limit=${limit}`
  )
  if (!res.ok) throw new Error('Search failed')
  return res.json()
}

export async function fetchSavedModels(): Promise<SavedModelHeader[]> {
  const res = await fetch(`${BASE}/api/models`)
  if (!res.ok) throw new Error('Failed to load saved models')
  return res.json()
}

export async function saveModel(
  companyId: string,
  name: string
): Promise<{ status: string; header: SavedModelHeader }> {
  const res = await fetch(`${BASE}/api/models/save`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, company_id: companyId }),
  })
  if (!res.ok) throw new Error('Save failed')
  return res.json()
}

export async function loadSavedModel(
  modelId: string
): Promise<ModelSpecification> {
  const res = await fetch(`${BASE}/api/models/${modelId}`)
  if (!res.ok) throw new Error('Load failed')
  return res.json()
}

export async function deleteSavedModel(modelId: string): Promise<void> {
  const res = await fetch(`${BASE}/api/models/${modelId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Delete failed')
}
