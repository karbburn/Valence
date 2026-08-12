# 12 — Decisions Log

**Doc status:** living doc, append-only (don't delete superseded entries — mark them superseded and add the new one). Source of truth for "why did we choose this" questions.

---

| Date | Decision | Choice | Rationale |
|---|---|---|---|
| 2026-08-12 | Market sequencing | India first, then US (SEC EDGAR) | Chosen despite India lacking a clean structured free API — see `02_data_architecture.md` §4 risk note |
| 2026-08-12 | Pilot scope | 1 hand-tuned company, fully working end-to-end | Prove full pipeline before generalizing taxonomy |
| 2026-08-12 | Pilot company | Infosys (INFY) | Debt-free (isolates debt-schedule testing), clean segment revenue disclosure, dual-listed NSE/BSE + NYSE ADR (bridge to Phase 3), heavy analyst coverage (sanity-check for DCF output) |
| 2026-08-12 | Build sequencing | Staged, one-prompt-per-stage, manual checkpoints | Matches established project workflow |
| 2026-08-12 | Data sourcing (India) | Screener.in export + BSE/NSE filings, automated, with user-editable override layer | Automation-first; every value must remain overridable and provenance-tracked |
| 2026-08-12 | Model Specification format | Pydantic schema | Python-native, versionable, matches Python-first modelling stack |
| 2026-08-12 | Excel formula approach | openpyxl, live formulas (Excel computes on open) | Matches real IB/PE model conventions; auditable and traceable |
| 2026-08-12 | Auth / persistence | Yes — Google OAuth via Supabase, saved models per user | Enables repeat usage and versioning |
| 2026-08-12 | Compute strategy | Precompute + cache per company, GitHub Actions pattern | Matches Factor Exposure Analyzer precedent; avoids Render free-tier cold-start/RAM issues |
| 2026-08-12 | Excel branding | Placeholder for V1 | Focus effort on engine correctness first; structural slots left for real branding later |
| 2026-08-12 | Doc structure | One doc per topic (this suite), stage docs written just-in-time | Matches prior project planning-suite pattern; keeps docs focused and AI-agent-consumable |
| 2026-08-12 | Doc format | All planning docs in Markdown, in project folder, treated as source of truth for AI-assisted development | Explicit project requirement |
| 2026-08-12 | Claude's role | Docs/planning only — no code written by Claude in this project | Explicit project requirement |
| 2026-08-12 | Stage 1 storage | Local SQLite (`backend/data/valence.db`) now; Supabase deferred to Stage 11 | Schema already matches `02_data_architecture.md` §2, so migration is a storage-layer swap only |
| 2026-08-12 | company_id convention | `infy_infy` (not `infy_nse`) | One stable id per company regardless of listing exchange |
| 2026-08-12 | PDF extraction lib | pdfplumber only (tabula-py dropped) | No Java runtime on the build machine; pdfplumber handles the Infosys statement tables |
| 2026-08-12 | PDF page indexing | 0-based page indices in code (NSE viewer UI is 1-based) | Avoids an off-by-one parse of the wrong statement page |
| 2026-08-12 | Cross-source reconciliation | Canonical metric vocabulary + filing-wins precedence, tolerance 0.5%/1 Cr | Lets Screener vs regulated filing reconcile on meaning; regulated filing is source of truth |
| 2026-08-12 | Phase 2 Expansion Companies | INFY, TCS, Tata Motors, Tata Steel | TCS (IT peer/multi-segment), Tata Motors (real debt capital structure/non-zero WACC debt weight), Tata Steel (capital-intensive manufacturing PPE/CWIP) |
