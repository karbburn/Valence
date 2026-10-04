import { CompanySummary, ModelSpecification, RecomputeRequest, SavedModelHeader } from './types'
import { withholdUnpublishedPrice } from './publication'

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
 * 503 means the engine could not compile this company right now. It is NOT a verdict
 * on the company. The two causes are "the filings do not exist" and "we could not
 * reach the filings", and from the outside they look identical, which is exactly why
 * the copy must not pick one.
 *
 * The previous wording picked one, and picked the wrong one. It said "no annual
 * filings could be reached for it, so there is nothing to model" -- a factual claim
 * about a company we know nothing about. Adani Green files annually with its
 * exchange, and the page failed because a fetch did not come back. The sentence told
 * a reader the company has no financials when the truth was that we had not asked
 * successfully. A number platform whose error state overstates its own knowledge is
 * the one place a reader is most entitled to be misled, because that is the state
 * they read in order to decide whether to trust anything else on the page.
 *
 * It also printed the internal storage key, uppercased: ADANIGREEN_ADANIGREEN. That
 * is plumbing, not a name, and putting it in front of a visitor tells them the
 * system is showing them its internals. The ticker is what a person recognises.
 *
 * So: name what happened, name the company the way the exchange does, say plainly
 * that the filings most likely exist, and hand over the one action that can still
 * change the outcome.
 */
function unavailableMessage(ticker: string, detail: string): string {
  const label = ticker.trim().toUpperCase()
  // The API leads with "No financial statements could be sourced for this ticker
  // yet", which only repeats what follows. Dropped so one sentence carries it all.
  const tail = detail.replace(
    /^\s*No financial statements could be sourced[^.]*\.\s*/i,
    ''
  )
  return (
    `${label}: ${tail || 'the filings behind this company could not be reached'}. ` +
    'The company does file, so this is most likely a temporary failure to reach ' +
    'them rather than a gap in its reporting. Try again in a few minutes.'
  )
}

export async function fetchModelSpec(companyId: string): Promise<ModelSpecification> {
  const res = await fetch(`${BASE}/api/model/${companyId}`)
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.status }))
    const message = String(detail.detail || `Failed to load ${companyId}`)
    if (res.status === 503) {
      throw new Error(unavailableMessage(companyId.split('_')[0], message))
    }
    throw new Error(message)
  }
  return withholdUnpublishedPrice((await res.json()) as ModelSpecification)
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
