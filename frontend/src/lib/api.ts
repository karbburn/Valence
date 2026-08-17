import { CompanySummary, ModelSpecification, RecomputeRequest, SavedModelHeader } from './types'

export type { CompanySummary, SavedModelHeader, RecomputeRequest } from './types'

const BASE = '' // proxied via next.config.ts rewrites

const SAVED_MODELS_KEY = 'valence.savedModels'

interface SavedModelEntry {
  header: SavedModelHeader
  spec: ModelSpecification
}

function readSavedModels(): SavedModelEntry[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(SAVED_MODELS_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function writeSavedModels(entries: SavedModelEntry[]): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(SAVED_MODELS_KEY, JSON.stringify(entries))
  } catch (e) {
    if (e instanceof DOMException && e.name === 'QuotaExceededError') {
      throw new Error('Storage full — delete some saved models to make room.')
    }
    throw e
  }
}

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
  return readSavedModels().map((e) => e.header)
}

export async function saveModel(
  spec: ModelSpecification,
  name: string
): Promise<{ status: string; header: SavedModelHeader }> {
  const entries = readSavedModels()
  const now = new Date().toISOString()
  const modelId = (globalThis.crypto?.randomUUID?.() || Math.random().toString(36).slice(2)).slice(0, 12)
  const header: SavedModelHeader = {
    model_id: modelId,
    user_id: 'local',
    company_id: spec.metadata.company_id,
    name,
    model_version: spec.metadata.model_version,
    created_at: now,
    updated_at: now,
  }
  entries.unshift({ header, spec })
  writeSavedModels(entries)
  return { status: 'saved', header }
}

export async function loadSavedModel(modelId: string): Promise<ModelSpecification> {
  const entry = readSavedModels().find((e) => e.header.model_id === modelId)
  if (!entry) throw new Error('Saved model not found')
  return entry.spec
}

export async function deleteSavedModel(modelId: string): Promise<void> {
  writeSavedModels(readSavedModels().filter((e) => e.header.model_id !== modelId))
}
