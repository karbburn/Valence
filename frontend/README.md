# Valence Frontend — Institutional Valuation Terminal

Next.js 16 App Router application implementing the Valence financial modeling interface with real-time valuation updates, 3-statement financial schedules, and DCF analysis.

---

## 🛠 Tech Stack

- **Framework**: Next.js 16 (App Router)
- **Language**: TypeScript (Strict mode, zero `any` types)
- **Styling**: Tailwind CSS with custom CSS variables & theme tokens
- **Icons**: `lucide-react`
- **Typography**: Inter (UI labels) + JetBrains Mono (financial data with global `tabular-nums`)
- **Accent Palette**: Teal (`#0ea5e9`) & Light Cyan (`#7dd3fc`)

---

## 🏛 Architecture & Layout

### 1. View Modes
- **Analyst Mode (`1`)**: 12-column grid featuring interactive driver sliders and flat CAPM WACC breakdown in the left pane (4 cols), alongside a 5-period FCFF DCF valuation schedule with subtotal bridges and a 5-year forecast summary table in the right pane (8 cols).
- **Quick DCF Mode (`2`)**: Executive overview with hero intrinsic share price, benchmark market quote, upside/downside percentage trend, key CAPM/growth parameters, and a 2-way WACC x Terminal Growth (g) sensitivity matrix.
- **Full 3-Statement Mode (`3`)**: Complete 12-period model with tabbed navigation for Income Statement, Balance Sheet, and Cash Flow Statement, featuring distinct audited historical (`H`) and explicit forecast (`F`) columns separated by vertical demarcations.

### 2. Interactive Systems & Modals
- **Company Search (`CompanySearch.tsx`)**: Debounced multi-market lookup (US SEC EDGAR & India NSE) with status badges (`INSTANT` precomputed vs `LIVE` build) and keyboard navigation (`ArrowDown`, `ArrowUp`, `Enter`, `Escape`).
- **QA Consistency Audit (`QAModal.tsx`)**: Inspects automated balance sheet balancing, NOPAT derivation, and growth rate validity checks.
- **Model Persistence (`SaveModal.tsx` & `SavedModelsModal.tsx`)**: Replaces native browser prompts and confirms with accessible modal dialogs and inline deletion verification.
- **Mobile Viewport Guard (`MobileGuard.tsx`)**: Enforces institutional desktop viewport standards (900px minimum).

### 3. Global Keyboard Shortcuts (`useKeyboardShortcuts.ts`)
- **`Ctrl+S` / `Cmd+S`**: Open Save Model modal.
- **`1` / `2` / `3`**: Switch between Analyst, Quick DCF, and 3-Statement modes.
- **`ArrowLeft` / `ArrowRight`**: Navigate between Base, Bull, and Bear scenarios.
- **`Escape`**: Dismiss open modal or company search dropdown.

---

## 🚀 Getting Started

### 1. Install Dependencies
```bash
cd frontend
npm install
```

### 2. Run Local Development Server
```bash
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) in your browser. API requests to `/api/*` are automatically proxied to FastAPI on `http://localhost:8000/api/*`.

### 3. Type Checking & Production Build
```bash
# Type check without emitting files
npx tsc --noEmit

# Production build
npm run build
```

---

## 📋 Design System Constraints & Anti-Patterns

Valence enforces strict institutional aesthetic standards:
- **No Indigo/Violet Accents**: Only `#0ea5e9` (Teal) is permitted.
- **No Gradients or Glows**: Flat backgrounds, subtle 1px border delimitations.
- **No Rounded-XL / Rounded-Full on Data Cells**: Cards use `rounded-[4px]`, modals use `rounded-[6px]`.
- **No Emoji or Decorative Icons**: Institutional iconography only.
- **Numeric Precision**: All numbers formatted with `fmtNum`, `fmtMoney`, or `fmtPct` using JetBrains Mono with tabular numbers.
