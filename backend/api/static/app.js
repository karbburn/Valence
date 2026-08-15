// Valence Dashboard — Rebuilt for usability

let currentSpec = null;
let currentMode = 'analyst';
let currentScenario = 'base';
let currentCompanyId = 'infy_infy';
let currentFullTab = 'is';
let isLoading = false;

const DRIVER_CONFIGS = [
    { key: "revenue_growth",      label: "Revenue Growth %",       unit: "%",    min: -5,  max: 30,  step: 0.5 },
    { key: "ebitda_margin",       label: "EBITDA Margin %",        unit: "%",    min: 5,   max: 45,  step: 0.5 },
    { key: "ebit_margin",         label: "EBIT / Operating Margin %", unit: "%", min: 5,   max: 40,  step: 0.5 },
    { key: "da_pct_revenue",      label: "D&A % Revenue",          unit: "%",    min: 0.5, max: 15,  step: 0.1 },
    { key: "tax_rate",            label: "Effective Tax Rate %",   unit: "%",    min: 10,  max: 40,  step: 0.5 },
    { key: "capex_pct_revenue",   label: "CapEx % Revenue",        unit: "%",    min: 0.5, max: 20,  step: 0.1 },
    { key: "dso_days",            label: "DSO (Days Receivable)",  unit: "days", min: 20,  max: 200, step: 1   },
    { key: "dpo_days",            label: "DPO (Days Payable)",     unit: "days", min: 5,   max: 90,  step: 1   },
    { key: "wacc.cost_of_equity", label: "Cost of Equity (CAPM) %", unit: "%",  min: 6,   max: 22,  step: 0.25 },
    { key: "terminal_growth_rate",label: "Terminal Growth Rate %", unit: "%",    min: 0.5, max: 7,   step: 0.25 },
    { key: "exit_ev_multiple",    label: "Exit EV/EBITDA Multiple",unit: "x",   min: 5,   max: 45,  step: 0.5 },
];

document.addEventListener("DOMContentLoaded", () => {
    loadCompanySelector();
    fetchModelSpec('infy_infy');
    document.addEventListener("click", e => {
        const searchBox = document.getElementById("company-search-input");
        const drop = document.getElementById("search-dropdown");
        if (searchBox && drop && !searchBox.contains(e.target) && !drop.contains(e.target)) {
            drop.classList.add("hidden");
        }
    });
});

// ── Currency helpers ──────────────────────────────────────────────────────────
function getCurrencySymbol() {
    if (!currentSpec?.metadata) return "₹";
    return currentSpec.metadata.currency === "USD" ? "$" : "₹";
}
function getCurrencyUnit() {
    if (!currentSpec?.metadata) return "INR Cr";
    return currentSpec.metadata.currency === "USD" ? "USD M" : "INR Cr";
}
function fmtNum(val, decimals = 0) {
    if (val == null || isNaN(val)) return "—";
    return val.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}
function fmtMoney(val) {
    if (val == null || isNaN(val)) return "—";
    const sym = getCurrencySymbol();
    const abs = Math.abs(val);
    const sign = val < 0 ? "-" : "";
    if (currentSpec?.metadata?.currency === "USD") {
        if (abs >= 1e6) return `${sign}${sym}${(abs / 1e6).toFixed(2)}T`;
        if (abs >= 1e3) return `${sign}${sym}${(abs / 1e3).toFixed(1)}B`;
        return `${sign}${sym}${fmtNum(abs)}M`;
    }
    // INR Crores
    if (abs >= 1e5) return `${sign}${sym}${(abs / 1e5).toFixed(2)}L Cr`;
    return `${sign}${sym}${fmtNum(abs)} Cr`;
}

// ── Company selector ──────────────────────────────────────────────────────────
async function loadCompanySelector() {
    try {
        const res = await fetch('/api/companies');
        const list = await res.json();
        const select = document.getElementById("company-select");
        if (select && list.length > 0) {
            select.innerHTML = list.map(c => {
                const mkt = c.market === 'us' ? 'US' : 'India';
                return `<option value="${c.company_id}">${c.ticker} — ${c.name} (${mkt})</option>`;
            }).join('');
            select.value = currentCompanyId;
        }
    } catch (err) {
        console.error("Failed to load company list:", err);
    }
}

async function handleSearchInput(query) {
    const drop = document.getElementById("search-dropdown");
    if (!query?.trim()) { drop.classList.add("hidden"); return; }
    try {
        const res = await fetch(`/api/companies/search?q=${encodeURIComponent(query)}&limit=12`);
        const results = await res.json();
        if (!results?.length) {
            drop.innerHTML = `<div class="px-4 py-3 text-xs text-slate-400">No matching companies</div>`;
        } else {
            drop.innerHTML = results.map(c => {
                const mktClass = c.market === 'us' ? 'bg-blue-900/60 text-blue-300 border-blue-700' : 'bg-orange-900/60 text-orange-300 border-orange-700';
                const statusDot = c.onboarding_status === 'onboarded' ? '🟢' : '🔴';
                return `<div onclick="selectCompanyFromSearch('${c.company_id}','${c.ticker}','${c.name.replace(/'/g,"\\'")}','${c.market}')"
                    class="px-4 py-2.5 hover:bg-slate-800 cursor-pointer flex items-center justify-between text-xs border-b border-slate-800 last:border-0">
                    <div class="flex items-center gap-2.5">
                        <span class="font-bold text-white font-mono bg-slate-800 px-2 py-0.5 rounded border border-slate-700">${c.ticker}</span>
                        <div>
                            <div class="text-slate-100 font-semibold truncate max-w-[160px]">${c.name}</div>
                            <div class="text-slate-500 text-[10px]">${c.sector || ''}</div>
                        </div>
                    </div>
                    <div class="flex items-center gap-1.5">
                        <span class="text-[9px] font-bold ${statusDot === '🔴' ? 'text-slate-500' : 'text-emerald-400'}">${c.onboarding_status === 'onboarded' ? 'READY' : 'PENDING'}</span>
                        <span class="px-1.5 py-0.5 rounded text-[10px] font-bold border ${mktClass}">${c.market.toUpperCase()}</span>
                    </div>
                </div>`;
            }).join('');
        }
        drop.classList.remove("hidden");
    } catch (err) { console.error("Search failed:", err); }
}

function handleSearchFocus() {
    const input = document.getElementById("company-search-input");
    if (input?.value?.trim()) handleSearchInput(input.value);
}

function selectCompanyFromSearch(companyId, ticker, name, market) {
    document.getElementById("search-dropdown").classList.add("hidden");
    document.getElementById("company-search-input").value = "";
    const select = document.getElementById("company-select");
    if (select) {
        let opt = select.querySelector(`option[value="${companyId}"]`);
        if (!opt) {
            opt = document.createElement("option");
            opt.value = companyId;
            opt.textContent = `${ticker} — ${name} (${market === 'us' ? 'US' : 'India'})`;
            select.appendChild(opt);
        }
        select.value = companyId;
    }
    fetchModelSpec(companyId);
}

async function handleCompanyChange(companyId) {
    await fetchModelSpec(companyId);
}

// ── Model fetching ────────────────────────────────────────────────────────────
function setLoadingState(loading) {
    isLoading = loading;
    const overlay = document.getElementById("loading-overlay");
    if (overlay) overlay.classList.toggle("hidden", !loading);
}

async function fetchModelSpec(companyId = currentCompanyId) {
    setLoadingState(true);
    try {
        currentCompanyId = companyId;
        const select = document.getElementById("company-select");
        if (select) select.value = companyId;
        const exportBtn = document.getElementById("excel-export-btn");
        if (exportBtn) exportBtn.href = `/api/export/excel?company_id=${companyId}`;

        const res = await fetch(`/api/model/${companyId}`);
        if (!res.ok) {
            showError(`Failed to load model for ${companyId} (${res.status})`);
            return;
        }
        currentSpec = await res.json();
        renderDashboard();
    } catch (err) {
        showError(`Network error: ${err.message}`);
    } finally {
        setLoadingState(false);
    }
}

function showError(msg) {
    const el = document.getElementById("error-banner");
    const txt = document.getElementById("error-banner-text");
    if (el && txt) {
        txt.textContent = msg;
        el.classList.remove("hidden");
        setTimeout(() => el.classList.add("hidden"), 5000);
    }
}

// ── Dashboard render ──────────────────────────────────────────────────────────
function renderDashboard() {
    if (!currentSpec) return;
    const unit = getCurrencyUnit();

    document.getElementById("company-name").innerText = currentSpec.metadata.name.toUpperCase();
    document.getElementById("ticker-badge").innerText = `${currentSpec.metadata.market?.toUpperCase()}: ${currentSpec.metadata.ticker} (${currentSpec.metadata.currency})`;

    const fUnitLabel = document.getElementById("forecast-unit-label");
    if (fUnitLabel) fUnitLabel.innerText = `FY27 – FY31 (${unit})`;

    renderKPIs();
    renderQABadge();

    if (currentMode === 'analyst') renderAnalystView();
    else if (currentMode === 'quick') renderQuickView();
    else if (currentMode === 'full') renderFullView();
}

function renderKPIs() {
    const val = getValuationForScenario(currentScenario);
    if (!val) return;

    const sym = getCurrencySymbol();
    const bridge = val.dcf_bridge || {};
    const wacc = val.wacc || {};
    const tv = val.terminal_value || {};
    const revDcf = val.reverse_dcf || {};

    const mktPrice = revDcf.market_price || 0.0;
    const price = bridge.implied_share_price || 0.0;
    const upside = mktPrice > 0 ? ((price - mktPrice) / mktPrice * 100.0) : 0.0;

    document.getElementById("kpi-market-price").innerText = mktPrice > 0 ? `${sym}${fmtNum(mktPrice, 2)}` : "—";
    document.getElementById("kpi-implied-price").innerText = `${sym}${fmtNum(price, 2)}`;

    const upsideBadge = document.getElementById("kpi-upside-badge");
    upsideBadge.innerText = mktPrice > 0 ? `${upside >= 0 ? '+' : ''}${upside.toFixed(1)}% vs Market` : "Market price N/A";
    upsideBadge.className = `text-xs font-semibold mt-1 ${upside >= 0 ? 'text-emerald-400' : 'text-rose-400'}`;

    // EV & Equity Value — formatted with proper units
    document.getElementById("kpi-ev").innerText = fmtMoney(bridge.enterprise_value);
    document.getElementById("kpi-equity-value").innerText = fmtMoney(bridge.equity_value);
    document.getElementById("kpi-wacc").innerText = `${(wacc.wacc || 0).toFixed(2)}%`;
    document.getElementById("kpi-term-growth").innerText = `${(tv.terminal_growth_rate || 4.0).toFixed(2)}%`;

    // Net debt/cash label
    const netDebt = bridge.less_net_debt || 0;
    const netDebtEl = document.getElementById("kpi-net-debt");
    if (netDebtEl) {
        netDebtEl.innerText = netDebt < 0
            ? `Net Cash: ${fmtMoney(Math.abs(netDebt))}`
            : `Net Debt: ${fmtMoney(netDebt)}`;
        netDebtEl.className = `text-xs font-semibold mt-1 ${netDebt < 0 ? 'text-emerald-400' : 'text-rose-400'}`;
    }

    const waccSub = document.getElementById("wacc-source-sub");
    if (waccSub && wacc.source_notes) {
        waccSub.innerText = wacc.source_notes.split('(')[0]?.trim() || "CAPM";
    }

    // DCF Bridge Cards
    document.getElementById("bridge-pv-fcff").innerText = fmtMoney(bridge.sum_pv_fcff);
    document.getElementById("bridge-pv-tv").innerText = fmtMoney(bridge.pv_terminal_value);
    const tvPct = tv.tv_pct_of_ev || 0;
    const tvPctEl = document.getElementById("bridge-tv-pct");
    if (tvPctEl) tvPctEl.innerText = `${tvPct.toFixed(1)}% of EV`;
    document.getElementById("bridge-net-cash").innerText = netDebt < 0
        ? `+ ${fmtMoney(Math.abs(netDebt))}`
        : `- ${fmtMoney(netDebt)}`;
    document.getElementById("bridge-net-cash").className = `font-mono font-bold text-sm ${netDebt < 0 ? 'text-emerald-400' : 'text-rose-400'}`;
    document.getElementById("bridge-price").innerText = `${sym}${fmtNum(price, 2)}`;
}

function renderQABadge() {
    const qa = currentSpec.qa || {};
    const checks = qa.checks || [];
    const allPassed = checks.length > 0 && checks.every(c => c.passed);
    const failedCount = checks.filter(c => !c.passed).length;

    const badge = document.getElementById("qa-badge");
    const labelSpan = document.getElementById("qa-label");

    if (checks.length === 0) {
        labelSpan.innerText = "QA NOT RUN";
        badge.className = "px-3 py-1 rounded-full text-xs font-bold bg-slate-700/50 text-slate-400 border border-slate-600 flex items-center gap-1.5 cursor-pointer";
    } else if (allPassed) {
        labelSpan.innerText = "MODEL VALID";
        badge.className = "px-3 py-1 rounded-full text-xs font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5 cursor-pointer hover:bg-emerald-500/20 transition-all";
    } else {
        labelSpan.innerText = `${failedCount} CHECK${failedCount > 1 ? 'S' : ''} FAILED`;
        badge.className = "px-3 py-1 rounded-full text-xs font-bold bg-rose-500/10 text-rose-400 border border-rose-500/30 flex items-center gap-1.5 cursor-pointer hover:bg-rose-500/20 transition-all animate-pulse";
    }
}

function openQAModal() {
    const modal = document.getElementById("qa-modal");
    const listDiv = document.getElementById("qa-checks-list");
    modal.classList.remove("hidden");
    const checks = (currentSpec?.qa?.checks) || [];
    if (checks.length === 0) {
        listDiv.innerHTML = `<div class="p-3 text-slate-400 text-center">No QA records.</div>`;
        return;
    }
    listDiv.innerHTML = checks.map(c => `
        <div class="bg-slate-950 p-3 rounded-lg border border-slate-800 flex items-start justify-between gap-3">
            <div class="space-y-1 flex-1">
                <div class="font-semibold text-slate-100 text-xs">${c.check_name}</div>
                ${c.detail ? `<div class="text-[11px] text-slate-400">${c.detail}</div>` : ''}
            </div>
            <span class="px-2 py-1 rounded text-[10px] font-bold shrink-0 ${c.passed ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' : 'bg-rose-950 text-rose-300 border border-rose-800'}">
                ${c.passed ? 'PASS' : 'FAIL'}
            </span>
        </div>
    `).join('');
}
function closeQAModal() { document.getElementById("qa-modal").classList.add("hidden"); }

// ── Analyst View ──────────────────────────────────────────────────────────────
function renderAnalystView() {
    renderDrivers();
    renderForecastTable();
    renderDCFSchedule();
    renderWACCCard();
}

function renderDrivers() {
    const container = document.getElementById("drivers-container");
    container.innerHTML = "";
    const scenAssumptions = (currentSpec.assumptions || []).filter(a => a.scenario === currentScenario);

    DRIVER_CONFIGS.forEach(cfg => {
        const ass = scenAssumptions.find(a => a.driver_key === cfg.key) || { value: 0, type: 'model_generated' };
        const val = ass.value ?? 0;
        const isOverride = ass.type === "user_override";

        const div = document.createElement("div");
        div.className = `driver-row ${isOverride ? 'ring-1 ring-indigo-500/40' : ''}`;
        div.innerHTML = `
            <div class="flex items-center justify-between mb-1.5">
                <div class="flex items-center gap-1.5">
                    <label class="text-xs font-semibold text-slate-200">${cfg.label}</label>
                    ${isOverride ? '<span class="text-[9px] font-bold text-indigo-300 bg-indigo-900/60 px-1.5 py-0.5 rounded border border-indigo-700 uppercase tracking-wide">Override</span>' : ''}
                </div>
                <div class="flex items-center gap-2">
                    <span class="text-xs font-mono text-slate-400 w-14 text-right" id="drv-val-${cfg.key}">${val.toFixed(cfg.unit === 'days' ? 0 : 2)}${cfg.unit === '%' ? '%' : cfg.unit === 'x' ? 'x' : 'd'}</span>
                    ${isOverride ? `<button onclick="handleRevert('${cfg.key}')" class="text-[10px] text-rose-400 hover:text-rose-300 font-bold">↺ Revert</button>` : ''}
                </div>
            </div>
            <input type="range" class="driver-slider" min="${cfg.min}" max="${cfg.max}" step="${cfg.step}" value="${val}"
                oninput="updateDriverDisplay('${cfg.key}', this.value, '${cfg.unit}')"
                onchange="handleDriverInput('${cfg.key}', this.value)">
            <div class="flex justify-between text-[9px] text-slate-600 mt-0.5">
                <span>${cfg.min}${cfg.unit === '%' ? '%' : ''}</span><span>${cfg.max}${cfg.unit === '%' ? '%' : ''}</span>
            </div>
        `;
        container.appendChild(div);
    });
}

function updateDriverDisplay(key, value, unit) {
    const el = document.getElementById(`drv-val-${key}`);
    if (!el) return;
    const num = parseFloat(value);
    el.innerText = `${unit === 'days' ? Math.round(num) : num.toFixed(2)}${unit === '%' ? '%' : unit === 'x' ? 'x' : 'd'}`;
}

function renderForecastTable() {
    const tbody = document.getElementById("forecast-table-body");
    if (!tbody) return;
    tbody.innerHTML = "";
    const sym = getCurrencySymbol();
    const periods = ["FY27", "FY28", "FY29", "FY30", "FY31"];
    const rows = [
        { key: "canonical.is.revenue",              label: "Revenue",          bold: true  },
        { key: "canonical.is.ebitda",               label: "EBITDA",           bold: false },
        { key: "canonical.is.operating_profit",     label: "EBIT",             bold: false },
        { key: "canonical.is.net_profit",           label: "Net Profit (PAT)", bold: true  },
        { key: "canonical.is.depreciation_amortization", label: "D&A",        bold: false },
        { key: "canonical.cf.capex",                label: "CapEx",            bold: false, negate: true },
        { key: "canonical.cf.operating_activities", label: "Operating CF",     bold: false },
    ];

    rows.forEach(r => {
        const tr = document.createElement("tr");
        tr.className = r.bold ? "bg-slate-900/40" : "";
        let html = `<td class="px-3 py-2 ${r.bold ? 'font-bold text-slate-100' : 'font-medium text-slate-300'} text-xs">${r.label}</td>`;
        periods.forEach(p => {
            let val = getForecastVal(r.key, p, currentScenario);
            if (r.negate && val) val = Math.abs(val);
            html += `<td class="px-3 py-2 text-right font-mono text-xs ${r.bold ? 'text-white font-bold' : 'text-slate-200'}">${sym}${fmtNum(val)}</td>`;
        });
        tr.innerHTML = html;
        tbody.appendChild(tr);
    });
}

function renderDCFSchedule() {
    const container = document.getElementById("dcf-schedule-container");
    if (!container) return;
    const val = getValuationForScenario(currentScenario);
    if (!val) { container.innerHTML = '<div class="text-slate-500 text-xs p-2">No valuation data</div>'; return; }

    const sym = getCurrencySymbol();
    const fcffs = val.fcff_by_period || [];
    const bridge = val.dcf_bridge || {};
    const tv = val.terminal_value || {};
    const wacc = val.wacc || {};

    const rows = [
        { label: "EBIT (Operating Profit)", fn: p => fmtNum(p.ebit) },
        { label: "Tax Rate %",              fn: p => `${(p.tax_rate || 0).toFixed(1)}%` },
        { label: "NOPAT",                   fn: p => fmtNum(p.nopat),    bold: true },
        { label: "+ D&A",                   fn: p => fmtNum(p.da) },
        { label: "− CapEx",                 fn: p => `(${fmtNum(Math.abs(p.capex))})` },
        { label: "± ΔNWC",                  fn: p => fmtNum(-(p.delta_working_capital || 0)) },
        { label: "= FCFF",                  fn: p => fmtNum(p.fcff),     bold: true, total: true },
        { label: "Discount Factor",         fn: p => (p.discount_factor || 0).toFixed(4) },
        { label: "PV(FCFF)",                fn: p => fmtNum(p.pv_fcff),  bold: true },
    ];

    let html = `<table class="w-full text-xs">
        <thead>
            <tr class="border-b border-slate-700">
                <th class="px-3 py-2 text-left text-slate-400 font-semibold">DCF Line Item</th>
                ${fcffs.map(p => `<th class="px-3 py-2 text-right text-slate-400 font-semibold">${p.period}</th>`).join('')}
            </tr>
        </thead>
        <tbody class="divide-y divide-slate-800/40">`;

    rows.forEach(r => {
        const rowClass = r.total ? 'bg-indigo-950/30 border-t border-indigo-800/40' : '';
        const textClass = r.bold ? 'font-bold text-slate-100' : 'text-slate-300';
        html += `<tr class="${rowClass} hover:bg-slate-800/30">
            <td class="px-3 py-2 ${textClass} font-mono text-[11px]">${r.label}</td>
            ${fcffs.map(p => `<td class="px-3 py-2 text-right font-mono ${textClass} text-[11px]">${r.fn(p)}</td>`).join('')}
        </tr>`;
    });

    // TV & Bridge summary
    html += `<tr class="border-t-2 border-slate-600 bg-slate-900/60">
        <td class="px-3 py-2 text-slate-400 text-[11px] font-semibold">Σ PV(FCFF)</td>
        <td colspan="${fcffs.length}" class="px-3 py-2 text-right font-mono font-bold text-slate-200 text-[11px]">${sym}${fmtNum(bridge.sum_pv_fcff)}</td>
    </tr>
    <tr class="bg-slate-900/60">
        <td class="px-3 py-2 text-slate-400 text-[11px]">+ PV Terminal Value (${(tv.terminal_growth_rate || 4).toFixed(1)}% g, ${(tv.tv_pct_of_ev || 0).toFixed(0)}% of EV)</td>
        <td colspan="${fcffs.length}" class="px-3 py-2 text-right font-mono font-bold text-slate-200 text-[11px]">${sym}${fmtNum(bridge.pv_terminal_value)}</td>
    </tr>
    <tr class="bg-indigo-950/30">
        <td class="px-3 py-2 text-indigo-300 font-bold text-[11px]">Enterprise Value (EV)</td>
        <td colspan="${fcffs.length}" class="px-3 py-2 text-right font-mono font-bold text-indigo-300 text-[11px]">${sym}${fmtNum(bridge.enterprise_value)}</td>
    </tr>
    <tr class="bg-slate-900/60">
        <td class="px-3 py-2 text-slate-400 text-[11px]">${(bridge.less_net_debt || 0) < 0 ? '+ Net Cash' : '− Net Debt'}</td>
        <td colspan="${fcffs.length}" class="px-3 py-2 text-right font-mono text-[11px] ${(bridge.less_net_debt || 0) < 0 ? 'text-emerald-400' : 'text-rose-400'}">${(bridge.less_net_debt || 0) < 0 ? sym : '-'+sym}${fmtNum(Math.abs(bridge.less_net_debt || 0))}</td>
    </tr>
    <tr class="bg-emerald-950/20 border-t border-emerald-800/30">
        <td class="px-3 py-2 text-emerald-300 font-bold text-[11px]">Equity Value → Implied Price</td>
        <td colspan="${fcffs.length}" class="px-3 py-2 text-right font-mono font-bold text-emerald-300 text-[11px]">${sym}${fmtNum(bridge.equity_value)} → ${sym}${fmtNum(bridge.implied_share_price, 2)} / share</td>
    </tr>
    </tbody></table>
    <div class="mt-3 px-3 py-2 bg-slate-800/40 rounded-lg text-[11px] text-slate-400">
        <span class="font-semibold text-slate-300">WACC: ${(wacc.wacc || 0).toFixed(2)}%</span>
        &nbsp;·&nbsp; Ke: ${(wacc.cost_of_equity || 0).toFixed(2)}%
        &nbsp;·&nbsp; Kd(AT): ${(wacc.cost_of_debt || 0).toFixed(2)}%
        &nbsp;·&nbsp; Eq Wt: ${((wacc.equity_weight || 0) * 100).toFixed(1)}%
        &nbsp;·&nbsp; Debt: ${sym}${fmtNum(bridge.less_net_debt || 0)} (net)
    </div>`;

    container.innerHTML = html;
}

function renderWACCCard() {
    const container = document.getElementById("wacc-detail-container");
    if (!container) return;
    const val = getValuationForScenario(currentScenario);
    if (!val) return;
    const w = val.wacc || {};
    container.innerHTML = `
        <div class="grid grid-cols-3 gap-2 text-xs">
            <div class="bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                <div class="text-slate-500 mb-1">Risk-Free Rate</div>
                <div class="font-bold text-slate-100 font-mono">${(w.risk_free_rate || 0).toFixed(2)}%</div>
            </div>
            <div class="bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                <div class="text-slate-500 mb-1">Beta</div>
                <div class="font-bold text-slate-100 font-mono">${(w.beta || 0).toFixed(2)}</div>
            </div>
            <div class="bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                <div class="text-slate-500 mb-1">Equity Risk Premium</div>
                <div class="font-bold text-slate-100 font-mono">${(w.equity_risk_premium || 0).toFixed(2)}%</div>
            </div>
            <div class="bg-indigo-950/40 p-2.5 rounded-lg border border-indigo-800/50">
                <div class="text-indigo-400 mb-1">Cost of Equity (CAPM)</div>
                <div class="font-bold text-indigo-300 font-mono">${(w.cost_of_equity || 0).toFixed(2)}%</div>
            </div>
            <div class="bg-slate-950 p-2.5 rounded-lg border border-slate-800">
                <div class="text-slate-500 mb-1">Pre-tax Kd</div>
                <div class="font-bold text-slate-100 font-mono">${(w.pre_tax_cost_of_debt || 0).toFixed(2)}%</div>
            </div>
            <div class="bg-indigo-950/40 p-2.5 rounded-lg border border-indigo-800/50 col-span-1">
                <div class="text-indigo-400 mb-1">WACC</div>
                <div class="font-bold text-2xl text-indigo-300 font-mono">${(w.wacc || 0).toFixed(2)}%</div>
            </div>
        </div>`;
}

// ── Full 3-Statement View ─────────────────────────────────────────────────────
function switchFullTab(tab) {
    currentFullTab = tab;
    ['is', 'bs', 'cf'].forEach(t => {
        const btn = document.getElementById(`tab-${t}`);
        if (btn) btn.className = t === tab
            ? "px-3 py-1.5 rounded-lg bg-indigo-600 text-white font-semibold text-xs"
            : "px-3 py-1.5 rounded-lg bg-slate-800 text-slate-400 hover:text-slate-200 text-xs";
    });
    renderFullView();
}

function renderFullView() {
    const container = document.getElementById("full-schedules-container");
    const sym = getCurrencySymbol();
    const unit = getCurrencyUnit();
    const periods = ["FY24", "FY25", "FY26", "FY27", "FY28", "FY29", "FY30", "FY31"];
    const histPeriods = ["FY24", "FY25", "FY26"];
    const fcastPeriods = ["FY27", "FY28", "FY29", "FY30", "FY31"];

    let rows = [];
    if (currentFullTab === 'is') {
        rows = [
            { key: "canonical.is.revenue",                    label: "Revenue",               bold: true  },
            { key: "canonical.is.cost_of_sales",              label: "Cost of Sales",         bold: false },
            { key: "canonical.is.gross_profit",               label: "Gross Profit",          bold: true  },
            { key: "canonical.is.ebitda",                     label: "EBITDA",                bold: true  },
            { key: "canonical.is.depreciation_amortization",  label: "D&A",                   bold: false },
            { key: "canonical.is.operating_profit",           label: "EBIT (Operating Profit)",bold: true  },
            { key: "canonical.is.pbt",                        label: "PBT",                   bold: false },
            { key: "canonical.is.tax",                        label: "Tax Provision",         bold: false },
            { key: "canonical.is.net_profit",                 label: "Net Profit (PAT)",      bold: true  },
        ];
    } else if (currentFullTab === 'bs') {
        rows = [
            { key: "canonical.bs.borrowings",         label: "Total Debt / Borrowings",  bold: false },
            { key: "canonical.bs.cash_and_bank",      label: "Cash & Bank Balances",     bold: false },
            { key: "canonical.bs.trade_receivables",  label: "Trade Receivables",        bold: false },
            { key: "canonical.bs.inventory",          label: "Inventory",                bold: false },
            { key: "canonical.bs.trade_payables",     label: "Trade Payables",           bold: false },
            { key: "canonical.bs.ppe",                label: "PPE / Net Block",          bold: false },
            { key: "canonical.bs.total_equity",       label: "Shareholders' Equity",     bold: true  },
        ];
    } else {
        rows = [
            { key: "canonical.cf.operating_activities",  label: "Cash from Operations (CFO)",   bold: true  },
            { key: "canonical.cf.capex",                 label: "Capital Expenditure (CapEx)",   bold: false, negate: true },
            { key: "canonical.cf.investing_activities",  label: "Cash from Investing (CFI)",     bold: false },
            { key: "canonical.cf.financing_activities",  label: "Cash from Financing (CFF)",     bold: false },
        ];
    }

    let html = `<div class="text-[10px] text-slate-500 mb-2 px-1">All values in <span class="font-semibold text-slate-400">${unit}</span> · FY24–FY26 Historical · FY27–FY31 Forecast (${currentScenario})</div>
        <table class="w-full text-xs text-left">
            <thead>
                <tr class="border-b border-slate-700">
                    <th class="px-3 py-2.5 text-slate-400 font-semibold w-56">Line Item</th>
                    ${histPeriods.map(p => `<th class="px-3 py-2.5 text-right text-slate-500 font-semibold">${p} <span class="text-[9px] text-slate-600">H</span></th>`).join('')}
                    ${fcastPeriods.map(p => `<th class="px-3 py-2.5 text-right text-indigo-400/70 font-semibold">${p} <span class="text-[9px] text-indigo-600">F</span></th>`).join('')}
                </tr>
            </thead>
            <tbody class="divide-y divide-slate-800/50">`;

    rows.forEach(r => {
        html += `<tr class="${r.bold ? 'bg-slate-900/30 font-bold' : ''} hover:bg-slate-800/30">
            <td class="px-3 py-2 ${r.bold ? 'text-slate-100 font-bold' : 'text-slate-300 font-medium'}">${r.label}</td>`;

        histPeriods.forEach(p => {
            let val = getHistoricalVal(r.key, p);
            if (r.negate && val) val = Math.abs(val);
            html += `<td class="px-3 py-2 text-right font-mono ${r.bold ? 'text-slate-100 font-bold' : 'text-slate-400'}">${val != null ? sym + fmtNum(val) : '—'}</td>`;
        });
        fcastPeriods.forEach(p => {
            let val = getForecastVal(r.key, p, currentScenario);
            if (r.negate && val) val = Math.abs(val);
            html += `<td class="px-3 py-2 text-right font-mono ${r.bold ? 'text-indigo-200 font-bold' : 'text-slate-300'}">${val != null && val !== 0 ? sym + fmtNum(val) : '—'}</td>`;
        });
        html += `</tr>`;
    });

    html += `</tbody></table>`;
    container.innerHTML = html;
}

// ── Quick View ────────────────────────────────────────────────────────────────
function renderQuickView() {
    const val = getValuationForScenario(currentScenario);
    if (!val) return;
    const sym = getCurrencySymbol();
    const price = (val.dcf_bridge || {}).implied_share_price || 0.0;
    const mktPrice = (val.reverse_dcf || {}).market_price || 0.0;
    const upside = mktPrice > 0 ? ((price - mktPrice) / mktPrice * 100) : null;

    document.getElementById("quick-company-title").innerText = `${currentSpec.metadata.name}`;
    document.getElementById("quick-price").innerText = `${sym}${fmtNum(price, 2)}`;
    document.getElementById("quick-mkt-price").innerText = mktPrice > 0 ? `${sym}${fmtNum(mktPrice, 2)}` : "N/A";
    document.getElementById("quick-upside").innerText = upside != null ? `${upside >= 0 ? '+' : ''}${upside.toFixed(1)}%` : "—";
    document.getElementById("quick-upside").className = `text-3xl font-extrabold font-mono ${upside != null && upside >= 0 ? 'text-emerald-400' : 'text-rose-400'}`;

    document.getElementById("quick-wacc").innerText = `${((val.wacc || {}).wacc || 0).toFixed(2)}%`;
    document.getElementById("quick-g").innerText = `${((val.terminal_value || {}).terminal_growth_rate || 4).toFixed(2)}%`;
    const impliedG = (val.reverse_dcf || {}).implied_terminal_growth;
    document.getElementById("quick-implied-g").innerText = impliedG != null ? `${impliedG.toFixed(2)}%` : "N/A";

    // Sensitivity table
    const sensEl = document.getElementById("quick-sens-table");
    if (sensEl && val.sensitivity_tables?.length > 0) {
        const tbl = val.sensitivity_tables[0];
        const rowVals = tbl.row_values || [];
        const colVals = tbl.col_values || [];
        const grid = tbl.results_grid || [];
        const baseWacc = (val.wacc || {}).wacc || 0;
        const baseTg = (val.terminal_value || {}).terminal_growth_rate || 4;

        let html = `<div class="text-[10px] text-slate-500 mb-2">WACC (rows) vs Terminal Growth % (cols) — Implied Share Price</div>
        <table class="w-full text-[11px] border-collapse">
            <thead><tr>
                <th class="px-2 py-1 text-left text-slate-500">WACC \\ g</th>
                ${colVals.map(g => `<th class="px-2 py-1 text-right text-slate-400 ${Math.abs(g - baseTg) < 0.01 ? 'text-indigo-400 font-bold' : ''}">${g.toFixed(1)}%</th>`).join('')}
            </tr></thead>
            <tbody>`;
        rowVals.forEach((w, ri) => {
            const isBaseRow = Math.abs(w - baseWacc) < 0.1;
            html += `<tr class="${isBaseRow ? 'bg-indigo-950/30' : 'hover:bg-slate-800/30'}">
                <td class="px-2 py-1 font-mono text-slate-400 ${isBaseRow ? 'text-indigo-400 font-bold' : ''}">${w.toFixed(1)}%</td>
                ${(grid[ri] || []).map((v, ci) => {
                    const isBaseCell = isBaseRow && Math.abs(colVals[ci] - baseTg) < 0.01;
                    const upside = mktPrice > 0 && v ? ((v - mktPrice) / mktPrice * 100) : null;
                    const cellClass = isBaseCell ? 'bg-indigo-600/30 text-indigo-200 font-bold' :
                        (upside == null ? 'text-slate-400' : upside > 10 ? 'text-emerald-400' : upside > 0 ? 'text-slate-200' : 'text-rose-400');
                    return `<td class="px-2 py-1 text-right font-mono ${cellClass}">${v ? sym + fmtNum(v, 0) : '—'}</td>`;
                }).join('')}
            </tr>`;
        });
        html += `</tbody></table>`;
        sensEl.innerHTML = html;
    }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function getValuationForScenario(scen) {
    if (!currentSpec?.valuation) return null;
    return currentSpec.valuation.find(v => v.scenario === scen) || currentSpec.valuation[0];
}

function getForecastVal(ckey, period, scen) {
    if (!currentSpec?.forecast?.line_items) return null;
    const item = currentSpec.forecast.line_items.find(i =>
        i.canonical_key === ckey && i.period_label === period && i.scenario === scen);
    return item ? item.value : null;
}

function getHistoricalVal(ckey, period) {
    if (!currentSpec?.historicals?.line_items) return null;
    const item = currentSpec.historicals.line_items.find(i =>
        i.canonical_key === ckey && i.period_label === period);
    return item ? item.value : null;
}

// ── Driver interactions ───────────────────────────────────────────────────────
let _driverDebounceTimer = null;

async function handleDriverInput(driverKey, newValue) {
    clearTimeout(_driverDebounceTimer);
    _driverDebounceTimer = setTimeout(async () => {
        try {
            const res = await fetch(`/api/model/recompute?company_id=${currentCompanyId}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ driver_key: driverKey, value: parseFloat(newValue), period: "FY27", scenario: currentScenario })
            });
            currentSpec = await res.json();
            renderDashboard();
            showToast(`${driverKey} → ${parseFloat(newValue).toFixed(2)}`);
        } catch (err) { showError(`Recompute failed: ${err.message}`); }
    }, 300);
}

async function handleRevert(driverKey) {
    try {
        const res = await fetch(`/api/model/revert?company_id=${currentCompanyId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ driver_key: driverKey, period: "FY27", scenario: currentScenario })
        });
        currentSpec = await res.json();
        renderDashboard();
        showToast(`${driverKey} reverted`);
    } catch (err) { showError(`Revert failed: ${err.message}`); }
}

// ── Mode/Scenario switches ────────────────────────────────────────────────────
function switchMode(mode) {
    currentMode = mode;
    document.querySelectorAll(".mode-btn").forEach(b => {
        b.className = "mode-btn px-4 py-1.5 rounded-md text-slate-400 hover:text-white transition-all text-xs font-medium";
    });
    document.getElementById(`mode-${mode}`).className = "mode-btn px-4 py-1.5 rounded-md transition-all bg-indigo-600 text-white shadow text-xs font-medium";

    document.getElementById("view-analyst").classList.toggle("hidden", mode !== "analyst");
    document.getElementById("view-quick").classList.toggle("hidden", mode !== "quick");
    document.getElementById("view-full").classList.toggle("hidden", mode !== "full");

    renderDashboard();
}

function switchScenario(scen) {
    currentScenario = scen;
    document.querySelectorAll(".scen-btn").forEach(b => {
        b.className = "scen-btn px-3 py-1 rounded text-slate-400 hover:text-slate-200 text-xs";
    });
    document.getElementById(`scen-${scen}`).className = "scen-btn px-3 py-1 rounded text-slate-100 bg-slate-700 font-bold text-xs";
    renderDashboard();
}

// ── Toast & utils ─────────────────────────────────────────────────────────────
function showToast(message, type = 'success') {
    const toast = document.getElementById("toast");
    const msgSpan = document.getElementById("toast-message");
    if (!toast || !msgSpan) return;
    msgSpan.innerText = message;
    toast.classList.remove("hidden");
    setTimeout(() => toast.classList.add("hidden"), 2500);
}

// ── Model Persistence ─────────────────────────────────────────────────────────
async function saveCurrentModel() {
    if (!currentSpec) return;
    const name = prompt("Save model as:", `${currentSpec.metadata.name} – ${new Date().toLocaleDateString()}`);
    if (!name) return;
    try {
        const res = await fetch("/api/models/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, company_id: currentCompanyId })
        });
        const data = await res.json();
        showToast(`Saved: "${data.header?.name || name}"`);
    } catch (err) { showError("Save failed"); }
}

async function openSavedModelsModal() {
    document.getElementById("saved-models-modal").classList.remove("hidden");
    await loadSavedModelsList();
}
function closeSavedModelsModal() { document.getElementById("saved-models-modal").classList.add("hidden"); }

async function loadSavedModelsList() {
    const listDiv = document.getElementById("saved-models-list");
    listDiv.innerHTML = `<div class="text-xs text-slate-400 text-center py-4">Loading...</div>`;
    try {
        const res = await fetch("/api/models");
        const models = await res.json();
        if (!models?.length) {
            listDiv.innerHTML = `<div class="text-xs text-slate-500 py-6 text-center">No saved models yet.</div>`;
            return;
        }
        listDiv.innerHTML = "";
        models.forEach(m => {
            const item = document.createElement("div");
            item.className = "bg-slate-950 p-3.5 rounded-lg border border-slate-800 flex items-center justify-between";
            item.innerHTML = `
                <div>
                    <div class="text-sm font-semibold text-slate-100">${m.name}</div>
                    <div class="text-xs text-slate-500">v${m.model_version} · ${new Date(m.updated_at).toLocaleString()}</div>
                </div>
                <div class="flex items-center gap-2">
                    <button onclick="loadSavedModel('${m.model_id}')" class="px-3 py-1 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded">Load</button>
                    <button onclick="deleteSavedModel('${m.model_id}')" class="px-2.5 py-1 bg-rose-950/60 hover:bg-rose-900 text-rose-300 text-xs font-semibold rounded border border-rose-800">Del</button>
                </div>`;
            listDiv.appendChild(item);
        });
    } catch (err) { listDiv.innerHTML = `<div class="text-xs text-rose-400 text-center py-4">Failed to load</div>`; }
}

async function loadSavedModel(modelId) {
    try {
        const res = await fetch(`/api/models/${modelId}`);
        currentSpec = await res.json();
        currentCompanyId = currentSpec.metadata?.company_id || currentCompanyId;
        renderDashboard();
        closeSavedModelsModal();
        showToast("Model loaded");
    } catch (err) { showError("Load failed"); }
}

async function deleteSavedModel(modelId) {
    if (!confirm("Delete this model?")) return;
    try {
        await fetch(`/api/models/${modelId}`, { method: "DELETE" });
        await loadSavedModelsList();
        showToast("Model deleted");
    } catch (err) { showError("Delete failed"); }
}
