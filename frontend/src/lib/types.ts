// TypeScript types matching backend Pydantic model specification schema

export type MarketType = 'india' | 'us'
export type ScenarioLabel = 'base' | 'bull' | 'bear' | 'custom'
export type AssumptionType = 'model_generated' | 'user_override'
export type CheckCategory = 'accounting' | 'valuation' | 'data_quality'
export type TerminalValueMethod = 'gordon_growth' | 'exit_multiple'

export interface ModelMetadata {
  company_id: string
  ticker: string
  name: string
  market: MarketType
  currency: string
  units: string
  fiscal_year_end: string
  shares_outstanding: number | null
  model_version: string
  generation_date: string
}

export interface HistoricalLineItem {
  canonical_key: string
  period_label: string
  period_end_date: string
  value: number
  currency: string
  units: string
  status: string
  source_datapoint_ids: string[]
  derivation_rule: string | null
}

export interface Historicals {
  periods: string[]
  line_items: HistoricalLineItem[]
}

export interface ForecastLineItem {
  canonical_key: string
  period_label: string
  period_end_date: string
  value: number
  scenario: ScenarioLabel
  currency: string
  units: string
  driver_key: string | null
}

export interface Forecast {
  horizon_years: number
  periods: string[]
  scenarios: ScenarioLabel[]
  line_items: ForecastLineItem[]
}

export interface DriverDefinition {
  driver_key: string
  label: string
  unit: string
  min: number
  max: number
  step: number
}

export interface AssumptionObject {
  assumption_id: string
  driver_key: string
  value: number
  period: string
  scenario: ScenarioLabel
  type: AssumptionType
  source: string
  previous_model_value: number | null
  last_updated: string
}

export interface WACCBreakdown {
  risk_free_rate: number | null
  beta: number | null
  equity_risk_premium: number | null
  cost_of_equity: number | null
  pre_tax_cost_of_debt: number | null
  tax_rate: number | null
  cost_of_debt: number | null
  equity_weight: number | null
  debt_weight: number | null
  wacc: number | null
  source_notes: string
}

export interface FCFFPeriod {
  period: string
  ebit: number | null
  tax_rate: number | null
  nopat: number | null
  da: number | null
  capex: number | null
  delta_working_capital: number | null
  stock_compensation?: number | null
  fcff: number | null
  discount_factor: number | null
  pv_fcff: number | null
  timing_convention: 'mid_year' | 'end_year'
}

export interface TerminalValue {
  method: TerminalValueMethod
  timing_convention: 'mid_year' | 'end_year'
  terminal_growth_rate: number | null
  final_year_fcff: number | null
  terminal_value_undiscounted: number | null
  terminal_nopat: number | null
  reinvestment_rate: number | null
  implied_roic: number | null
  exit_multiple: number | null
  final_year_ebitda: number | null
  exit_multiple_tv_undiscounted: number | null
  discount_factor: number | null
  terminal_value_pv: number | null
  tv_pct_of_ev: number | null
}

export interface DCFBridge {
  sum_pv_fcff: number | null
  pv_terminal_value: number | null
  enterprise_value: number | null
  cash_and_equivalents: number | null
  marketable_securities: number | null
  non_current_investments: number | null
  total_debt: number | null
  operating_lease_liabilities?: number | null
  minority_interest: number | null
  preferred_stock: number | null
  less_net_debt: number | null
  equity_value: number | null
  shares_outstanding: number | null
  implied_share_price: number | null
  /** Date of the balance sheet the net debt figure was struck on. */
  balance_sheet_as_of?: string | null
  /** How that balance sheet was obtained. */
  balance_sheet_source?: string | null
  /** What counts as debt, stated in words. */
  debt_basis_note?: string | null
}

export interface ReverseDCF {
  market_price: number | null
  market_price_date?: string | null
  market_price_source?: string | null
  implied_terminal_growth: number | null
  implied_revenue_cagr: number | null
  method_note: string
}

export interface SensitivityTable {
  row_driver: string
  col_driver: string
  row_values: number[]
  col_values: number[]
  results_grid: (number | null)[][]
}

export interface ValuationOutput {
  scenario: ScenarioLabel
  timing_convention: 'mid_year' | 'end_year'
  wacc: WACCBreakdown
  fcff_by_period: FCFFPeriod[]
  terminal_value: TerminalValue
  dcf_bridge: DCFBridge
  reverse_dcf: ReverseDCF
  sensitivity_tables: SensitivityTable[]
}

export interface ModelCheckResult {
  check_name: string
  category: CheckCategory
  passed: boolean
  detail: string
  implicated_canonical_keys: string[]
  implicated_periods: string[]
  implicated_scenarios: string[]
}

export interface QAResults {
  checks: ModelCheckResult[]
}

export interface ModelSpecification {
  metadata: ModelMetadata
  historicals: Historicals
  forecast: Forecast
  drivers: DriverDefinition[]
  assumptions: AssumptionObject[]
  scenarios: { name: string; label: ScenarioLabel }[]
  valuation: ValuationOutput[]
  qa: QAResults
}

export interface CompanySummary {
  company_id: string
  ticker: string
  name: string
  market: string
  exchange: string
  currency: string
  units: string
  fiscal_year_end: string
  onboarding_status: string
  sector?: string
  /**
   * Whether a valuation model has actually been compiled for this company, as
   * opposed to its filings merely being onboarded. Distinct states: a company
   * can be onboarded with no model, and the ticker page will build one on first
   * open. Optional because older saved payloads predate it, and absent must be
   * read as "unknown", never as "ready".
   */
  has_model?: boolean
  /**
   * Public URL segment. Present on every search result so selecting a company
   * can rewrite the address bar to a link that resolves. Optional because
   * locally-saved and legacy payloads may predate it.
   */
  slug?: string
}

export interface SavedModelHeader {
  model_id: string
  user_id: string
  company_id: string
  name: string
  model_version: string
  created_at: string
  updated_at: string
}

export interface RecomputeRequest {
  driver_key: string
  value: number
  period?: string
  scenario?: string
}
