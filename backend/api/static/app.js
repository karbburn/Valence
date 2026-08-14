// Valence Dashboard Application Logic (Single-Page App)

let currentSpec = null;
let currentMode = 'analyst';
let currentScenario = 'base';
let currentCompanyId = 'infy_infy';
let currentFullTab = 'is';

// V1 Driver Controls Config
const DRIVER_CONFIGS = [
    { key: "revenue_growth", label: "Revenue Growth Rate %", unit: "%", min: -10, max: 30, step: 0.5 },
    { key: "ebitda_margin", label: "EBITDA Margin %", unit: "%", min: 10, max: 40, step: 0.5 },
    { key: "ebit_margin", label: "Operating Margin (EBIT) %", unit: "%", min: 10, max: 35, step: 0.5 },
    { key: "da_pct_revenue", label: "D&A % Revenue", unit: "%", min: 0.5, max: 10, step: 0.1 },
    { key: "tax_rate", label: "Effective Tax Rate %", unit: "%", min: 15, max: 35, step: 0.5 },
    { key: "dso_days", label: "DSO (Days)", unit: "days", min: 30, max: 180, step: 1 },
    { key: "dpo_days", label: "DPO (Days)", unit: "days", min: 5, max: 60, step: 1 },
    { key: "capex_pct_revenue", label: "Capex % Revenue", unit: "%", min: 0.5, max: 15, step: 0.1 },
    { key: "wacc.cost_of_equity", label: "Cost of Equity (CAPM) %", unit: "%", min: 8, max: 20, step: 0.25 },
    { key: "terminal_growth_rate", label: "Terminal Growth Rate %", unit: "%", min: 1, max: 8, step: 0.25 },
    { key: "exit_ev_multiple", label: "Exit EV/EBITDA Multiple", unit: "x", min: 5, max: 40, step: 0.5 },
];

document.addEventListener("DOMContentLoaded", () => {
    loadCompanySelector();
    fetchModelSpec('infy_infy');

    // Close search dropdown on click outside
    document.addEventListener("click", (e) => {
        const searchBox = document.getElementById("company-search-input");
        const drop = document.getElementById("search-dropdown");
        if (searchBox && drop && !searchBox.contains(e.target) && !drop.contains(e.target)) {
            drop.classList.add("hidden");
        }
    });
});

function getCurrencySymbol() {
    if (!currentSpec || !currentSpec.metadata) return "₹";
    return currentSpec.metadata.currency === "USD" ? "$" : "₹";
}

function getCurrencyUnit() {
    if (!currentSpec || !currentSpec.metadata) return "INR Cr";
    return currentSpec.metadata.currency === "USD" ? "USD M" : "INR Cr";
}

async function loadCompanySelector() {
    try {
        const res = await fetch('/api/companies');
        const list = await res.json();
        const select = document.getElementById("company-select");
        if (select && list.length > 0) {
            select.innerHTML = list.map(c => 
                `<option value="${c.company_id}">${c.ticker} — ${c.name} (${c.market === 'us' ? 'US' : 'India'})</option>`
            ).join('');
            select.value = currentCompanyId;
        }
    } catch (err) {
        console.error("Failed to load universe companies:", err);
    }
}

async function handleSearchInput(query) {
    const drop = document.getElementById("search-dropdown");
    if (!query || query.trim().length === 0) {
        drop.classList.add("hidden");
        return;
    }

    try {
        const res = await fetch(`/api/companies/search?q=${encodeURIComponent(query)}&limit=10`);
        const results = await res.json();
        if (!results || results.length === 0) {
            drop.innerHTML = `<div class="p-3 text-xs text-slate-400 font-medium">No matching companies found</div>`;
        } else {
            drop.innerHTML = results.map(c => `
                <div onclick="selectCompanyFromSearch('${c.company_id}', '${c.ticker}', '${c.name.replace(/'/g, "\\'")}')" class="px-3.5 py-2.5 hover:bg-slate-800 cursor-pointer flex items-center justify-between text-xs border-b border-slate-800/80 last:border-0 search-result-item">
                    <div class="flex items-center gap-2">
                        <span class="font-extrabold text-white text-xs font-mono bg-slate-800 px-1.5 py-0.5 rounded border border-slate-700">${c.ticker}</span>
                        <span class="text-slate-200 font-semibold text-xs truncate max-w-[150px]">${c.name}</span>
                    </div>
                    <span class="px-2 py-0.5 rounded text-[10px] font-mono font-bold ${c.market === 'us' ? 'ticker-badge-us' : 'ticker-badge-india'}">${c.market.toUpperCase()}</span>
                </div>
            `).join('');
        }
        drop.classList.remove("hidden");
    } catch (err) {
        console.error("Search failed:", err);
    }
}

function handleSearchFocus() {
    const input = document.getElementById("company-search-input");
    if (input && input.value.trim().length > 0) {
        handleSearchInput(input.value);
    }
}

function selectCompanyFromSearch(companyId, ticker, name) {
    document.getElementById("search-dropdown").classList.add("hidden");
    document.getElementById("company-search-input").value = "";
    
    const select = document.getElementById("company-select");
    if (select) {
        let opt = select.querySelector(`option[value="${companyId}"]`);
        if (!opt) {
            opt = document.createElement("option");
            opt.value = companyId;
            opt.textContent = `${ticker || companyId} — ${name || 'Search Result'}`;
            select.appendChild(opt);
        }
        select.value = companyId;
    }
    fetchModelSpec(companyId);
}

async function fetchModelSpec(companyId = currentCompanyId) {
    try {
        currentCompanyId = companyId;
        const select = document.getElementById("company-select");
        if (select) select.value = companyId;

        const exportBtn = document.getElementById("excel-export-btn");
        if (exportBtn) {
            exportBtn.href = `/api/export/excel?company_id=${companyId}`;
        }
        const res = await fetch(`/api/model/${companyId}`);
        currentSpec = await res.json();
        renderDashboard();
    } catch (err) {
        console.error("Failed to load model specification:", err);
    }
}

async function handleCompanyChange(companyId) {
    await fetchModelSpec(companyId);
}

function renderDashboard() {
    if (!currentSpec) return;

    const sym = getCurrencySymbol();
    const unit = getCurrencyUnit();

    // 1. Render Header & Metadata
    document.getElementById("company-name").innerText = currentSpec.metadata.name.toUpperCase();
    document.getElementById("ticker-badge").innerText = `${currentSpec.metadata.market.toUpperCase()}: ${currentSpec.metadata.ticker} (${currentSpec.metadata.currency})`;

    // Forecast Unit Label
    const fUnitLabel = document.getElementById("forecast-unit-label");
    if (fUnitLabel) fUnitLabel.innerText = `FY27 – FY31 (${unit})`;

    // 2. Render Top KPI Bar
    renderKPIs();

    // 3. Render QA Status Badge
    renderQABadge();

    // 4. Render Active View Mode
    if (currentMode === 'analyst') {
        renderAnalystView();
    } else if (currentMode === 'quick') {
        renderQuickView();
    } else if (currentMode === 'full') {
        renderFullView();
    }
}

function renderKPIs() {
    const val = getValuationForScenario(currentScenario);
    if (!val) return;

    const sym = getCurrencySymbol();
    const bridge = val.dcf_bridge || {};
    const wacc = val.wacc || {};
    const tv = val.terminal_value || {};
    const revDcf = val.reverse_dcf || {};

    const mktPrice = revDcf.market_price || 1650.0;
    const price = bridge.implied_share_price || 0.0;
    const upside = mktPrice > 0 ? ((price - mktPrice) / mktPrice * 100.0) : 0.0;

    document.getElementById("kpi-market-price").innerText = `${sym}${mktPrice.toFixed(2)}`;
    document.getElementById("kpi-implied-price").innerText = `${sym}${price.toFixed(2)}`;

    const upsideBadge = document.getElementById("kpi-upside-badge");
    upsideBadge.innerText = `${upside >= 0 ? '+' : ''}${upside.toFixed(1)}% Upside`;
    upsideBadge.className = `text-xs font-semibold mt-1 ${upside >= 0 ? 'text-emerald-400' : 'text-rose-400'}`;

    document.getElementById("kpi-ev").innerText = `${sym}${(bridge.enterprise_value || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
    document.getElementById("kpi-equity-value").innerText = `${sym}${(bridge.equity_value || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
    document.getElementById("kpi-wacc").innerText = `${(wacc.wacc || 12.95).toFixed(2)}%`;
    document.getElementById("kpi-term-growth").innerText = `${(tv.terminal_growth_rate || 4.0).toFixed(2)}%`;

    const waccSub = document.getElementById("wacc-source-sub");
    if (waccSub && wacc.source_notes) {
        waccSub.innerText = wacc.source_notes.split('(')[0] || "CAPM Cost of Equity";
    }

    // DCF Bridge Cards
    document.getElementById("bridge-pv-fcff").innerText = `${sym}${(bridge.sum_pv_fcff || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
    document.getElementById("bridge-pv-tv").innerText = `${sym}${(bridge.pv_terminal_value || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
    document.getElementById("bridge-net-cash").innerText = `${(bridge.less_net_debt || 0) < 0 ? '+' : ''}${sym}${Math.abs(bridge.less_net_debt || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
    document.getElementById("bridge-price").innerText = `${sym}${price.toFixed(2)}`;
}

function renderQABadge() {
    const qa = currentSpec.qa || {};
    const label = qa.summary_label || "MODEL VALID";
    const passed = qa.all_passed !== false;

    const badge = document.getElementById("qa-badge");
    const labelSpan = document.getElementById("qa-label");

    labelSpan.innerText = label;
    if (passed) {
        badge.className = "px-3 py-1 rounded-full text-xs font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5 cursor-pointer hover:bg-emerald-500/20 transition-all";
    } else {
        badge.className = "px-3 py-1 rounded-full text-xs font-bold bg-rose-500/10 text-rose-400 border border-rose-500/30 flex items-center gap-1.5 cursor-pointer animate-pulse hover:bg-rose-500/20 transition-all";
    }
}

function openQAModal() {
    const modal = document.getElementById("qa-modal");
    const listDiv = document.getElementById("qa-checks-list");
    modal.classList.remove("hidden");

    const qa = currentSpec.qa || {};
    const checks = qa.checks || [];

    if (checks.length === 0) {
        listDiv.innerHTML = `<div class="p-3 text-slate-400">No QA check records available.</div>`;
        return;
    }

    listDiv.innerHTML = checks.map(c => `
        <div class="bg-slate-950 p-3 rounded-lg border border-slate-800 flex items-start justify-between">
            <div class="space-y-1">
                <div class="font-semibold text-slate-200">${c.name}</div>
                <div class="text-[11px] text-slate-400">${c.description}</div>
                ${c.implicated_keys && c.implicated_keys.length > 0 ? `<div class="text-[10px] text-slate-500 font-mono">Implicated: ${c.implicated_keys.join(', ')}</div>` : ''}
            </div>
            <span class="px-2 py-0.5 rounded text-[10px] font-bold ${c.passed ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' : 'bg-rose-950 text-rose-300 border border-rose-800'}">
                ${c.passed ? 'PASS' : 'FAIL'}
            </span>
        </div>
    `).join('');
}

function closeQAModal() {
    document.getElementById("qa-modal").classList.add("hidden");
}

function renderAnalystView() {
    // Render Drivers Control List
    const container = document.getElementById("drivers-container");
    container.innerHTML = "";

    const scenarioAssumptions = (currentSpec.assumptions || []).filter(a => a.scenario === currentScenario);

    DRIVER_CONFIGS.forEach(cfg => {
        const ass = scenarioAssumptions.find(a => a.driver_key === cfg.key) || { value: 0, type: 'model_generated' };
        const val = ass.value;
        const isOverride = ass.type === "user_override";

        const div = document.createElement("div");
        div.className = "bg-slate-950 p-3.5 rounded-lg border border-slate-800 space-y-2";

        div.innerHTML = `
            <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                    <label class="text-xs font-semibold text-slate-200">${cfg.label}</label>
                    ${isOverride ? '<span class="badge-override">Analyst Override</span>' : ''}
                </div>
                <div class="flex items-center gap-2">
                    <input type="number" class="driver-input" value="${val.toFixed(2)}" step="${cfg.step}" onchange="handleDriverInput('${cfg.key}', this.value)">
                    ${isOverride ? `<button onclick="handleRevert('${cfg.key}')" class="text-xs text-rose-400 hover:text-rose-300 font-semibold">Revert</button>` : ''}
                </div>
            </div>
            <input type="range" class="w-full" min="${cfg.min}" max="${cfg.max}" step="${cfg.step}" value="${val}" oninput="handleDriverInput('${cfg.key}', this.value)">
        `;

        container.appendChild(div);
    });

    // Render Forecast Preview Table
    renderForecastTable();
}

function renderForecastTable() {
    const tbody = document.getElementById("forecast-table-body");
    tbody.innerHTML = "";

    const sym = getCurrencySymbol();
    const periods = ["FY27", "FY28", "FY29", "FY30", "FY31"];
    const rows = [
        { key: "canonical.is.revenue", label: "Revenue from Operations" },
        { key: "canonical.is.ebitda", label: "EBITDA" },
        { key: "canonical.is.operating_profit", label: "Operating Profit (EBIT)" },
        { key: "canonical.is.net_profit", label: "Net Profit After Tax" },
        { key: "canonical.cf.operating_activities", label: "Operating Cash Flow" },
    ];

    rows.forEach(r => {
        const tr = document.createElement("tr");
        let html = `<td class="px-3 py-2 font-medium text-slate-300">${r.label}</td>`;

        periods.forEach(p => {
            const val = getForecastVal(r.key, p, currentScenario);
            html += `<td class="px-3 py-2 text-right font-mono text-slate-200">${sym}${val.toLocaleString('en-US', { maximumFractionDigits: 0 })}</td>`;
        });

        tr.innerHTML = html;
        tbody.appendChild(tr);
    });
}

function renderQuickView() {
    const val = getValuationForScenario(currentScenario);
    if (!val) return;
    const sym = getCurrencySymbol();
    const price = (val.dcf_bridge || {}).implied_share_price || 0.0;
    const revDcf = val.reverse_dcf || {};

    document.getElementById("quick-company-title").innerText = `${currentSpec.metadata.name} — Quick DCF Summary`;
    document.getElementById("quick-price").innerText = `${sym}${price.toFixed(2)}`;
    document.getElementById("quick-mkt-price").innerText = `${sym}${(revDcf.market_price || 1650.0).toFixed(2)}`;
    document.getElementById("quick-wacc").innerText = `${(val.wacc.wacc || 12.95).toFixed(2)}%`;
    document.getElementById("quick-g").innerText = `${(val.terminal_value.terminal_growth_rate || 4.0).toFixed(2)}%`;
    document.getElementById("quick-implied-g").innerText = revDcf.implied_terminal_growth ? `${revDcf.implied_terminal_growth.toFixed(2)}%` : "N/A";
}

function switchFullTab(tab) {
    currentFullTab = tab;
    ['is', 'bs', 'cf'].forEach(t => {
        const btn = document.getElementById(`tab-${t}`);
        if (btn) {
            btn.className = t === tab 
                ? "px-3 py-1.5 rounded-lg bg-indigo-600 text-white font-semibold"
                : "px-3 py-1.5 rounded-lg bg-slate-800 text-slate-400 hover:text-slate-200";
        }
    });
    renderFullView();
}

function renderFullView() {
    const container = document.getElementById("full-schedules-container");
    const sym = getCurrencySymbol();
    const periods = ["FY27", "FY28", "FY29", "FY30", "FY31"];

    let rows = [];
    if (currentFullTab === 'is') {
        rows = [
            { key: "canonical.is.revenue", label: "Revenue from Operations" },
            { key: "canonical.is.cost_of_sales", label: "Cost of Goods & Services Sold" },
            { key: "canonical.is.gross_profit", label: "Gross Profit" },
            { key: "canonical.is.operating_expenses", label: "Operating Expenses" },
            { key: "canonical.is.ebitda", label: "EBITDA" },
            { key: "canonical.is.depreciation_amortization", label: "Depreciation & Amortization" },
            { key: "canonical.is.operating_profit", label: "Operating Profit (EBIT)" },
            { key: "canonical.is.pbt", label: "Profit Before Tax (PBT)" },
            { key: "canonical.is.tax", label: "Provision for Taxes" },
            { key: "canonical.is.net_profit", label: "Net Profit After Tax (PAT)" },
        ];
    } else if (currentFullTab === 'bs') {
        rows = [
            { key: "canonical.bs.share_capital", label: "Share Capital" },
            { key: "canonical.bs.reserves", label: "Reserves & Surplus" },
            { key: "canonical.bs.total_equity", label: "Total Shareholders' Equity" },
            { key: "canonical.bs.borrowings", label: "Total Borrowings (Debt)" },
            { key: "canonical.bs.net_fixed_assets", label: "Net Property, Plant & Equipment" },
            { key: "canonical.bs.working_capital", label: "Net Working Capital" },
            { key: "canonical.bs.cash_and_equivalents", label: "Cash & Cash Equivalents" },
        ];
    } else if (currentFullTab === 'cf') {
        rows = [
            { key: "canonical.cf.operating_activities", label: "Cash Flow from Operating Activities (CFO)" },
            { key: "canonical.cf.capex", label: "Capital Expenditures (Capex)" },
            { key: "canonical.cf.investing_activities", label: "Cash Flow from Investing Activities (CFI)" },
            { key: "canonical.cf.financing_activities", label: "Cash Flow from Financing Activities (CFF)" },
            { key: "canonical.cf.net_cash_flow", label: "Net Increase / (Decrease) in Cash" },
        ];
    }

    let html = `
        <table class="w-full text-xs text-left text-slate-300">
            <thead class="text-xs uppercase bg-slate-950 text-slate-400 border-b border-slate-800">
                <tr>
                    <th class="px-4 py-3">Line Item</th>
                    ${periods.map(p => `<th class="px-4 py-3 text-right">${p}</th>`).join('')}
                </tr>
            </thead>
            <tbody class="divide-y divide-slate-800/50">
    `;

    rows.forEach(r => {
        html += `<tr class="hover:bg-slate-950/50"><td class="px-4 py-2.5 font-medium text-slate-200">${r.label}</td>`;
        periods.forEach(p => {
            const val = getForecastVal(r.key, p, currentScenario);
            html += `<td class="px-4 py-2.5 text-right font-mono text-slate-200">${sym}${val.toLocaleString('en-US', { maximumFractionDigits: 0 })}</td>`;
        });
        html += `</tr>`;
    });

    html += `</tbody></table>`;
    container.innerHTML = html;
}

async function handleDriverInput(driverKey, newValue) {
    try {
        const res = await fetch(`/api/model/recompute?company_id=${currentCompanyId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                driver_key: driverKey,
                value: parseFloat(newValue),
                period: "FY27",
                scenario: currentScenario,
            })
        });

        currentSpec = await res.json();
        renderDashboard();
        showToast(`Driver ${driverKey} updated`);
    } catch (err) {
        console.error("Recomputation failed:", err);
    }
}

async function handleRevert(driverKey) {
    try {
        const res = await fetch(`/api/model/revert?company_id=${currentCompanyId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                driver_key: driverKey,
                period: "FY27",
                scenario: currentScenario,
            })
        });

        currentSpec = await res.json();
        renderDashboard();
        showToast(`Driver ${driverKey} reverted`);
    } catch (err) {
        console.error("Revert failed:", err);
    }
}

function switchMode(mode) {
    currentMode = mode;

    document.querySelectorAll(".mode-btn").forEach(b => {
        b.className = "mode-btn px-4 py-1.5 rounded-md text-slate-400 hover:text-white transition-all";
    });
    document.getElementById(`mode-${mode}`).className = "mode-btn px-4 py-1.5 rounded-md transition-all bg-indigo-600 text-white shadow";

    document.getElementById("view-analyst").classList.toggle("hidden", mode !== "analyst");
    document.getElementById("view-quick").classList.toggle("hidden", mode !== "quick");
    document.getElementById("view-full").classList.toggle("hidden", mode !== "full");

    renderDashboard();
}

function switchScenario(scen) {
    currentScenario = scen;

    document.querySelectorAll(".scen-btn").forEach(b => {
        b.className = "scen-btn px-3 py-1 rounded text-slate-400 hover:text-slate-200";
    });
    document.getElementById(`scen-${scen}`).className = "scen-btn px-3 py-1 rounded text-slate-300 bg-slate-800 font-semibold";

    renderDashboard();
}

function getValuationForScenario(scen) {
    if (!currentSpec || !currentSpec.valuation) return null;
    return currentSpec.valuation.find(v => v.scenario === scen) || currentSpec.valuation[0];
}

function getForecastVal(ckey, period, scen) {
    if (!currentSpec || !currentSpec.forecast || !currentSpec.forecast.line_items) return 0;
    const item = currentSpec.forecast.line_items.find(i => i.canonical_key === ckey && i.period_label === period && i.scenario === scen);
    return item ? item.value : 0;
}

function showToast(message) {
    const toast = document.getElementById("toast");
    const msgSpan = document.getElementById("toast-message");
    if (!toast || !msgSpan) return;

    msgSpan.innerText = message;
    toast.classList.remove("hidden");
    setTimeout(() => {
        toast.classList.add("hidden");
    }, 2500);
}

// ------------------------------------------------------------------ #
// Model Persistence Functions
// ------------------------------------------------------------------ #

async function saveCurrentModel() {
    if (!currentSpec) return;
    const name = prompt("Enter a name for this model scenario set:", `${currentSpec.metadata.name} Valuation`);
    if (!name) return;

    try {
        const res = await fetch("/api/models/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: name, company_id: currentCompanyId })
        });
        const data = await res.json();
        showToast(`Model "${data.header.name}" saved!`);
    } catch (err) {
        console.error("Failed to save model:", err);
        alert("Error saving model.");
    }
}

async function openSavedModelsModal() {
    document.getElementById("saved-models-modal").classList.remove("hidden");
    await loadSavedModelsList();
}

function closeSavedModelsModal() {
    document.getElementById("saved-models-modal").classList.add("hidden");
}

async function loadSavedModelsList() {
    const listDiv = document.getElementById("saved-models-list");
    listDiv.innerHTML = `<div class="text-xs text-slate-400">Loading saved models...</div>`;

    try {
        const res = await fetch("/api/models");
        const models = await res.json();

        if (!models || models.length === 0) {
            listDiv.innerHTML = `<div class="text-xs text-slate-500 py-4 text-center">No saved models found. Click "Save" to persist your edits.</div>`;
            return;
        }

        listDiv.innerHTML = "";
        models.forEach(m => {
            const item = document.createElement("div");
            item.className = "bg-slate-950 p-3.5 rounded-lg border border-slate-800 flex items-center justify-between";
            item.innerHTML = `
                <div>
                    <div class="text-sm font-semibold text-slate-200">${m.name}</div>
                    <div class="text-xs text-slate-500">Version ${m.model_version} • Saved ${new Date(m.updated_at).toLocaleString()}</div>
                </div>
                <div class="flex items-center gap-2">
                    <button onclick="loadSavedModel('${m.model_id}')" class="px-3 py-1 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded">Load</button>
                    <button onclick="deleteSavedModel('${m.model_id}')" class="px-2.5 py-1 bg-rose-950/60 hover:bg-rose-900 text-rose-300 text-xs font-semibold rounded border border-rose-800">Delete</button>
                </div>
            `;
            listDiv.appendChild(item);
        });
    } catch (err) {
        console.error("Failed to list saved models:", err);
        listDiv.innerHTML = `<div class="text-xs text-rose-400">Failed to load saved models list.</div>`;
    }
}

async function loadSavedModel(modelId) {
    try {
        const res = await fetch(`/api/models/${modelId}`);
        currentSpec = await res.json();
        currentCompanyId = currentSpec.metadata.company_id || currentCompanyId;
        renderDashboard();
        closeSavedModelsModal();
        showToast("Model loaded");
    } catch (err) {
        console.error("Failed to load model:", err);
        alert("Error loading model.");
    }
}

async function deleteSavedModel(modelId) {
    if (!confirm("Are you sure you want to delete this saved model?")) return;
    try {
        await fetch(`/api/models/${modelId}`, { method: "DELETE" });
        await loadSavedModelsList();
        showToast("Model deleted");
    } catch (err) {
        console.error("Failed to delete model:", err);
        alert("Error deleting model.");
    }
}
