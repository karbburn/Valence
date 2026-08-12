# 11 — Roadmap

**Doc status:** source of truth for build sequencing. Depends on: all preceding docs.
**Convention:** stage-specific implementation detail docs are written **just-in-time**, immediately before each build session — not all upfront. This doc tracks phase/stage structure and status only.

---

## Phase 1 — India Pilot (Infosys, hand-tuned)

| # | Stage | Depends on docs | Status |
|---|---|---|---|
| 1 | Data Ingestion & Source-of-Truth Layer | `02` | **Complete (2026-08-12)** — `assets/stage01_data_ingestion.md` |
| 2 | Financial Taxonomy & Normalization | `02`, `03` | **Complete (2026-08-12)** — `assets/stage02_taxonomy_normalization.md` |
| 3 | Historical 3-Statement Model | `03` | **Complete (2026-08-12)** — `assets/stage03_historical_statements.md` |
| 4 | Model Specification (Pydantic schema v1) | `04`, `05` | **Complete (2026-08-12)** — `assets/stage04_model_specification.md` |
| 5 | Driver Engine & Forecast | `04`, `05` | **Complete (2026-08-12)** — `assets/stage05_driver_engine_forecast.md` |
| 6 | Debt Schedule & Share Count | `05` | **Complete (2026-08-12)** — `assets/stage06_debt_schedule_share_count.md` |
| 7 | Valuation Engine | `06` | **Complete (2026-08-12)** — `assets/stage07_valuation_engine.md` |
| 8 | Model Checks / QA Engine | `07` | **Complete (2026-08-12)** — `assets/stage08_qa_engine.md` |
| 9 | Excel Renderer | `08` | **Complete (2026-08-12)** — `assets/stage09_excel_renderer.md` |
| 10 | Web Renderer (Analyst Mode first) | `09` | **Complete (2026-08-12)** — `assets/stage10_web_renderer.md` |
| 11 | Auth & Persistence | `10` | **Complete (2026-08-12)** — `assets/stage11_auth_persistence.md` |
| 12 | Precompute/Cache Pipeline | `10` | **Complete (2026-08-12)** — `assets/stage12_precompute_cache_pipeline.md` |

## Phase 2 — Generalize Beyond Infosys (India)

**Complete (2026-08-12)** — `assets/stage13_phase2_generalization.md`

Executed full pipeline end-to-end against 4 Indian non-financial companies across sectors (Infosys, TCS, Tata Motors, Tata Steel). Validated non-zero debt WACC calculation, debt schedule roll-forwards, multi-segment reporting, capital-intensive manufacturing balance sheets, 0 unmapped raw labels, `MODEL VALID` QA rollup, 27-tab Excel workbook exports, and Infosys pilot non-regression.

13.0 — company selection against explicit stress-test criteria (Infosys, TCS, Tata Motors, Tata Steel) — Complete
13.1 — per-company ingestion, reusing parameterized Stage 1 adapters — Complete
13.2 — taxonomy extension covering new manufacturing & capital structure raw labels — Complete
13.3 / 13.4 / 13.5 — targeted stress tests: real debt WACC (Tata Motors 6.12%, Tata Steel 3.45%), segment builds, restatements — Complete
13.6 — full pipeline run per company (web + Excel, all 4 MODEL VALID) — Complete
13.7 — regression check confirming Infosys pilot outputs unchanged (₹888.16 price, 12.78% WACC) — Complete
13.8 — handoff to Phase 3 — Complete

## Phase 3 — US Expansion (SEC EDGAR)

New ingestion module against SEC EDGAR's company-facts API (structured, free, XBRL-based — much cleaner than the India pilot's PDF/export sourcing). Because normalization/taxonomy/Model Specification layers are source-agnostic by design (`01_architecture.md`), this should mostly be a new ingestion + taxonomy-mapping module, not a rebuild of the engine. Infosys's dual-listing (NYSE ADR, SEC 20-F filer) makes it a natural first bridge company to validate the US ingestion path against a company already known end-to-end.

## Phase 4 — Later Features (not scoped yet — do not build speculatively)

Trading comps, precedent transactions, valuation triangulation, M&A / accretion-dilution, LBO, industry-specific models (banks, insurance, REITs).

## Process rule for the agent

Before starting a new stage: write that stage's implementation doc (e.g. `stages/stage01_data_ingestion.md`) referencing the relevant cross-cutting docs above, get it reviewed/confirmed, then implement. Update this table's status column when a stage completes. Do not skip ahead to a later stage's doc while an earlier one is incomplete, and do not silently expand a stage's scope beyond what its doc says without updating the doc first.
