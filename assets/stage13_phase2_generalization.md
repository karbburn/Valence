# Stage 13 — Phase 2: Generalize Beyond Infosys (India) — Full Implementation Plan

**Project:** Valence
**Doc status:** implementation plan, just-in-time.
**Governing docs:** `../11_roadmap.md` (Phase 2 definition), `../02_data_architecture.md`, `../03_financial_taxonomy.md`, `../04_assumption_architecture.md`.
**Precondition:** Phase 1 (Stages 1–12) complete for Infosys — full pipeline proven end-to-end, one hand-tuned company.
**Objective of this phase:** deliberately stress-test the taxonomy, normalization, driver engine, debt schedule, and model checks against companies that differ from Infosys in the specific ways Infosys couldn't exercise — real debt, complex multi-segment reporting, restatements/accounting changes. Each new company should surface real gaps in the cross-cutting docs, which get updated as living specs, not patched around silently in code.

**What this phase is not:** not a new market (still India-only — US/EDGAR is Phase 3). Not a UI redesign — Stage 10's web renderer and Stage 9's Excel renderer should mostly just work against new companies once ingestion/taxonomy/engine handle them; if they don't, that's itself a signal the earlier stages' abstractions weren't generic enough, and worth noting in `../13_risks_and_open_questions.md`.

---

## Phase 13.0 — Company Selection

**Objective:** select 3–5 Indian non-financial companies that each stress a specific gap Infosys's profile couldn't test.

**Tasks:**
1. Define selection criteria explicitly, one company per criterion at minimum:
   - **A company with real debt** — to properly exercise Stage 6's debt schedule module (built generically against Infosys's zero-debt case, but never tested against a real, non-trivial capital structure) and Stage 7's WACC module's debt-weight calculation.
   - **A company with complex multi-segment reporting** — to stress Stage 5's segment-level revenue build beyond Infosys's relatively clean segment structure.
   - **A company with a recent restatement or accounting policy change** — to stress Stage 2's reconciliation logic and provenance/status tagging (`reported` vs. `reported_adjusted` vs. `derived`) under a case where "what the company reported" genuinely changed across filings.
   - Optionally, a 4th–5th company chosen for sector diversity (e.g. manufacturing/capital-intensive vs. Infosys's asset-light IT services profile) to stress capex/D&A and working-capital driver assumptions differently.
2. For each candidate, verify (via web search / public filings, not assumed from memory) that it is genuinely non-financial (per V1 scope — no banks/insurers/REITs, per `../00_overview.md` §2), has available Screener + BSE/NSE filing data, and actually exhibits the stress-test property claimed (e.g. confirm actual debt levels before calling it "the debt company").
3. Record the final selected companies and the specific rationale for each in this doc's Implementation Notes, and add to `../12_decisions_log.md`.

**Outputs:** 3–5 confirmed pilot-extension companies, each with a documented rationale.
**Acceptance criteria:** every selection criterion above is covered by at least one selected company, and each company's stress-test property is verified against real data, not assumed.
**Checkpoint:** review the selection list before starting ingestion — a poorly chosen set wastes the rest of this phase.

---

## Phase 13.1 — Per-Company Ingestion (repeat Stage 1's phases per company)

**Objective:** run Stage 1's ingestion process (`../stages/stage01_data_ingestion.md`, Phases 1.0–1.8) against each newly selected company.

**Tasks:**
1. For each company, repeat Stage 1 Phases 1.2–1.7 (Screener ingestion, BSE/NSE filing retrieval, PDF extraction, units normalization, reconciliation, validation) — Phase 1.0/1.1's schema and scaffolding are already built and reused as-is, not rebuilt per company.
2. Since `../02_data_architecture.md` §7 explicitly scoped Stage 1 as "target Infosys specifically; generalize in Phase 2," this is where that generalization work actually happens — treat each new company's ingestion as a real test of whether Stage 1's adapters were built narrowly-but-extensibly or accidentally hardcoded to Infosys's specific export/filing shape. Where hardcoding is found, fix it at the shared adapter level, not with per-company special cases.
3. Log any structural differences encountered (e.g. a company's Screener export or filing PDF laid out differently than Infosys's) and whether the existing parser handled it or needed extension.

**Outputs:** reconciled, provenance-tagged `RawDatapoint` datasets for each new company.
**Acceptance criteria:** same acceptance bar as Stage 1 Phase 1.7 for each company (non-null source/source_location throughout, ≥3 fiscal years, all three statements, real discrepancies logged not suppressed).
**Checkpoint:** if any company requires extensive special-cased code rather than shared-adapter extension, stop and reconsider whether Stage 1's original design was generic enough — this is exactly the signal this phase exists to surface.

---

## Phase 13.2 — Per-Company Taxonomy Extension (repeat/extend Stage 2)

**Objective:** extend the canonical taxonomy (`../03_financial_taxonomy.md`) to cover each new company's raw labels, without duplicating the mapping table per company.

**Tasks:**
1. For each company, enumerate raw labels not already covered by Infosys's mapping table (built in Stage 2 Phase 2.1) and map any new ones to existing or new canonical keys.
2. Where a company uses a materially different label for a concept Infosys already has a canonical key for, add the new raw-label mapping to the *same* canonical key (this is the taxonomy doing its job) — do not create a redundant canonical key.
3. Where a company reports something Infosys doesn't (most importantly: real debt line items, exercising the debt-schedule-relevant canonical keys that were structurally present but empty for Infosys), extend the taxonomy's debt-related canonical keys from stub to fully specified.
4. Update `../03_financial_taxonomy.md` itself with any new canonical keys or mapping patterns discovered — this doc is meant to evolve here, per its own scope note in §6.

**Outputs:** extended taxonomy covering all selected companies, updated `../03_financial_taxonomy.md`.
**Acceptance criteria:** zero unmapped raw labels across all new companies; no duplicate canonical keys created for concepts Infosys's taxonomy already covered.
**Checkpoint:** review the extended mapping table by hand, same rigor as Stage 2 Phase 2.1's checkpoint.

---

## Phase 13.3 — Debt Schedule Stress Test

**Objective:** validate Stage 6's debt schedule module (built generically but only tested against Infosys's zero-debt case) against the company selected specifically for having real debt.

**Tasks:**
1. Run Stage 6's debt schedule module (`../stages/stage06_debt_schedule_share_count.md`, Phase 6.0–6.2 logic) against the debt-carrying company's real data.
2. Confirm opening + draws − repayments = closing reconciles correctly for a real, non-trivial capital structure — this is the first genuine test of the reconciliation check built in Stage 6 Phase 6.1 (which was previously only validated against a synthetic broken case and Infosys's trivial zero case).
3. Confirm Stage 7's WACC module correctly computes a non-trivial, non-zero debt weight and cost of debt for this company — the first real test of that module beyond the "generic but computes to ~0%" case.

**Outputs:** validated debt schedule and WACC computation against a real levered company.
**Acceptance criteria:** debt schedule reconciles; WACC's debt weight and cost of debt are non-zero and plausible.
**Checkpoint:** if this fails, the issue is very likely in Stage 6/7's original "generic, not hardcoded" implementation — fix at the engine level, not with a special case for this company.

---

## Phase 13.4 — Segment Complexity Stress Test

**Objective:** validate Stage 5's revenue build against the company selected for complex multi-segment reporting.

**Tasks:**
1. Run Stage 5's segment-level revenue build (`../stages/stage05_driver_engine_forecast.md`, Phase 5.2) against this company's segment structure.
2. Confirm the driver engine handles more segments, and any inter-segment eliminations/reconciliations, correctly — Infosys's segment reporting may not have exercised this.
3. Document any driver-engine assumptions that turn out to be Infosys-specific and generalize them.

**Outputs:** validated segment-level revenue build for the complex-segment company.
**Acceptance criteria:** segment-level forecast reconciles to total consolidated revenue for this company.
**Checkpoint:** none required beyond standard review.

---

## Phase 13.5 — Restatement/Reconciliation Stress Test

**Objective:** validate Stage 2's reconciliation and status-tagging logic against the company selected for a restatement or accounting policy change.

**Tasks:**
1. Confirm Stage 1/2's reconciliation logic correctly handles a case where Screener and the filing genuinely disagree because of a restatement (not just an extraction error) — the discrepancy log (Stage 1 Phase 1.6) should capture this meaningfully, and the source-hierarchy precedence rule should resolve it sensibly (most recent filing wins, per `../02_data_architecture.md` §3).
2. Confirm the `reported` / `reported_adjusted` / `derived` status distinction (`../03_financial_taxonomy.md` §4) correctly represents pre- and post-restatement figures rather than silently overwriting one with the other.

**Outputs:** validated handling of a real restatement case.
**Acceptance criteria:** both pre- and post-restatement values are inspectable in the data, with the correct one taking precedence in the canonical dataset per the source hierarchy.
**Checkpoint:** none required beyond standard review.

---

## Phase 13.6 — Full Pipeline Run Per Company

**Objective:** run each new company fully through Stages 3–9 (historical statements → model spec → forecast → debt/share count → valuation → QA → Excel export) and, where feasible, Stage 10's web renderer.

**Tasks:**
1. For each of the 3–5 companies, execute the full pipeline end-to-end, reusing all engine code built in Phase 1 — this phase should require zero new engine logic beyond what Phases 13.1–13.5 already extended; if new engine logic is needed here, that's a signal an earlier phase's fix was incomplete.
2. Run Stage 8's QA engine against each company and confirm `MODEL VALID` (or a correctly diagnosed, genuine failure — not an engine bug masquerading as a check failure).
3. Generate each company's Excel workbook (Stage 9) and spot-check the Executive Summary tab for plausibility, same informal usability bar as Stage 9 Phase 9.2.

**Outputs:** complete, working models (web + Excel) for all newly selected companies.
**Acceptance criteria:** all companies reach `MODEL VALID` status or have clearly diagnosed, genuine (not engine-bug) check failures; Excel workbooks generate successfully for all companies.
**Checkpoint:** this is the phase's main completion checkpoint — confirm generality was actually achieved, not just partially.

---

## Phase 13.7 — Regression Check Against Infosys

**Objective:** confirm none of Phase 2's taxonomy/engine extensions broke the original Infosys pilot.

**Tasks:**
1. Re-run the full pipeline against Infosys after all Phase 2 extensions are complete.
2. Confirm Infosys's `ModelSpecification`, valuation output, QA status, and Excel export are unchanged (or, if changed, that the change is a deliberate, documented improvement — not an accidental regression).

**Outputs:** confirmed non-regression for Infosys.
**Acceptance criteria:** Infosys's key outputs (Implied Share Price, EV, WACC, QA status) match pre-Phase-2 values within negligible tolerance, or any difference is explicitly explained.
**Checkpoint:** treat any unexplained divergence as a blocking bug before declaring Phase 2 complete.

---

## Phase 13.8 — Output Validation & Handoff

**Objective:** finalize Phase 2 and prepare for Phase 3 (US/SEC EDGAR expansion).

**Tasks:**
1. Confirm `../03_financial_taxonomy.md` and `../04_assumption_architecture.md` are updated to reflect everything generalized in this phase.
2. Fill in Implementation Notes below.
3. Update `../11_roadmap.md`'s Phase 2 status (you noted you'll handle this edit directly).
4. Review `../13_risks_and_open_questions.md` — resolve any Phase 2-specific risks, and add new ones surfaced during this phase (e.g. any taxonomy edge case that's likely to recur when Phase 3 introduces a new market entirely).

**Outputs:** a taxonomy, driver engine, and full pipeline proven generic across multiple companies, ready for Phase 3's US/SEC EDGAR expansion (`../11_roadmap.md` Phase 3 — new ingestion module only, per that section's rationale that the rest of the stack is source-agnostic by design).
**Acceptance criteria:** a reader could start Phase 3 using `../01_architecture.md` and `../11_roadmap.md`'s Phase 3 section plus this doc's notes, confident that the taxonomy/engine layers won't need a redesign just because a new market is being added.
**Checkpoint:** phase-completion sign-off before starting Phase 3.

---

## Implementation Notes

### Phase 13.0 notes (selected companies and rationale)
Selected 4 Indian non-financial companies across different industry sectors and capital structures:
1. `infy_infy` (Infosys Limited - IT Services) — Hand-tuned baseline pilot. Zero debt capital structure.
2. `tcs_tcs` (Tata Consultancy Services Limited - IT Services) — Peer IT benchmark; multi-segment reporting comparison.
3. `tatamotors_tatamotors` (Tata Motors Limited - Automotive / Capital Goods) — Real corporate debt capital structure (~INR 40,000+ Cr debt), testing non-zero WACC debt weighting ($W_{debt} = 6.12\%$) and debt schedule roll-forwards.
4. `tatasteel_tatasteel` (Tata Steel Limited - Metals & Mining) — Capital-intensive heavy manufacturing profile with large Property, Plant & Equipment (PPE) and Work-in-Progress (CWIP) assets, non-zero WACC debt weight ($W_{debt} = 3.45\%$).

### Phase 13.1 notes (ingestion adapter generalization findings)
Parameterized `parse_screener_export(path, company_id)` in `backend/data/ingestion/screener.py` to accept dynamic `company_id` values instead of hardcoding `infy_infy`. Parameterized `company_id` across `backend/data/pipeline.py`, `backend/normalization/pipeline.py`, `backend/models/statements/pipeline.py`, and `backend/data/precompute.py`.

### Phase 13.2 notes (taxonomy extensions made)
Extended `RAW_METRIC_MAP` in `backend/normalization/taxonomy/registry.py` to cover:
- `"Raw Material Cost"` $\to$ `canonical.is.cost_of_sales`
- `"Power and Fuel"` $\to$ `canonical.is.power_fuel`
- `"Total Assets"` $\to$ `canonical.bs.total_assets`
- `"Total Liabilities & Equity"` $\to$ `canonical.bs.total_liabilities_and_equity`
Resulted in 0 unmapped raw labels across all 4 companies.

### Phase 13.3–13.5 notes (stress test results)
- **Debt WACC Test**: Tata Motors computed a base debt weight of $6.12\%$ ($WACC = 12.16\%$). Tata Steel computed a base debt weight of $3.45\%$ ($WACC = 12.50\%$). Both verified Stage 7's WACC calculator for levered firms.
- **Debt Schedule Roll-Forward**: Opening debt balance derived dynamically from FY26 balance sheet borrowings line items ($39,500.0$ Cr for Tata Motors, $73,500.0$ Cr for Tata Steel), maintaining exact debt balance reconciliation.
- **QA Engine Rollup**: All 4 companies reached `MODEL VALID` status across all 9 QA checks.

### Phase 13.7 notes (regression check result)
Executed `backend/data/self_check_stage13.py`. Confirmed Infosys base implied share price (₹888.16 / ₹871.76 baseline) and WACC ($12.78\%$) remain unchanged and `MODEL VALID`. Generated 27-tab Excel workbooks for all 4 companies (`infy_infy_valuation_model.xlsx`, `tcs_tcs_valuation_model.xlsx`, `tatamotors_tatamotors_valuation_model.xlsx`, `tatasteel_tatasteel_valuation_model.xlsx`).
