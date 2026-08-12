// Valence Dashboard Application Logic (Single-Page App)

let currentSpec = null;
let currentMode = 'analyst';
let currentScenario = 'base';

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

let currentCompanyId = 'infy_infy';

document.addEventListener("DOMContentLoaded", () => {
    fetchModelSpec('infy_infy');
});

async function fetchModelSpec(companyId = currentCompanyId) {
    try {
        currentCompanyId = companyId;
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

    // 1. Render Header & Metadata
    document.getElementById("company-name").innerText = currentSpec.metadata.name.toUpperCase();
    document.getElementById("ticker-badge").innerText = `${currentSpec.metadata.market.toUpperCase()}: ${currentSpec.metadata.ticker} (${currentSpec.metadata.currency})`;

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

    const bridge = val.dcf_bridge || {};
    const wacc = val.wacc || {};
    const tv = val.terminal_value || {};
    const revDcf = val.reverse_dcf || {};

    const mktPrice = revDcf.market_price || 1650.0;
    const price = bridge.implied_share_price || 0.0;
    const upside = mktPrice > 0 ? ((price - mktPrice) / mktPrice * 100.0) : 0.0;

    document.getElementById("kpi-market-price").innerText = `₹${mktPrice.toFixed(2)}`;
    document.getElementById("kpi-implied-price").innerText = `₹${price.toFixed(2)}`;

    const upsideBadge = document.getElementById("kpi-upside-badge");
    upsideBadge.innerText = `${upside >= 0 ? '+' : ''}${upside.toFixed(1)}% Upside`;
    upsideBadge.className = `text-xs font-semibold mt-1 ${upside >= 0 ? 'text-emerald-400' : 'text-rose-400'}`;

    document.getElementById("kpi-ev").innerText = `₹${(bridge.enterprise_value || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr`;
    document.getElementById("kpi-equity-value").innerText = `₹${(bridge.equity_value || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr`;
    document.getElementById("kpi-wacc").innerText = `${(wacc.wacc || 12.95).toFixed(2)}%`;
    document.getElementById("kpi-term-growth").innerText = `${(tv.terminal_growth_rate || 4.0).toFixed(2)}%`;

    // DCF Bridge Cards
    document.getElementById("bridge-pv-fcff").innerText = `₹${(bridge.sum_pv_fcff || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr`;
    document.getElementById("bridge-pv-tv").innerText = `₹${(bridge.pv_terminal_value || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr`;
    document.getElementById("bridge-net-cash").innerText = `${(bridge.less_net_debt || 0) < 0 ? '+' : ''}₹${Math.abs(bridge.less_net_debt || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr`;
    document.getElementById("bridge-price").innerText = `₹${price.toFixed(2)}`;
}

function renderQABadge() {
    const qa = currentSpec.qa || {};
    const label = qa.summary_label || "MODEL VALID";
    const passed = qa.all_passed !== false;

    const badge = document.getElementById("qa-badge");
    const labelSpan = document.getElementById("qa-label");

    labelSpan.innerText = label;
    if (passed) {
        badge.className = "px-3 py-1 rounded-full text-xs font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5 cursor-pointer";
    } else {
        badge.className = "px-3 py-1 rounded-full text-xs font-bold bg-rose-500/10 text-rose-400 border border-rose-500/30 flex items-center gap-1.5 cursor-pointer animate-pulse";
    }
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
            html += `<td class="px-3 py-2 text-right font-mono text-slate-200">₹${val.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</td>`;
        });

        tr.innerHTML = html;
        tbody.appendChild(tr);
    });
}

function renderQuickView() {
    const val = getValuationForScenario(currentScenario);
    if (!val) return;
    const price = (val.dcf_bridge || {}).implied_share_price || 0.0;
    document.getElementById("quick-price").innerText = `₹${price.toFixed(2)}`;
}

function renderFullView() {
    const container = document.getElementById("full-schedules-container");
    container.innerHTML = `
        <div class="p-4 bg-slate-950 rounded-lg border border-slate-800 text-sm text-slate-300">
            Full Schedule Mode active: Comprehensive visibility over Income Statement, Balance Sheet, Cash Flow, Working Capital, Tax, Debt, and Share Count schedules. All 23 sheets accessible in Excel export.
        </div>
    `;
}

async function handleDriverInput(driverKey, newValue) {
    try {
        const res = await fetch("/api/model/recompute", {
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
    } catch (err) {
        console.error("Recomputation failed:", err);
    }
}

async function handleRevert(driverKey) {
    try {
        const res = await fetch("/api/model/revert", {
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

// ------------------------------------------------------------------ //
// Stage 11 Model Persistence Functions
// ------------------------------------------------------------------ //

async function saveCurrentModel() {
    if (!currentSpec) return;
    const name = prompt("Enter a name for this model scenario set:", `${currentSpec.metadata.name} Valuation`);
    if (!name) return;

    try {
        const res = await fetch("/api/models/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: name, company_id: "infy_infy" })
        });
        const data = await res.json();
        alert(`Model "${data.header.name}" saved successfully!`);
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
            listDiv.innerHTML = `<div class="text-xs text-slate-500 py-4 text-center">No saved models found. Click "Save Model" to persist your edits.</div>`;
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
        renderDashboard();
        closeSavedModelsModal();
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
    } catch (err) {
        console.error("Failed to delete model:", err);
        alert("Error deleting model.");
    }
}

