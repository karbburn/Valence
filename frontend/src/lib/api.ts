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
      throw new Error('Storage full. Delete some saved models to make room.')
    }
    throw e
  }
}

/**
 * Why a ticker has no model, in the visitor's terms.
 *
 * 503 is the one failure here that is not a fault. It means the filings behind
 * this company are not retrievable: a foreign ordinary with no filing in reach, a
 * recent listing with no annual report, a delisted symbol still in the index.
 * Roughly one in seven tickers drawn at random lands here, so it is a normal
 * outcome and the person reading it is most likely to have followed a link rather
 * than to have mistyped anything.
 *
 * The API's own wording was written for the API. Shown to a visitor it reads as
 * a malfunction, and "retry shortly" is the wrong advice when the filings are not
 * going to appear, so it names the situation and gives somewhere to go instead.
 */
function unavailableMessage(companyId: string, detail: string): string {
  return (
    `${detail} ${companyId.toUpperCase()} is listed, but no annual filings could be reached ` +
    'for it, so there is nothing to model. Try another ticker, or ask for this one and ' +
    'it will be looked at.'
  )
}

export async function fetchModelSpec(companyId: string): Promise<ModelSpecification> {
  const res = await fetch(`${BASE}/api/model/${companyId}`)
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.status }))
    const message = String(detail.detail || `Failed to load ${companyId}`)
    if (res.status === 503) throw new Error(unavailableMessage(companyId, message))
    throw new Error(message)
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

export async function revertAll(
  companyId: string,
  scenario = 'base'
): Promise<ModelSpecification> {
  const res = await fetch(`${BASE}/api/model/revert?company_id=${companyId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ driver_key: 'all', period: 'all', scenario }),
  })
  if (!res.ok) throw new Error('Revert all failed')
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
