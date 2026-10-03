# Valence — Equity Valuation & Financial Modeling Workbench

<p align="center">
  <img src="frontend/public/opengraph.png" width="880" alt="Valence — equity valuation and financial modeling workbench">
</p>

Valence is a browser-based equity valuation workbench. It ingests filings, normalizes them into a canonical taxonomy, runs a driver-based five-year three-statement forecast, discounts unlevered FCFF at a CAPM-derived WACC, solves the reverse DCF, benchmarks public comps, audits the result against 23 accounting and model checks, and exports the whole thing to a 31-tab Excel workbook with live formulas.

Every published figure traces to an official filing, and anything that does not is labelled as something else rather than presented as a filing-derived number.

Every company has its own public URL. `valence.sourabhpradhan.in/NVDA` is a deep link that opens with the model already in the HTML, so the figures are readable before any script runs.

---

## Key Features

- **Per-ticker deep links.** Every covered company has a canonical page at `/stock/{slug}`, with `/NVDA` as a short form that redirects to it. The model is server-rendered and revalidated hourly, so a shared link is a working link rather than an empty shell.
- **Driver-Based 5-Year Forecasting Engine**: Income Statement, Balance Sheet, and Cash Flow across **Base**, **Bull**, and **Bear** scenarios, driven by operational metrics (Revenue Growth, EBITDA/EBIT Margins, CapEx % Revenue, D&A %, DSO, DPO, Tax Rate).
- **Institutional DCF & WACC Buildup**: full Free Cash Flow to Firm build with non-cash operating working capital, dynamic WACC (CAPM cost of equity plus tax-shielded cost of debt), Gordon Growth and Exit EV/EBITDA terminal values, and an Enterprise Value to Implied Share Price bridge.
- **Dynamic Reverse DCF & 2D Sensitivity**: solves for the market-implied perpetuity growth rate by exact closed-form inversion, paired with live two-way sensitivity grids over WACC against terminal growth and exit multiple. When no growth rate in a sane band can reproduce the market price, the solver returns nothing rather than a number it cannot justify.
- **Public Trading Comps & Football Field Synthesis**: benchmarks the company against sector peers (EV/Sales, EV/EBITDA, P/E, FCF Yield %, ROIC %) and synthesizes cross-methodology valuation ranges. *Football field and comps are Excel-export features; the web workbench shows the DCF and the scenario matrix.*
- **Private Equity Exit Returns & IRR Waterfall**: 3-year and 5-year Exit Equity Value, MoIC, and Equity IRR under each exit scenario with entry-price sensitivity grids.
- **Multi-Market & Multi-Currency Support**: US equities (NASDAQ/NYSE, USD millions) and Indian equities (NSE/BSE, INR crores), with currency and unit localization across all statements.
- **23-Check QA Engine**: balance sheet balancing, cash flow reconciliation, debt schedule ties, share count consistency, DCF bridge tie-out, WACC validity, terminal growth below WACC, year-one growth plausibility, missing critical inputs, data provenance quality, historical reporting coverage, unit agreement within a model, and — the checks that decide whether a number may be published at all — `inputs_trace_to_a_filing`, `debt_is_actually_sourced`, and `valuation_is_meaningful`. A model with failing checks is still served, with the failures listed. A check that could not run is marked skipped and is never counted as a pass.
- **31-Tab Interactive Excel Exporter**: detail schedules drive the operating model through live Excel formulas (CAPM, FCFF sums, cross-sheet references, sensitivity grids, and live `=IF(...)` audit checks).
- **Live Web Workbench**: scenario switching, driver overrides with revert, methodology breakdown, and a model library kept in the browser.

### Deliberate design decisions

These look like gaps and are not. They are recorded here so nobody "fixes" them.

- **Annual filings only.** SEC ingestion accepts facts from annual forms (`10-K`, `20-F`, `40-F` and their amendments) and keeps only duration facts spanning 330 to 400 days, so 10-Q quarters are never read. A DCF built on annual statements is the institutional standard, and mixing quarters into an annual-period forecast would misstate the growth anchor. Statements six to twelve months old is the correct reading, not staleness.
- **Throttled live ingestion.** `VALENCE_INGEST_CONCURRENCY` defaults to 2. Measured on a single instance: one cached specification costs 1.15 MB resident, so a 50-entry cache is about 58 MB against 512 MB, and a live build costs 2.5 MB over roughly seven seconds. Memory is not the binding constraint. What remains is politeness toward the upstream filing and market-data providers, which rate-limit under concurrency. Raise it alongside a provider measurement, not a memory one.
- **Single-flight builds.** A slug that is being built is not built twice, an unsourceable slug is negatively cached, and the cache is an LRU of 50.
- **Prices self-heal.** A live quote failure falls back to the last cached close *preserving the original date*, and the UI says so rather than presenting a stale number as current.
- **A valuation is published only where a filing is behind it.** Coverage is a sourcing problem, not an engine problem: a company ships if a filing contributed its historicals, and 9 of the 23 shipped models publish while the rest are built but withheld with the reason stated on the page. A model that no filing is behind returns a verdict rather than a number.
- **A DCF below market price is a view, not an error.** `implied_price_deviation_is_explainable` holds a deviation inside a band symmetric in both directions. Negative equity value for a filer with negative book equity is arithmetic, so it is reported as such rather than suppressed.

---

## The gates

Every defect found while building this engine was invisible from the inside. A model
footed to the dollar on a debt figure 15% above the filing, balanced perfectly, passed
every arithmetic check, and was wrong. A statement can tie across every identity and
still be built on an input the issuer never published.

So the loop cannot ask "does it add up" — adding up is a property of the model.
Correctness is a property of the *inputs*, and the only way to know an input is right
is to compare it with something that does not share code with what it audits.

```bash
python scripts/audit_loop.py                 # all seven gates
python scripts/audit_loop.py --only tieout   # one gate
python scripts/audit_loop.py --no-server     # skip the live site gates
```

| # | Gate | Oracle |
| :--- | :--- | :--- |
| 1 | `tieout` | SEC XBRL, plus the filing's own rendered balance sheet for concepts us-gaap does not expose |
| 2 | `excel` | The served API payload, read fresh, against the generated workbook |
| 3 | `identities` | Arithmetic that must hold regardless of inputs |
| 4 | `qa` | A committed baseline, so a NEW failure is distinguishable from a known one |
| 5 | `tests` | pytest and jest |
| 6 | `self_check` | The Excel sheet contract and formula wiring, end to end |
| 7 | `site` | A running server, over HTTP |

Ordered cheapest-and-most-decisive first: a tie-out failure invalidates every figure
downstream, so there is no value in reading a workbook whose inputs are already wrong.
Exit code is non-zero when any gate blocks.

Both taxonomies are read. A foreign private issuer filing a 20-F reports under
`ifrs-full`, and reading only us-gaap reported TSMC's cash as carrying no filed caption
at all — a gate reporting a disagreement that does not exist, which is as damaging as
one that misses a real disagreement.

On current `main`: **tie-out 0 untied figures, 10 of 11 US filers audited clean**
(the eleventh is TSMC, disclosed rather than counted), **QA 0 regressions across 23
models**, **742 backend tests**, and a current-asset reconciliation that lands exactly
on Infosys' filed subtotal in all three years.

---

## System Architecture

```mermaid
flowchart TB
    subgraph Public["0. Public Web Tier (Next.js)"]
        LP[Landing page /]
        IDX[Ticker index /stock]
        TKR["Per-ticker /stock/[slug]"]
        RED["Short form /[ticker] 308"]
        MET[Methodology /methodology]
    end

    subgraph Delivery["1. API Layer (FastAPI)"]
        API[Router]
        THR[Ingest throttle<br/>semaphore, single-flight, negative cache]
        API --> THR
    end

    subgraph Ingestion["2. Ingestion & Storage"]
        A1[SEC EDGAR XBRL<br/>annual forms only]
        A2[Screener.in Excel]
        A3[yfinance market feed]
        Store[(SQLite universe + datapoints)]
        A1 & A2 & A3 --> Store
    end

    subgraph Normalization["3. Taxonomy & Normalization"]
        Mapping[Unified Taxonomy Mapper]
        Canonical[Canonical Registry]
        Derivation[Derived Metrics]
        Slugs[Slug + CIK assignment]
        Store --> Mapping --> Canonical --> Derivation
        Store --> Slugs
    end

    subgraph CoreEngine["4. 3-Statement & Forecast Engine"]
        Hist[Historical Assembly]
        Fcst[5-Year Driver Roll-forward]
        Schedules[Capex, D&A, NWC, Debt, Tax, Shares]
        Derivation --> Hist --> Fcst --> Schedules
    end

    subgraph ValuationQA["5. Valuation & QA Core"]
        WACC[CAPM WACC Module]
        DCF[Unlevered FCFF Engine]
        Reverse[Reverse DCF Solver]
        Comps[Comps & Football Field]
        Returns[PE Returns & IRR]
        QA[23-Check QA Engine]
        Schedules --> WACC & DCF
        DCF --> Reverse & Comps & Returns
        WACC & DCF & Reverse & Comps & Returns --> QA
    end

    subgraph Output["6. Output"]
        XLSX[31-Tab Excel Exporter]
    end

    Public --> API
    THR --> Ingestion
    QA --> API
    QA --> XLSX

    classDef pub fill:#EFF6FF,stroke:#2563EB,color:#0f172a;
    classDef ing fill:#F5F3FF,stroke:#7C3AED,color:#0f172a;
    classDef core fill:#ECFDF5,stroke:#059669,color:#0f172a;
    classDef val fill:#FFFBEB,stroke:#D97706,color:#0f172a;
    classDef out fill:#FFF5F5,stroke:#DC2626,color:#0f172a;
    class LP,IDX,TKR,RED,MET,API,THR pub;
    class A1,A2,A3,Store,Mapping,Canonical,Derivation,Slugs ing;
    class Hist,Fcst,Schedules core;
    class WACC,DCF,Reverse,QA val;
    class XLSX out;
```

---

## Tech Stack

- **Core Engine**: Python 3.12, Pydantic v2
- **API**: FastAPI, Uvicorn, Requests, HTTPX
- **Data**: SQLite, committed per-company model snapshots (`backend/data/cache/*.json`)
- **Excel Renderer**: OpenPyXL (live formulas via OpenXML value patching)
- **Frontend**: Next.js 16 (App Router), React 19, Tailwind CSS v4, TypeScript

Dependencies are declared in `pyproject.toml`, so `pip install -e .` is enough.

---

## Project Structure

```
Valence/
├── backend/
│   ├── api/
│   │   ├── main.py                    # FastAPI app factory
│   │   ├── routes.py                  # Endpoints, slug allowlist, spec build & cache
│   │   ├── throttle.py                # Ingest semaphore, single-flight, negative cache
│   │   └── static/                    # Legacy SPA assets and icon
│   ├── data/
│   │   ├── ingestion/                 # Source-specific parsers
│   │   │   ├── sec_edgar.py           # US SEC XBRL company facts (annual forms only)
│   │   │   ├── screener.py            # India Screener.in Excel parser
│   │   │   ├── india_live.py          # Live India market data
│   │   │   └── us_live.py             # Live US market data
│   │   ├── universe/
│   │   │   ├── models.py              # Raw database schemas
│   │   │   ├── store.py               # SQLite reader/writer, universe queries
│   │   │   ├── slugs.py               # Public slug + CIK assignment
│   │   │   └── master_list.py         # Covered tickers and markets
│   │   ├── pipeline.py                # Ingestion orchestration
│   │   └── precompute.py              # Model cache precomputation
│   ├── export/excel/                  # 31-sheet openpyxl renderer
│   │   ├── builder.py                 # Low-level utilities & OpenXML string patcher
│   │   ├── exporter.py                # Export runner
│   │   ├── render_front.py            # Cover, guide, executive summary, tab manifest
│   │   ├── render_hist.py             # Historical statements
│   │   ├── render_fcst.py             # Operating model and schedules
│   │   ├── render_val.py              # WACC, DCF, comps, football field, returns
│   │   ├── render_qa.py               # Documentation and dynamic QA checks
│   │   ├── self_check.py              # Sheet contract assertions
│   │   └── styles.py                  # Formatting and color tokens
│   ├── forecast/                      # engine, assumptions, debt, share_count
│   ├── models/                        # Pydantic contracts (spec, statements)
│   ├── normalization/                 # taxonomy/ and financials/
│   ├── validation/                    # accounting_checks.py, pipeline.py (CHECK_SUITE)
│   ├── valuation/                     # dcf, wacc, reverse_dcf, comps,
│   │                                  # football_field, returns, sensitivity
│   └── tests/                         # Pytest suite
├── frontend/
│   ├── src/app/
│   │   ├── page.tsx                   # Landing page
│   │   ├── layout.tsx                 # Metadata, tokens, browser surfaces
│   │   ├── stock/page.tsx             # Ticker index
│   │   ├── stock/[ticker]/            # Per-ticker page, share card, JSON-LD
│   │   ├── [ticker]/                  # Short-form redirector
│   │   ├── methodology/page.tsx
│   │   ├── not-found.tsx
│   │   ├── sitemap.ts, robots.ts, manifest.ts
│   │   ├── icon.png, favicon.ico, apple-icon.png
│   ├── src/components/                # Workbench views, modals, landing blocks
│   ├── src/lib/                       # API client, formatters, tickers, site config
│   └── public/media/                  # Launch clip and poster
├── scripts/                           # The launch gates (see The gates below)
│   ├── audit_loop.py                  # Runs all seven gates, prints a verdict
│   ├── tieout.py                      # Every bridge input vs the filing that published it
│   ├── qa_gate.py                     # Plausibility over every covered company, vs a baseline
│   ├── audit_valuation_figures.py     # Served API payload vs the generated workbook
│   └── check_shipped_set.py           # What the site serves vs what is committed
├── data/
│   └── qa_gate_baseline.json          # Recorded failures, so a new one is distinguishable
├── .github/workflows/                 # tests.yml, qa-gate.yml, and two market-data jobs
├── assets/                            # Gitignored: plans, reviews, screenshots, media sources
└── README.md
```

---

## Getting Started

### Prerequisites

- **Python 3.12+**
- **Node.js 20+** (the floor Next.js 16 requires)

There is no `requirements.txt`; the backend's third-party dependencies are:

```bash
pip install fastapi uvicorn pydantic openpyxl requests pdfplumber yfinance
```

`pytest` is needed to run the suite.

### Installation

```bash
git clone https://github.com/karbburn/Valence.git
cd Valence

python -m venv venv
# Windows:  venv\Scripts\activate
# macOS/Linux: source venv/bin/activate
pip install fastapi uvicorn pydantic openpyxl requests pdfplumber yfinance pytest

cd frontend && npm install
```

### Configuration

Optional. Everything below has a working default.

```env
# backend/.env
SEC_CONTACT_EMAIL=you@example.com     # SEC requires a monitored contact in the User-Agent
TWELVEDATA_API_KEY=                   # optional market-data provider
VALENCE_INGEST_CONCURRENCY=2          # in-flight live builds
VALENCE_INGEST_NEGATIVE_TTL=900       # seconds to remember an unsourceable slug
```

```env
# frontend/.env.local
NEXT_PUBLIC_API_URL=http://127.0.0.1:8111
NEXT_PUBLIC_SITE_URL=http://localhost:3000
```

`NEXT_PUBLIC_API_URL` is read at **build** time, not only at runtime. The pages
are prerendered, so a build without it will find no companies to prerender and
the index will render empty.

### Running

Backend:

```bash
python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8111
```

Frontend, in a second terminal:

```bash
cd frontend
npm run dev
```

| Route | What it is |
| :--- | :--- |
| `/` | Landing page |
| `/stock` | Covered tickers, searchable |
| `/stock/NVDA` | A company's model, server-rendered |
| `/NVDA` | Short form, 308s to the canonical URL |
| `/methodology` | How the valuation is built, and what it cannot do |

`/api/*` is proxied from the frontend to `NEXT_PUBLIC_API_URL`, so the browser
never makes a cross-origin request.

### Excel export

```bash
curl -o model.xlsx "http://127.0.0.1:8111/api/export/excel?company_id=nvda_us"
```

---

## Tests

```bash
# The whole launch loop, in one command: seven gates, one verdict
python scripts/audit_loop.py

# Or individually
python -m pytest backend/tests -q                              # 742 tests
python -m backend.export.excel.self_check                      # 31-sheet contract + formula wiring
python -m backend.api.self_check                               # Web API and recomputation
cd frontend && npm test && npx tsc --noEmit && npm run lint && npm run build
```

A commit that touches `backend/` is not finished until the suite passes. The backend
suite takes about ten minutes and, together with the tie-out gate, is the only thing
guarding the engine.

On every push to `main`, CI runs the backend suite, the frontend typecheck/lint/test/build,
and `qa_gate.py` in snapshot mode — offline, over the committed snapshots, against the
committed baseline. The gate fails on a *new* regression, not on the recorded failures,
so a permanently red gate is not a thing anyone learns to ignore.

---

## Core API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Liveness |
| `GET` | `/api/model/{company_id}` | Full `ModelSpecification` JSON |
| `POST` | `/api/model/recompute` | Apply driver overrides, return updated model |
| `POST` | `/api/model/revert` | Revert an override to baseline |
| `GET` | `/api/export/excel` | 31-tab `.xlsx` workbook |
| `GET` | `/api/companies` | Covered companies |
| `GET` | `/api/companies/manifest` | Paged universe with `slug` and `has_model` |
| `GET` | `/api/companies/resolve` | Resolve one public slug to a company |
| `GET` | `/api/companies/search` | Ticker and name autocomplete |

`/api/companies/resolve` is the security boundary for the public page routes.
`/api/model/{company_id}` will attempt live third-party ingestion for any
pattern-valid id, so a page route that passed unknown segments straight through
would let any well-formed URL start an ingestion. Unknown slugs 404 rather than
redirecting somewhere plausible.

Saved models live in the browser (`localStorage`). Nothing is uploaded or
synchronised.

---

## Licensing & Data

Figures come from public filings (SEC EDGAR, NSE annual reports, Screener.in) and
public market-data providers, and **every figure on the site states which of those it
came from** -- a caption the filer itself prints is read from the filing, and one the
filing does not carry is marked as coming from a market feed rather than presented as
filed. Prices refresh daily. Valuation output is model-generated and is not a
recommendation or investment advice.

Known and stated limits, rather than discovered by a reader:

  - 10 of the 12 India models read a market feed rather than a filing, because the NSE
    annual reports have to be obtained and committed; only Infosys reads one today.
  - where a caption is dropped rather than guessed, the reconciliation reports the
    shortfall instead of leaving it to be found.
  - a period has one end date, taken from the filing; market feeds name columns by
    calendar month end and are not authoritative about when a fiscal period closed.

Built by [Sourabh Pradhan](https://www.sourabhpradhan.in/).
