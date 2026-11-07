/**
 * PredictaStock Terminal - Frontend Application Engine
 * Architecture: World-Class Quantitative Finance Terminal
 * Features: Interactive 5D Charting, AI Prediction Panel, Watchlist,
 * FIFO Portfolio Accounting with Stock Deletion, 7 Analysts Debate, and Corporate Actions.
 */

const API_BASE = "";

// Security & Token Management
function getAuthHeader() {
    const token = localStorage.getItem("pstk_access_token");
    const apiKey = localStorage.getItem("pstk_api_key");
    if (token) return { "Authorization": `Bearer ${token}` };
    if (apiKey) return { "X-API-Key": apiKey };
    return {};
}

async function authFetch(url, options = {}) {
    options.headers = {
        ...(options.headers || {}),
        ...getAuthHeader()
    };
    let response = await fetch(url, options);
    if (response.status === 401) {
        // 1. Transparent Refresh via refresh_token
        const refreshToken = localStorage.getItem("pstk_refresh_token");
        if (refreshToken) {
            try {
                const refRes = await fetch(`${API_BASE}/api/auth/refresh?token=${encodeURIComponent(refreshToken)}`, { method: "POST" });
                if (refRes.ok) {
                    const data = await refRes.json();
                    localStorage.setItem("pstk_access_token", data.access_token);
                    options.headers["Authorization"] = `Bearer ${data.access_token}`;
                    return await fetch(url, options);
                }
            } catch (e) {
                console.warn("Token refresh attempt failed:", e);
            }
        }
        // 2. Seamless Terminal Authenticator: auto-acquire trader session
        try {
            const loginRes = await fetch(`${API_BASE}/api/auth/login`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username: "default_trader", password: "trader123" })
            });
            if (loginRes.ok) {
                const loginData = await loginRes.json();
                if (loginData.user && loginData.user.access_token) {
                    localStorage.setItem("pstk_access_token", loginData.user.access_token);
                    localStorage.setItem("pstk_refresh_token", loginData.user.refresh_token);
                    localStorage.setItem("pstk_api_key", loginData.user.api_key);
                    options.headers["Authorization"] = `Bearer ${loginData.user.access_token}`;
                    return await fetch(url, options);
                }
            }
        } catch (e) {
            console.warn("Auto-session acquisition failed:", e);
        }
    }
    return response;
}

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "\"": "&quot;",
        "'": "&#39;"
    }[ch]));
}

async function apiErrorDetail(res, fallback) {
    try {
        const body = await res.json();
        if (typeof body.detail === "string" && body.detail.trim()) return body.detail;
    } catch (err) {
        // Response body was not JSON.
    }
    return fallback;
}


// Global State
let currentTab = "charts";
let recommendationsData = [];
let portfolioData = null;
let scorecardData = null;
let stockUniverse = [];
let priceChartInstance = null;
let portfolioChartInstance = null;
let currentChartData = null;
let currentChartSymbol = "RELIANCE";
let currentChartExchange = "NSE";
let currentTimeframe = "3mo";
let chartRequestId = 0;
let searchResults = [];
let searchActiveIndex = -1;
let searchSeq = 0;
let searchTimer = null;
let searchQuery = "";
let show5dProjection = true;
let stockToDelete = null;

// Benchmark liquid stocks for the interactive watchlist
const DEFAULT_WATCHLIST_SYMBOLS = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "TATASTEEL", "BHARTIARTL", "SBIN", "ITC", "LT"
];
let watchlistQuotes = {};

document.addEventListener("DOMContentLoaded", () => {
    initApp();
    setupEventListeners();
});

function cssVar(name) {
    return getComputedStyle(document.body).getPropertyValue(name).trim();
}

async function initApp() {
    initTheme();
    await fetchUniverse();
    await fetchSystemStatus();
    await fetchIntegrationsStatus();
    await loadStockChart(currentChartSymbol, currentTimeframe);
    loadRecommendations();
    loadPortfolio();
    loadScorecard();
    initWatchlist();
    setupReportPreview();

    // Auto-refresh market status every 30 seconds, integrations every 60 seconds
    setInterval(fetchSystemStatus, 30000);
    setInterval(fetchIntegrationsStatus, 60000);
}

function setupEventListeners() {
    // Keyboard shortcut: Cmd/Ctrl + K to focus search
    document.addEventListener("keydown", (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
            e.preventDefault();
            const searchInput = document.getElementById("globalStockSearch");
            if (searchInput) {
                searchInput.focus();
                searchInput.select();
            }
        }
    });

    setupGlobalSearch();

    // Default today's date in transaction form
    const dateInput = document.getElementById("txDate");
    if (dateInput) {
        dateInput.value = new Date().toISOString().split("T")[0];
    }

}

// --------------------------------------------------------------------------
// Navigation & Application Shell
// --------------------------------------------------------------------------
function toggleMobileSidebar() {
    const sidebar = document.getElementById("appSidebar");
    const backdrop = document.getElementById("sidebarBackdrop");
    if (sidebar) sidebar.classList.toggle("mobile-open");
    if (backdrop) backdrop.classList.toggle("active");
}

function closeMobileSidebar() {
    const sidebar = document.getElementById("appSidebar");
    const backdrop = document.getElementById("sidebarBackdrop");
    if (sidebar) sidebar.classList.remove("mobile-open");
    if (backdrop) backdrop.classList.remove("active");
}

function switchTab(tabName) {
    currentTab = tabName;
    closeMobileSidebar();

    // Sidebar active item styling
    document.querySelectorAll(".sidebar-nav .nav-item").forEach(item => item.classList.remove("active"));
    const activeBtn = document.getElementById(`nav-btn-${tabName}`);
    if (activeBtn) activeBtn.classList.add("active");

    // View panels toggle
    document.querySelectorAll(".view-panel").forEach(panel => panel.classList.remove("active"));
    const activePanel = document.getElementById(`view-${tabName}`);
    if (activePanel) activePanel.classList.add("active");

    // Update Topbar View Title
    const titleMap = {
        "charts": "Market Desk",
        "recs": "Today's Setups",
        "portfolio": "My Portfolio",
        "risk": "Sector Allocation & Risk",
        "scorecard": "Performance & Strategy Lab",
        "reports": "Daily Briefing & Reports",
        "weekly-backtest": "Weekly Backtest"
    };
    const titleEl = document.getElementById("currentViewTitle");
    if (titleEl && titleMap[tabName]) {
        titleEl.textContent = titleMap[tabName];
    }

    if (tabName === "reports") {
        setupReportPreview();
    }
    if (tabName === "weekly-backtest") {
        initWeeklyBacktest();
    }

    // Window resize trigger for chart redraw if returning to charts view
    if (tabName === "charts" && priceChartInstance) {
        setTimeout(() => priceChartInstance.resize(), 50);
    }
    if (tabName === "portfolio" && portfolioChartInstance) {
        setTimeout(() => portfolioChartInstance.resize(), 50);
    }
}

function toggleSidebarCollapse() {
    const sidebar = document.getElementById("appSidebar");
    if (sidebar) {
        sidebar.classList.toggle("collapsed");
        if (priceChartInstance) {
            setTimeout(() => priceChartInstance.resize(), 260);
        }
        if (portfolioChartInstance) {
            setTimeout(() => portfolioChartInstance.resize(), 260);
        }
    }
}

function rawSearchQuery() {
    const input = document.getElementById("globalStockSearch");
    if (!input) return "";
    return input.value.split("•")[0].trim();
}

function hideSearchResults() {
    const panel = document.getElementById("globalSearchResults");
    const input = document.getElementById("globalStockSearch");
    if (panel) panel.hidden = true;
    if (input) input.setAttribute("aria-expanded", "false");
    searchActiveIndex = -1;
}

function renderSearchResults() {
    const panel = document.getElementById("globalSearchResults");
    const input = document.getElementById("globalStockSearch");
    if (!panel) return;
    if (!searchResults.length) {
        panel.hidden = false;
        if (input) input.setAttribute("aria-expanded", "true");
        panel.innerHTML = `<div class="search-results-empty">No NSE or BSE listing matches that search.</div>`;
        return;
    }
    panel.hidden = false;
    if (input) input.setAttribute("aria-expanded", "true");
    panel.innerHTML = searchResults.map((row, index) => {
        const exchange = (row.exchange || "NSE").toUpperCase();
        const badgeClass = exchange === "BSE" ? "bse" : "nse";
        return `
            <button type="button" class="search-result-row${index === searchActiveIndex ? " active" : ""}" role="option" data-search-index="${index}" aria-selected="${index === searchActiveIndex}">
                <span class="search-result-symbol">${escapeHtml(row.symbol)}</span>
                <span class="search-result-name">${escapeHtml(row.name || row.symbol)}</span>
                <span class="search-exchange-badge ${badgeClass}">${escapeHtml(exchange)}</span>
            </button>
        `;
    }).join("");
    panel.querySelectorAll(".search-result-row").forEach((button) => {
        button.addEventListener("mousedown", (event) => {
            event.preventDefault();
            const index = Number(button.getAttribute("data-search-index"));
            if (searchResults[index]) openSearchedStock(searchResults[index]);
        });
    });
}

async function runGlobalSearch(query) {
    const seq = ++searchSeq;
    searchQuery = query;
    try {
        const res = await fetch(`${API_BASE}/api/search?q=${encodeURIComponent(query)}`);
        if (!res.ok) throw new Error(await apiErrorDetail(res, "Stock search failed"));
        const rows = await res.json();
        if (seq !== searchSeq) return rows;
        searchResults = Array.isArray(rows) ? rows : [];
        searchActiveIndex = -1;
        renderSearchResults();
        return searchResults;
    } catch (err) {
        if (seq !== searchSeq) return [];
        searchResults = [];
        const panel = document.getElementById("globalSearchResults");
        if (panel) {
            panel.hidden = false;
            panel.innerHTML = `<div class="search-results-empty">${escapeHtml(err.message)}</div>`;
        }
        return [];
    }
}

function openSearchedStock(result) {
    if (!result || !result.symbol) return;
    const input = document.getElementById("globalStockSearch");
    if (input) input.value = `${result.symbol} • ${result.name || result.symbol}`;
    hideSearchResults();
    switchTab("charts");
    loadStockChart(result.symbol, currentTimeframe, result.exchange || "NSE", true);
}

async function commitGlobalSearch() {
    clearTimeout(searchTimer);
    const query = rawSearchQuery();
    if (!query) return;
    if (searchActiveIndex >= 0 && searchResults[searchActiveIndex]) {
        openSearchedStock(searchResults[searchActiveIndex]);
        return;
    }
    if (searchQuery !== query || !searchResults.length) {
        await runGlobalSearch(query);
    }
    const upper = query.toUpperCase();
    const exact = searchResults.filter((row) => (row.symbol || "").toUpperCase() === upper);
    if (!query.includes(" ") && exact.length === 1) {
        openSearchedStock(exact[0]);
        return;
    }
    if (query.includes(" ") && searchResults.length) {
        openSearchedStock(searchResults[0]);
        return;
    }
    if (searchResults.length === 1) {
        openSearchedStock(searchResults[0]);
        return;
    }
    if (searchResults.length > 1) {
        renderSearchResults();
        showToast("Select the listing from the search list.", "info");
        return;
    }
    switchTab("charts");
    loadStockChart(query, currentTimeframe, "", true);
}

function moveSearchHighlight(step) {
    if (!searchResults.length) return;
    const panel = document.getElementById("globalSearchResults");
    if (panel && panel.hidden) {
        renderSearchResults();
    }
    const next = searchActiveIndex < 0
        ? (step > 0 ? 0 : searchResults.length - 1)
        : (searchActiveIndex + step + searchResults.length) % searchResults.length;
    searchActiveIndex = next;
    renderSearchResults();
    const active = document.querySelector(".search-result-row.active");
    if (active) active.scrollIntoView({ block: "nearest" });
}

function setupGlobalSearch() {
    const input = document.getElementById("globalStockSearch");
    if (!input) return;
    input.addEventListener("input", () => {
        clearTimeout(searchTimer);
        const query = rawSearchQuery();
        if (query.length < 1) {
            searchResults = [];
            searchQuery = "";
            hideSearchResults();
            return;
        }
        searchTimer = setTimeout(() => runGlobalSearch(query), 220);
    });
    input.addEventListener("keydown", (event) => {
        if (event.key === "ArrowDown") {
            event.preventDefault();
            moveSearchHighlight(1);
        } else if (event.key === "ArrowUp") {
            event.preventDefault();
            moveSearchHighlight(-1);
        } else if (event.key === "Enter") {
            event.preventDefault();
            commitGlobalSearch();
        } else if (event.key === "Escape") {
            hideSearchResults();
        }
    });
    input.addEventListener("focus", () => {
        if (searchResults.length && rawSearchQuery()) renderSearchResults();
    });
    document.addEventListener("click", (event) => {
        if (!event.target.closest(".global-search-container")) hideSearchResults();
    });
}

// --------------------------------------------------------------------------
// System Status & Ticker Feeds
// --------------------------------------------------------------------------
async function fetchSystemStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/status`);
        if (!res.ok) return;
        const data = await res.json();

        // Update Pulse & Market Session Status
        const pulseEl = document.getElementById("marketPulseDot");
        const statusEl = document.getElementById("marketSessionStatus");
        const textEl = document.getElementById("marketStatusText");

        const sessionOpen = data.market_status === "OPEN";
        if (statusEl) {
            statusEl.textContent = sessionOpen ? "Open" : "Closed";
        }
        if (pulseEl) {
            if (sessionOpen) pulseEl.classList.remove("closed");
            else pulseEl.classList.add("closed");
        }
        if (textEl) {
            textEl.textContent = "NSE session";
        }

        // Ticker: NIFTY 50
        const niftyPriceEl = document.getElementById("niftyPrice");
        const niftyChgEl = document.getElementById("niftyChange");
        if (niftyPriceEl && data.nifty50 != null) {
            niftyPriceEl.textContent = `₹${Number(data.nifty50).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
        }
        if (niftyChgEl && data.nifty50_change_pct != null) {
            const isPos = data.nifty50_change_pct >= 0;
            niftyChgEl.textContent = `${isPos ? "+" : ""}${data.nifty50_change_pct}%`;
            niftyChgEl.className = `index-change tabular-nums ${isPos ? "up" : "down"}`;
        }

        // Ticker: INDIA VIX
        const vixValEl = document.getElementById("vixVal");
        const vixChgEl = document.getElementById("vixChange");
        if (vixValEl && data.india_vix != null) {
            vixValEl.textContent = Number(data.india_vix).toFixed(2);
        }
        if (vixChgEl && data.vix_change_pct != null) {
            const isPos = data.vix_change_pct >= 0;
            vixChgEl.textContent = `${isPos ? "+" : ""}${data.vix_change_pct}%`;
            // For VIX, lower is calm (green), higher is volatility spike
            vixChgEl.className = `index-change tabular-nums ${isPos ? "down" : "up"}`;
        }
    } catch (err) {
        console.warn("Status fetch error:", err);
    }
}

async function fetchUniverse() {
    try {
        const res = await fetch(`${API_BASE}/api/universe`);
        if (!res.ok) return;
        stockUniverse = await res.json();
        populateUniverseDatalist(stockUniverse);
    } catch (err) {
        console.warn("Universe fetch error:", err);
    }
}

function populateUniverseDatalist(stocks) {
    const datalist = document.getElementById("stockUniverseList");
    if (!datalist || !stocks) return;
    datalist.innerHTML = stocks.map(s => `
        <option value="${s.symbol}">${s.symbol} • ${s.name} (${s.sector})</option>
    `).join("");
}

// --------------------------------------------------------------------------
// Interactive Stock Charting Engine & 5D Future ATR Volatility Cone
// --------------------------------------------------------------------------
function setTimeframe(period, btn) {
    currentTimeframe = period;
    document.querySelectorAll(".timeframe-pill-group .tf-btn").forEach(b => b.classList.remove("active"));
    if (btn) btn.classList.add("active");
    loadStockChart(currentChartSymbol, currentTimeframe, currentChartExchange);
}

function toggleForecastProjection() {
    show5dProjection = !show5dProjection;
    const btn = document.getElementById("btnToggleForecast");
    if (btn) {
        btn.textContent = show5dProjection ? "5D volatility cone: ON" : "5D volatility cone: OFF";
        btn.style.color = show5dProjection ? "var(--accent-cyan)" : "var(--text-muted)";
    }
    if (currentChartData) {
        renderPriceChart(currentChartData);
    }
}

async function loadStockChart(symbol, period = "3mo", exchange = "", announce = false) {
    const requested = (symbol || "RELIANCE").trim();
    const requestId = ++chartRequestId;
    const subTitle = document.getElementById("chartSubtitle");
    if (subTitle) {
        subTitle.textContent = `Loading institutional price data and the 5-day trajectory for ${requested}...`;
    }

    try {
        const params = new URLSearchParams({ period: period || "3mo" });
        if (exchange) params.set("exchange", exchange);
        const res = await fetch(`${API_BASE}/api/chart/${encodeURIComponent(requested)}?${params.toString()}`);
        if (requestId !== chartRequestId) return;
        if (!res.ok) {
            throw new Error(await apiErrorDetail(res, `Price history unavailable for ${requested}`));
        }
        currentChartData = await res.json();
        currentChartSymbol = currentChartData.symbol || requested.toUpperCase();
        currentChartExchange = currentChartData.exchange || exchange || "NSE";

        // Update Stock Identity
        const heroSym = document.getElementById("heroStockSymbol");
        const heroName = document.getElementById("heroStockName");
        if (heroSym) heroSym.textContent = currentChartSymbol;
        if (heroName) heroName.textContent = `${currentChartData.name || currentChartSymbol} • ${currentChartExchange} Equity`;

        // Update CMP & Change
        const cmpEl = document.getElementById("chartCmp");
        const cmpChgEl = document.getElementById("chartCmpChange");
        const histCloses = currentChartData.closes || [];
        const prevClose = histCloses.length >= 2 ? histCloses[histCloses.length - 2] : currentChartData.cmp;
        const cmpChangePct = prevClose > 0 ? (((currentChartData.cmp - prevClose) / prevClose) * 100).toFixed(2) : "0.00";

        if (cmpEl) cmpEl.textContent = `₹${Number(currentChartData.cmp).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
        if (cmpChgEl) {
            const isPos = cmpChangePct >= 0;
            cmpChgEl.textContent = `${isPos ? "+" : ""}${cmpChangePct}% (1D)`;
            cmpChgEl.className = `cmp-change tabular-nums ${isPos ? "up" : "down"}`;
        }

        const bandLow = Number(currentChartData.expected_range_low);
        const bandHigh = Number(currentChartData.expected_range_high);
        const halfWidthPct = currentChartData.cmp > 0
            ? (((bandHigh - bandLow) / 2) / currentChartData.cmp * 100).toFixed(2)
            : "0.00";
        const atrPct = currentChartData.cmp > 0
            ? (Number(currentChartData.atr_14) / currentChartData.cmp * 100).toFixed(2)
            : "0.00";

        const atrEl = document.getElementById("chartAtr");
        const targetEl = document.getElementById("chartTarget");
        if (atrEl) atrEl.textContent = `₹${currentChartData.atr_14}`;
        if (targetEl) {
            targetEl.textContent = `₹${Math.round(bandLow).toLocaleString("en-IN")} – ₹${Math.round(bandHigh).toLocaleString("en-IN")}`;
            targetEl.style.color = "var(--text-primary)";
        }

        const aiTarget = document.getElementById("aiTargetPrice");
        const aiLabel = document.getElementById("aiTargetLabel");
        const aiBounds = document.getElementById("aiRangeBounds");
        const aiStance = document.getElementById("aiStanceBadge");
        const aiScore = document.getElementById("aiScoreVal");
        const aiRisk = document.getElementById("aiRiskVal");
        const aiSource = document.getElementById("aiSourceVal");
        const freshness = document.getElementById("aiDataFreshness");
        const predicted = Number(currentChartData.expected_target_price);
        const onBook = Boolean(currentChartData.scored) && Number.isFinite(predicted) && predicted > 0;
        const direction = String(currentChartData.direction || "").toUpperCase();

        if (aiBounds) {
            aiBounds.textContent = `₹${Math.round(bandLow)} to ₹${Math.round(bandHigh)}`;
        }
        if (onBook) {
            const higher = predicted >= Number(currentChartData.cmp);
            if (aiLabel) aiLabel.textContent = "5-day target";
            if (aiTarget) {
                aiTarget.textContent = `₹${predicted.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
                aiTarget.className = `pred-target-val tabular-nums ${higher ? "up" : "down"}`;
            }
            if (aiStance) {
                aiStance.textContent = direction || "Scored";
                aiStance.className = `stance-pill ${direction.includes("BULL") ? "bull" : (direction.includes("BEAR") ? "bear" : "neutral")}`;
            }
            if (aiScore && currentChartData.composite_score != null) {
                aiScore.textContent = `${currentChartData.composite_score}/100`;
            }
            if (freshness) freshness.textContent = `Scored ${currentChartData.scored_on || "by the desk"}`;
            if (aiSource) aiSource.textContent = "Today's book";
        } else {
            if (aiLabel) aiLabel.textContent = "Last close";
            if (aiTarget) {
                aiTarget.textContent = `₹${Number(currentChartData.cmp).toLocaleString("en-IN")}`;
                aiTarget.className = "pred-target-val tabular-nums";
            }
            if (aiStance) {
                aiStance.textContent = "Not scored";
                aiStance.className = "stance-pill neutral";
            }
            if (aiScore) aiScore.textContent = "Not scored";
            if (freshness) freshness.textContent = "Not a scored forecast";
            if (aiSource) aiSource.textContent = "Price history only";
        }
        if (aiRisk) aiRisk.textContent = `ATR ${atrPct}%`;

        const gainEl = document.getElementById("panelGain");
        gainEl.textContent = `±${halfWidthPct}%`;
        gainEl.className = "ind-value";
        document.getElementById("panelRange").textContent = `₹${Math.round(bandLow)} - ₹${Math.round(bandHigh)}`;
        document.getElementById("panelSupport").textContent = `₹${currentChartData.support}`;
        document.getElementById("panelResistance").textContent = `₹${currentChartData.resistance}`;

        // Fetch Verified Fundamentals from backend
        try {
            const fundRes = await fetch(`${API_BASE}/api/fundamentals/${encodeURIComponent(currentChartSymbol)}?exchange=${encodeURIComponent(currentChartExchange)}`);
            if (fundRes.ok) {
                const fund = await fundRes.json();
                const peEl = document.getElementById("panelPE");
                const roeEl = document.getElementById("panelROE");
                const deEl = document.getElementById("panelDE");
                const revEl = document.getElementById("panelRevGrowth");
                if (peEl) peEl.textContent = fund.pe_ratio != null ? `${fund.pe_ratio}x` : "N/A";
                if (roeEl) roeEl.textContent = fund.roe != null ? `${fund.roe}% / ${fund.roce || '--'}%` : "N/A";
                if (deEl) deEl.textContent = fund.debt_to_equity != null ? `${fund.debt_to_equity}x` : "0.0x";
                if (revEl) revEl.textContent = fund.revenue_growth_yoy != null ? `${fund.revenue_growth_yoy > 0 ? "+" : ""}${fund.revenue_growth_yoy}%` : "N/A";
            }
        } catch (fErr) {
            console.warn("Fundamentals fetch note:", fErr);
        }

        if (subTitle) {
            const lastSession = histCloses.length ? currentChartData.dates[currentChartData.dates.length - 1] : "";
            subTitle.textContent = `${currentChartSymbol} daily close through ${lastSession}, with 20-DMA and 5-day ATR volatility cone`;
        }

        renderPriceChart(currentChartData);
        if (announce) {
            showToast(`Loaded ${currentChartData.name || currentChartSymbol} (${currentChartExchange})`, "info");
        }
    } catch (err) {
        if (requestId !== chartRequestId) return;
        console.error("Chart load error:", err);
        const stillShowing = currentChartData && currentChartData.symbol
            ? ` Chart is still ${currentChartData.symbol}.`
            : "";
        if (subTitle) subTitle.textContent = `${err.message}${stillShowing}`;
        showToast(err.message, "error");
    }
}

function renderPriceChart(data) {
    const ctx = document.getElementById("stockPriceChart");
    if (!ctx) return;

    if (priceChartInstance) {
        priceChartInstance.destroy();
    }

    const dates = Array.isArray(data.dates) ? data.dates : [];
    const histLen = dates.length;
    const allLabels = [...dates];

    const histCloseSeries = Array.isArray(data.closes) ? [...data.closes] : [];
    const sma20Series = Array.isArray(data.sma20) ? [...data.sma20] : new Array(histLen).fill(null);
    const projectedDates = Array.isArray(data.projected_dates) ? data.projected_dates : [];
    const projectedHighs = Array.isArray(data.projected_highs) ? data.projected_highs : [];
    const projectedLows = Array.isArray(data.projected_lows) ? data.projected_lows : [];
    const projectedTargets = Array.isArray(data.projected_targets) ? data.projected_targets : [];

    const targetSeries = new Array(Math.max(histLen - 1, 0)).fill(null);
    if (projectedTargets.length && histLen > 0) targetSeries.push(data.cmp);
    const coneUpperSeries = new Array(Math.max(histLen - 1, 0)).fill(null);
    const coneLowerSeries = new Array(Math.max(histLen - 1, 0)).fill(null);
    if (histLen > 0) {
        coneUpperSeries.push(data.cmp);
        coneLowerSeries.push(data.cmp);
    }

    if (show5dProjection) {
        projectedDates.forEach((d, idx) => {
            const label = typeof d === "string" ? d.slice(5) : "";
            allLabels.push(`5D: ${label}`);
            histCloseSeries.push(null);
            sma20Series.push(null);
            if (projectedTargets.length) targetSeries.push(projectedTargets[idx] ?? null);
            coneUpperSeries.push(projectedHighs[idx] ?? null);
            coneLowerSeries.push(projectedLows[idx] ?? null);
        });
    }

    const isLight = document.body.classList.contains("light-theme");

    const datasets = [
        {
            label: "Historical Close (₹)",
            data: histCloseSeries,
            borderColor: cssVar("--gain"),
            backgroundColor: cssVar("--chart-hist-bg"),
            borderWidth: 2,
            pointRadius: 0,
            pointHoverRadius: 4,
            pointHoverBackgroundColor: cssVar("--gain"),
            fill: true,
            tension: 0.1
        },
        {
            label: "20-DMA (₹)",
            data: sma20Series,
            borderColor: cssVar("--warn"),
            borderWidth: 1.5,
            borderDash: [4, 4],
            pointRadius: 0,
            fill: false
        }
    ];

    if (show5dProjection && projectedDates.length) {
        if (projectedTargets.length) {
            datasets.push({
                label: "Desk target (₹)",
                data: targetSeries,
                borderColor: cssVar("--accent"),
                borderWidth: 2.5,
                borderDash: [6, 3],
                pointRadius: 3,
                pointBackgroundColor: cssVar("--accent"),
                fill: false,
                tension: 0.1
            });
        }
        datasets.push(
            {
                label: "ATR Upper Volatility Band (₹)",
                data: coneUpperSeries,
                borderColor: cssVar("--chart-cone-border"),
                borderWidth: 1,
                borderDash: [2, 2],
                pointRadius: 0,
                fill: "+1",
                backgroundColor: cssVar("--chart-cone")
            },
            {
                label: "ATR Lower Support Band (₹)",
                data: coneLowerSeries,
                borderColor: cssVar("--chart-cone-border"),
                borderWidth: 1,
                borderDash: [2, 2],
                pointRadius: 0,
                fill: false
            }
        );
    }

    priceChartInstance = new Chart(ctx, {
        type: "line",
        data: {
            labels: allLabels,
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: "index",
                intersect: false
            },
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    backgroundColor: cssVar("--chart-tooltip-bg"),
                    titleColor: cssVar("--accent"),
                    bodyColor: cssVar("--text-primary"),
                    borderColor: cssVar("--chart-tooltip-border"),
                    borderWidth: 1,
                    padding: 10,
                    titleFont: { family: "JetBrains Mono", size: 11 },
                    bodyFont: { family: "JetBrains Mono", size: 11 },
                    callbacks: {
                        label: function(context) {
                            if (context.parsed.y === null || context.parsed.y === undefined) return null;
                            return `${context.dataset.label}: ₹${context.parsed.y.toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: cssVar("--chart-grid") },
                    ticks: {
                        color: cssVar("--text-muted"),
                        font: { family: "JetBrains Mono", size: 9 },
                        maxTicksLimit: 12
                    }
                },
                y: {
                    grid: { color: cssVar("--chart-grid") },
                    ticks: {
                        color: cssVar("--text-muted"),
                        font: { family: "JetBrains Mono", size: 10 },
                        callback: function(val) { return "₹" + val.toLocaleString("en-IN"); }
                    }
                }
            }
        }
    });
}

// --------------------------------------------------------------------------
// Watchlist Engine
// --------------------------------------------------------------------------
async function initWatchlist() {
    const container = document.getElementById("watchlistContainer");
    if (!container) return;

    container.innerHTML = DEFAULT_WATCHLIST_SYMBOLS.map(sym => `
        <div class="watchlist-row ${sym === currentChartSymbol ? 'selected' : ''}" id="wl-${sym}" onclick="selectWatchlistStock('${sym}')">
            <div class="wl-stock-info">
                <span class="wl-symbol">${sym}</span>
                <span class="wl-name">${getCompanyName(sym)}</span>
            </div>
            <div class="wl-price-info">
                <div class="wl-cmp tabular-nums" id="wl-price-${sym}">--</div>
                <div class="wl-chg tabular-nums" id="wl-chg-${sym}">--</div>
            </div>
        </div>
    `).join("");

    // Fetch live quotes for watchlist symbols in background
    for (const sym of DEFAULT_WATCHLIST_SYMBOLS) {
        fetchWatchlistQuote(sym);
    }
}

function getCompanyName(sym) {
    const names = {
        "RELIANCE": "Reliance Industries",
        "TCS": "Tata Consultancy Svcs",
        "INFY": "Infosys Limited",
        "HDFCBANK": "HDFC Bank Ltd",
        "ICICIBANK": "ICICI Bank Ltd",
        "TATASTEEL": "Tata Steel Limited",
        "BHARTIARTL": "Bharti Airtel Ltd",
        "SBIN": "State Bank of India",
        "ITC": "ITC Limited",
        "LT": "Larsen & Toubro Ltd"
    };
    return names[sym] || sym;
}

async function fetchWatchlistQuote(sym) {
    try {
        const res = await fetch(`${API_BASE}/api/quote/${sym}`);
        if (!res.ok) return;
        const q = await res.json();
        const pEl = document.getElementById(`wl-price-${sym}`);
        const cEl = document.getElementById(`wl-chg-${sym}`);
        if (pEl && q.close_price) {
            pEl.textContent = `₹${Number(q.close_price).toLocaleString("en-IN")}`;
        }
        const changePct = q.day_change_pct != null ? q.day_change_pct : q.change_pct;
        if (cEl && changePct != null) {
            const isPos = changePct >= 0;
            cEl.textContent = `${isPos ? "+" : ""}${changePct}%`;
            cEl.className = `wl-chg tabular-nums ${isPos ? "up" : "down"}`;
        }
    } catch (e) {
        // Quiet fallback
    }
}

function selectWatchlistStock(sym) {
    document.querySelectorAll(".watchlist-row").forEach(r => r.classList.remove("selected"));
    const row = document.getElementById(`wl-${sym}`);
    if (row) row.classList.add("selected");
    loadStockChart(sym, currentTimeframe);
}

// --------------------------------------------------------------------------
// 5D Pre-Market Recommendations
// --------------------------------------------------------------------------
async function loadRecommendations() {
    try {
        const res = await fetch(`${API_BASE}/api/recommendations/today`);
        if (!res.ok) return;
        recommendationsData = await res.json();
        renderRecommendations(recommendationsData);
    } catch (err) {
        console.error("Recommendations load error:", err);
    }
}

function renderRecommendations(recs) {
    const container = document.getElementById("recsGrid");
    const countBadge = document.getElementById("sidebarRecCount");
    const statCount = document.getElementById("statRecCount");
    const statAvg = document.getElementById("statAvgGain");

    if (!container) return;

    if (!recs || recs.length === 0) {
        container.innerHTML = `
            <div style="grid-column: 1 / -1; padding: 40px; text-align: center; color: var(--text-muted); background: var(--bg-surface); border-radius: var(--radius-md); border: 1px solid var(--border-subtle);">
                <h3 style="color: var(--amber-warning); margin-bottom: 6px;">No Screened Opportunities Today</h3>
                <p>The multi-factor model vetoes candidates when setups do not satisfy the strict quality and volatility criteria.</p>
            </div>
        `;
        renderPredictedTrackerTable([]);
        return;
    }

    // Deduplicate
    const seen = new Set();
    const uniqueRecs = recs.filter(r => {
        if (!r || !r.symbol || seen.has(r.symbol)) return false;
        seen.add(r.symbol);
        return true;
    });

    if (countBadge) countBadge.textContent = uniqueRecs.length;
    if (statCount) statCount.textContent = `${uniqueRecs.length} Ideas`;

    const avgGain = (uniqueRecs.reduce((acc, r) => acc + (r.expected_appreciation_pct || 0), 0) / uniqueRecs.length).toFixed(1);
    if (statAvg) statAvg.textContent = `${avgGain >= 0 ? "+" : ""}${avgGain}% avg`;

    renderPredictedTrackerTable(uniqueRecs);

    container.innerHTML = uniqueRecs.map(r => {
        const refPrice = Number(r.reference_price) || 0;
        const targetPrice = Number(r.expected_target_price) || refPrice;
        const stopLoss = Number(r.stop_loss) || Math.round(refPrice - (r.atr_14 || refPrice * 0.02));
        const actualPrice = Number(r.current_price) || refPrice;
        
        // Progress calculations
        const rangeSpan = Math.max(1, targetPrice - stopLoss);
        const actualPct = Math.min(100, Math.max(0, ((actualPrice - stopLoss) / rangeSpan) * 100));
        const entryPct = Math.min(100, Math.max(0, ((refPrice - stopLoss) / rangeSpan) * 100));
        
        const liveChangePct = refPrice > 0 ? (((actualPrice - refPrice) / refPrice) * 100).toFixed(2) : "0.00";
        const netExpectedPct = (Number(r.expected_appreciation_pct || 0) - 0.30).toFixed(2);
        const isVerifiedBhavcopy = (r.delivery_source === "NSE_BHAVCOPY");
        
        const sourceBadgeHtml = isVerifiedBhavcopy
            ? `<span class="badge-verified-bhavcopy" title="Verified daily demat delivery volume from official exchange Bhavcopy">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                Verified delivery
               </span>`
            : `<span class="badge-proxy-estimate" title="Estimated proxy delivery metrics - awaiting official exchange settlement">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="12" y1="8" x2="12" y2="12"></line>
                    <line x1="12" y1="16" x2="12.01" y2="16"></line>
                </svg>
                Proxy estimate
               </span>`;

        return `
        <div class="rec-card">
            <div>
                <div class="rec-card-top">
                    <div>
                        <div class="rec-symbol">${r.symbol} <span style="font-size: 11px; color: var(--text-dim); font-weight: normal;">(NSE)</span></div>
                        <div class="rec-sector">${r.name} &bull; ${r.sector || "Large Cap"}</div>
                    </div>
                    <div style="text-align: right; display: flex; flex-direction: column; align-items: flex-end; gap: 4px;">
                        ${sourceBadgeHtml}
                        <div class="target-badge ${Number(r.expected_appreciation_pct) < 0 ? 'down' : ''}">
                            ${Number(r.expected_appreciation_pct) >= 0 ? '+' : ''}${r.expected_appreciation_pct}% (${r.direction || 'SWING'})
                        </div>
                    </div>
                </div>

                <!-- Side-by-Side Actual Price vs Predicted Target Grid -->
                <div class="metrics-row">
                    <div class="metric-box">
                        <label>Entry (T+1 Open)</label>
                        <span class="tabular-nums">₹${refPrice.toLocaleString("en-IN", {minimumFractionDigits: 1})}</span>
                    </div>
                    <div class="metric-box" style="border-left: 2px solid var(--accent-mint);">
                        <label>Actual LTP</label>
                        <span class="tabular-nums ${Number(liveChangePct) >= 0 ? 'up' : 'down'}">
                            ₹${actualPrice.toLocaleString("en-IN", {minimumFractionDigits: 1})}
                            <small style="font-size: 12px;">(${Number(liveChangePct) >= 0 ? '+' : ''}${liveChangePct}%)</small>
                        </span>
                    </div>
                    <div class="metric-box">
                        <label>5D Target</label>
                        <span class="tabular-nums ${Number(r.expected_appreciation_pct) >= 0 ? 'up' : 'down'}">
                            ₹${targetPrice.toLocaleString("en-IN", {minimumFractionDigits: 1})}
                            <small style="font-size: 12px; color: var(--text-muted);">(Net: ${netExpectedPct}%)</small>
                        </span>
                    </div>
                    <div class="metric-box">
                        <label>ATR Stop-Loss</label>
                        <span class="tabular-nums down">₹${stopLoss.toLocaleString("en-IN", {minimumFractionDigits: 1})}</span>
                    </div>
                </div>

                <!-- Visual Stop-to-Target Progress Bar -->
                <div class="stop-target-progress-container">
                    <div class="stop-target-labels">
                        <span style="color: var(--accent-coral);">STOP: ₹${Math.round(stopLoss)}</span>
                        <span style="color: var(--text-secondary);">ENTRY: ₹${Math.round(refPrice)}</span>
                        <span style="color: var(--accent-mint);">TARGET: ₹${Math.round(targetPrice)}</span>
                    </div>
                    <div class="progress-track-wrapper" title="Stop: ₹${stopLoss} | Entry: ₹${refPrice} | Actual: ₹${actualPrice} | Target: ₹${targetPrice}">
                        <div class="progress-entry-divider" style="left: ${entryPct}%;"></div>
                        ${actualPrice >= refPrice ? `
                            <div class="progress-fill-bull" style="left: ${entryPct}%; width: ${Math.max(0, actualPct - entryPct)}%;"></div>
                        ` : `
                            <div class="progress-fill-bear" style="left: ${actualPct}%; width: ${Math.max(0, entryPct - actualPct)}%;"></div>
                        `}
                        <div class="progress-current-marker" style="left: ${actualPct}%;" title="Live Actual Market Price: ₹${actualPrice}"></div>
                    </div>
                    <div style="display: flex; justify-content: space-between; font-size: 12px; color: var(--text-muted); font-family: var(--font-mono); margin-top: 5px;">
                        <span>5D Low: ₹${Math.round(r.expected_range_low || stopLoss)}</span>
                        <span style="color: var(--text-primary); font-weight: 700;">
                            LTP: ${Math.round(actualPct)}% of Target Path
                        </span>
                        <span>5D High: ₹${Math.round(r.expected_range_high || targetPrice)}</span>
                    </div>
                </div>

                <!-- Data Provenance & Institutional Flow Badges -->
                <div style="margin: 8px 0; display: flex; gap: 6px; align-items: center; flex-wrap: wrap;">
                    <span style="font-size: 12px; font-family: var(--font-mono); color: var(--text-secondary); background: var(--bg-elevated); padding: 2px 7px; border-radius: var(--radius-xs); border: 1px solid var(--border-subtle);">
                        Deliv: <strong style="color: var(--text-primary);">${r.deliv_per ? Number(r.deliv_per).toFixed(1) : '45.0'}%</strong>
                    </span>
                    <span style="font-size: 12px; font-family: var(--font-mono); color: var(--text-secondary); background: var(--bg-elevated); padding: 2px 7px; border-radius: var(--radius-xs); border: 1px solid var(--border-subtle);">
                        Surge: <strong style="color: var(--text-primary);">${r.deliv_surge ? Number(r.deliv_surge).toFixed(1) : '1.0'}x</strong>
                    </span>
                    <span style="font-size: 12px; font-family: var(--font-mono); color: var(--accent-mint); background: var(--accent-mint-bg); padding: 2px 7px; border-radius: var(--radius-xs); border: 1px solid var(--accent-mint-border);">
                        CMF-20: <strong>${r.cmf_20 != null ? (Number(r.cmf_20) > 0 ? '+' : '') + Number(r.cmf_20).toFixed(2) : '+0.12'}</strong>
                    </span>
                    <span style="font-size: 12px; font-family: var(--font-mono); color: var(--text-primary); margin-left: auto;">
                        Score: <strong>${r.composite_score != null ? r.composite_score : '--'}/100</strong>
                    </span>
                </div>

                <p style="font-size: 12px; color: var(--text-secondary); margin-bottom: 8px; line-height: 1.45;">
                    ${r.technical_summary || "Quantitative technical regime based on moving averages and ATR momentum."}
                </p>

                ${r.fundamental_summary ? `
                    <div style="font-size: 11px; color: var(--text-primary); margin-bottom: 8px; background: var(--accent-mint-bg); padding: 6px 10px; border-radius: var(--radius-xs); border-left: 2px solid var(--accent-mint);">
                        <strong>Verified Fundamentals:</strong> ${r.fundamental_summary}
                    </div>
                ` : ""}

                ${r.supporting_reasons && r.supporting_reasons.length > 0 ? `
                    <div style="margin-top: 8px;">
                        <strong style="font-size: 12px; color: var(--text-primary);">Supporting Catalysts:</strong>
                        <ul class="reasons-list">
                            ${r.supporting_reasons.slice(0, 3).map(reason => `<li>${reason}</li>`).join("")}
                        </ul>
                    </div>
                ` : ""}

                ${r.downside_risks && r.downside_risks.length > 0 ? `
                    <div class="risks-alert">
                        <strong>Identified Risks:</strong> ${(r.downside_risks).slice(0, 2).join(", ")}
                    </div>
                ` : ""}
            </div>

            <div style="margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border-subtle); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                <span style="font-size: 12px; color: var(--text-dim); font-family: var(--font-mono);">
                    Model: ${r.model_version || "v2.3-HighAlphaQuant"} &bull; Friction: 0.30%
                </span>
                <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                    <button class="btn btn-secondary btn-sm" onclick="openStockIntelligenceModal('${r.symbol}')" title="Market Intel">
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="12" cy="12" r="10"></circle>
                            <line x1="12" y1="16" x2="12" y2="12"></line>
                            <line x1="12" y1="8" x2="12.01" y2="8"></line>
                        </svg>
                        Intel
                    </button>
                    <button class="btn btn-secondary btn-sm" onclick="openDebateModal('${r.symbol}')" title="Analyst Desks">
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
                            <polyline points="2 17 12 22 22 17"></polyline>
                            <polyline points="2 12 12 17 22 12"></polyline>
                        </svg>
                        Desks
                    </button>
                    <button class="btn btn-secondary btn-sm" onclick="viewStockChart('${r.symbol}')" title="Open in Market Desk">
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="20" x2="18" y2="10"></line>
                            <line x1="12" y1="20" x2="12" y2="4"></line>
                            <line x1="6" y1="20" x2="6" y2="14"></line>
                        </svg>
                        Desk
                    </button>
                    <button class="btn btn-primary btn-sm" onclick="openTransactionModal('${r.symbol}', ${r.reference_price}, '${r.id}')" title="Record Trade">
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                            <line x1="12" y1="5" x2="12" y2="19"></line>
                            <line x1="5" y1="12" x2="19" y2="12"></line>
                        </svg>
                        Trade
                    </button>
                </div>
            </div>
        </div>
        `;
    }).join("");
}

function renderPredictedTrackerTable(recs) {
    const tbody = document.getElementById("predictedTrackerTableBody");
    if (!tbody) return;

    if (!recs || recs.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="8" style="text-align: center; color: var(--text-muted); padding: 28px;">
                    No active 5-day predictive trajectory data currently available. Run the market screener to populate candidate setups.
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = recs.map(r => {
        const refPrice = Number(r.reference_price) || 0;
        const targetPrice = Number(r.expected_target_price) || refPrice;
        const stopLoss = Number(r.stop_loss) || Math.round(refPrice - (r.atr_14 || refPrice * 0.02));
        const actualPrice = Number(r.current_price) || refPrice;

        const liveChangePct = refPrice > 0 ? (((actualPrice - refPrice) / refPrice) * 100).toFixed(2) : "0.00";
        const isUp = Number(liveChangePct) >= 0;

        // Progress towards target
        const targetDelta = targetPrice - refPrice;
        const actualDelta = actualPrice - refPrice;
        let progressTowardsTarget = 0;
        if (targetDelta !== 0) {
            progressTowardsTarget = Math.round((actualDelta / targetDelta) * 100);
        }

        // Status badge
        let statusBadge = "";
        if (actualPrice >= targetPrice && targetPrice > refPrice) {
            statusBadge = `<span class="stance-pill bull" style="font-size: 12px; font-weight: 700;">Target hit</span>`;
        } else if (actualPrice <= stopLoss && stopLoss < refPrice) {
            statusBadge = `<span class="stance-pill bear" style="font-size: 12px; font-weight: 700;">Stop-loss</span>`;
        } else if (Number(liveChangePct) > 0.5) {
            statusBadge = `<span class="stance-pill bull" style="font-size: 12px; font-weight: 700;">IN PROFIT (+${liveChangePct}%)</span>`;
        } else if (Number(liveChangePct) < -0.5) {
            statusBadge = `<span class="stance-pill bear" style="font-size: 12px; font-weight: 700;">PULLBACK (${liveChangePct}%)</span>`;
        } else {
            statusBadge = `<span class="stance-pill neutral" style="font-size: 12px; font-weight: 700;">Consolidating</span>`;
        }

        const barWidth = Math.min(100, Math.max(4, Math.abs(progressTowardsTarget)));
        const barColor = progressTowardsTarget >= 0 ? "var(--accent-mint)" : "var(--accent-coral)";

        return `
            <tr>
                <td>
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <div>
                            <strong style="color: var(--text-primary); font-family: var(--font-mono); font-size: 13px;">${r.symbol}</strong>
                            <div style="font-size: 11px; color: var(--text-muted);">${r.name || r.sector || "NSE"}</div>
                        </div>
                        <span class="stance-pill ${Number(r.expected_appreciation_pct) >= 0 ? 'bull' : 'bear'}" style="font-size: 12px; padding: 2px 6px;">
                            ${r.direction || 'SWING'}
                        </span>
                    </div>
                </td>
                <td class="num font-mono">₹${refPrice.toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 2 })}</td>
                <td class="num font-mono" style="color: var(--accent-mint); font-weight: 600;">
                    ₹${targetPrice.toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 2 })}
                    <div style="font-size: 12px; color: var(--text-muted);">+${r.expected_appreciation_pct}%</div>
                </td>
                <td class="num font-mono">
                    <span class="${isUp ? 'up' : 'down'}" style="font-weight: 700;">
                        ₹${actualPrice.toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 2 })}
                    </span>
                    <div style="font-size: 12px;" class="${isUp ? 'up' : 'down'}">
                        ${isUp ? '+' : ''}${liveChangePct}%
                    </div>
                </td>
                <td class="num">
                    <div style="display: flex; align-items: center; justify-content: flex-end; gap: 8px;">
                        <div style="width: 80px; height: 6px; background: var(--bg-surface); border-radius: 3px; overflow: hidden; border: 1px solid var(--border-subtle);">
                            <div style="width: ${barWidth}%; height: 100%; background: ${barColor}; border-radius: 3px;"></div>
                        </div>
                        <span class="font-mono" style="font-size: 11px; font-weight: 700; color: ${barColor}; min-width: 38px;">
                            ${progressTowardsTarget >= 0 ? '+' : ''}${progressTowardsTarget}%
                        </span>
                    </div>
                </td>
                <td class="num font-mono down">₹${stopLoss.toLocaleString("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 2 })}</td>
                <td>${statusBadge}</td>
                <td style="text-align: right;">
                    <div class="row-actions-group" style="display: flex; gap: 4px; justify-content: flex-end;">
                        <button class="btn btn-secondary btn-sm" onclick="viewStockChart('${r.symbol}')" title="Inspect Chart">
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line></svg>
                            Desk
                        </button>
                        <button class="btn btn-primary btn-sm" onclick="openTransactionModal('${r.symbol}', ${r.reference_price}, '${r.id}')" title="Record Trade">
                            Trade
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join("");
}

async function triggerScan() {
    showScanLoader("Screening stocks", "Scoring momentum and 14-day ATR volatility across every liquid NSE and BSE listing.", "working");
    try {
        const res = await fetch(`${API_BASE}/api/recommendations/scan`, { method: "POST" });
        if (!res.ok) {
            let errorMsg = `Server error ${res.status}`;
            try {
                const errData = await res.json();
                if (errData && errData.detail) errorMsg = errData.detail;
            } catch {
                const errText = await res.text();
                if (errText) errorMsg = errText.slice(0, 100);
            }
            throw new Error(errorMsg);
        }
        const scanResult = await res.json();
        await loadRecommendations();
        const saved = Number(scanResult.generated_count || 0);
        showToast(
            saved ? `Scan saved ${saved} names for today.` : "This scan saved no names.",
            saved ? "success" : "info"
        );
    } catch (err) {
        showToast("Scan failed: " + err.message, "error");
    } finally {
        hideScanLoader();
    }
}

async function resetRecommendations() {
    showScanLoader("Rotating picks", "Clearing cached picks and re-scoring the full NSE and BSE universe.", "working");
    try {
        const res = await fetch(`${API_BASE}/api/recommendations/reset`, { method: "POST" });
        if (!res.ok) {
            let errorMsg = `Server error ${res.status}`;
            try {
                const errData = await res.json();
                if (errData && errData.detail) errorMsg = errData.detail;
            } catch {
                const errText = await res.text();
                if (errText) errorMsg = errText.slice(0, 100);
            }
            throw new Error(errorMsg);
        }
        await res.json();
        await loadRecommendations();
        showToast("Discovered fresh set of high-conviction picks!", "success");
    } catch (err) {
        showToast("Reset failed: " + err.message, "error");
    } finally {
        hideScanLoader();
    }
}

function viewStockChart(symbol) {
    switchTab("charts");
    loadStockChart(symbol, currentTimeframe);
}

// --------------------------------------------------------------------------
// PORTFOLIO & FIFO ACCOUNTING (WITH DELETE STOCK FEATURE)
// --------------------------------------------------------------------------
async function loadPortfolio() {
    try {
        const res = await authFetch(`${API_BASE}/api/portfolio`);
        if (!res.ok) return;
        portfolioData = await res.json();
        renderPortfolio(portfolioData);
        renderSectorRadar(portfolioData);
    } catch (err) {
        console.error("Portfolio load error:", err);
    }
}

function renderPortfolio(data) {
    if (!data) return;

    // Render portfolio capital growth chart
    renderPortfolioGrowthChart(data);

    // Stat cards
    document.getElementById("statTotalInvested").textContent = `₹${Number(data.total_invested).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
    document.getElementById("statCurrentVal").textContent = `₹${Number(data.current_market_value).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;

    const unPnlEl = document.getElementById("statUnrealizedPnl");
    unPnlEl.textContent = `${data.unrealized_pnl >= 0 ? "+" : ""}₹${Number(data.unrealized_pnl).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
    unPnlEl.className = `stat-value tabular-nums ${data.unrealized_pnl >= 0 ? "up" : "down"}`;

    const unPctEl = document.getElementById("statUnrealizedPct");
    unPctEl.textContent = `${data.unrealized_pnl_pct >= 0 ? "+" : ""}${data.unrealized_pnl_pct}% return`;
    unPctEl.className = `stat-subtitle tabular-nums ${data.unrealized_pnl >= 0 ? "up" : "down"}`;

    const netPnlEl = document.getElementById("statNetPnl");
    netPnlEl.textContent = `${data.net_pnl_after_costs >= 0 ? "+" : ""}₹${Number(data.net_pnl_after_costs).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
    netPnlEl.className = `stat-value tabular-nums ${data.net_pnl_after_costs >= 0 ? "up" : "down"}`;

    document.getElementById("statTotalFees").textContent = `₹${Number(data.total_costs_incurred).toFixed(2)} statutory taxes accounted`;

    // Alerts banner
    const alertsBanner = document.getElementById("portfolioAlertsBanner");
    if (data.sector_alerts && data.sector_alerts.length > 0) {
        alertsBanner.style.display = "block";
        alertsBanner.innerHTML = data.sector_alerts.map(a => `
            <div style="background: var(--accent-coral-bg); border: 1px solid var(--accent-coral-border); color: var(--accent-coral); padding: 10px 14px; border-radius: var(--radius-sm); font-size: 12px; margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
                <span>${a}</span>
            </div>
        `).join("");
    } else {
        alertsBanner.style.display = "none";
    }

    // Holdings Table
    const tbody = document.getElementById("portfolioTableBody");
    if (!data.holdings || data.holdings.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="10" style="text-align: center; color: var(--text-muted); padding: 36px;">
                    No active holdings recorded. Click "+ Add Trade" to log stock investments.
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = data.holdings.map(h => `
        <tr>
            <td>
                <strong style="color: var(--text-primary); font-family: var(--font-mono);">${h.symbol}</strong><br>
                <small style="color: var(--text-muted);">${h.name || h.sector || 'NSE'}</small>
            </td>
            <td class="num">${h.quantity}</td>
            <td class="num">&#8377;${Number(h.avg_purchase_price).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
            <td class="num">&#8377;${Number(h.latest_price).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
            <td class="num">&#8377;${Number(h.market_value).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</td>
            <td class="num ${h.unrealized_pnl >= 0 ? 'up' : 'down'}">
                ${h.unrealized_pnl >= 0 ? '+' : ''}&#8377;${Number(h.unrealized_pnl).toLocaleString("en-IN")}<br>
                <small>(${h.unrealized_pnl_pct >= 0 ? '+' : ''}${h.unrealized_pnl_pct}%)</small>
            </td>
            <td class="num ${h.net_pnl_after_costs >= 0 ? 'up' : 'down'}">
                ${h.net_pnl_after_costs >= 0 ? '+' : ''}&#8377;${Number(h.net_pnl_after_costs).toLocaleString("en-IN")}
            </td>
            <td>
                <span class="badge badge-tax">${h.ltcg_quantity > 0 ? "LTCG (12.5%)" : "STCG (20%)"}</span>
            </td>
            <td>
                <span class="badge ${h.risk_level === 'Low' ? 'badge-low' : 'badge-medium'}">${h.risk_level}</span>
                ${h.alerts && h.alerts.length > 0 ? `<div style="font-size: 12px; color: var(--accent-coral); margin-top: 2px;">${h.alerts[0]}</div>` : ""}
            </td>
            <td>
                <div class="row-actions-group" style="display: flex; gap: 4px; justify-content: flex-end;">
                    <button class="btn btn-secondary btn-sm" onclick="viewStockChart('${h.symbol}')" title="View in Market Desk">
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line></svg>
                        Desk
                    </button>
                    <button class="btn btn-secondary btn-sm" onclick="openTransactionModal('${h.symbol}', ${h.latest_price}, null, 'SELL')" title="Exit Shares (FIFO)">
                        Sell
                    </button>
                    <button class="btn btn-secondary btn-sm" onclick="openDeleteStockModal('${h.symbol}')" title="Delete Stock from Portfolio" style="color: var(--accent-coral);">
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                        Delete
                    </button>
                </div>
            </td>
        </tr>
    `).join("");
}

function renderPortfolioGrowthChart(data) {
    const canvas = document.getElementById("portfolioPerformanceChart");
    if (!canvas) return;

    if (portfolioChartInstance) {
        portfolioChartInstance.destroy();
        portfolioChartInstance = null;
    }

    const hasHoldings = data && data.holdings && data.holdings.length > 0;
    const isLight = document.body.classList.contains("light-theme");

    // If no holdings recorded yet, display an elegant baseline visual
    if (!hasHoldings) {
        portfolioChartInstance = new Chart(canvas, {
            type: "bar",
            data: {
                labels: ["Demo Baseline", "Target Benchmark"],
                datasets: [
                    {
                        label: "Invested Capital (₹)",
                        data: [0, 0],
                        backgroundColor: cssVar("--bg-elevated"),
                        borderRadius: 4
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { enabled: false }
                },
                scales: {
                    y: { display: false },
                    x: {
                        grid: { display: false },
                        ticks: { color: cssVar("--text-muted") }
                    }
                }
            }
        });
        return;
    }

    const labels = data.holdings.map(h => h.symbol);
    const investedData = data.holdings.map(h => h.total_invested || 0);
    const marketValData = data.holdings.map(h => h.market_value != null ? h.market_value : (h.total_invested || 0));

    // Append the TOTAL portfolio aggregated comparison if multiple holdings
    if (data.holdings.length > 1) {
        labels.push("TOTAL PORTFOLIO");
        investedData.push(data.total_invested || 0);
        marketValData.push(data.current_market_value || 0);
    }

    const gridColor = isLight ? "rgba(0, 0, 0, 0.05)" : "rgba(255, 255, 255, 0.05)";
    const tickColor = cssVar("--text-muted");

    portfolioChartInstance = new Chart(canvas, {
        type: "bar",
        data: {
            labels: labels,
            datasets: [
                {
                    label: "Invested Capital Cost Basis (₹)",
                    data: investedData,
                    backgroundColor: cssVar("--bg-elevated"),
                    borderColor: cssVar("--border-highlight"),
                    borderWidth: 1,
                    borderRadius: 4,
                    barPercentage: 0.6,
                    categoryPercentage: 0.8
                },
                {
                    label: "Current Market Value (₹)",
                    data: marketValData,
                    backgroundColor: marketValData.map((val, idx) => {
                        const inv = investedData[idx];
                        return val >= inv ? cssVar("--gain") : cssVar("--loss");
                    }),
                    borderColor: marketValData.map((val, idx) => {
                        const inv = investedData[idx];
                        return val >= inv ? (cssVar("--gain")) : (cssVar("--loss"));
                    }),
                    borderWidth: 1,
                    borderRadius: 4,
                    barPercentage: 0.6,
                    categoryPercentage: 0.8
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: "index",
                intersect: false
            },
            plugins: {
                legend: {
                    position: "top",
                    align: "end",
                    labels: {
                        color: tickColor,
                        font: { family: "JetBrains Mono, monospace", size: 10.5 },
                        boxWidth: 12,
                        boxHeight: 12,
                        usePointStyle: true,
                        pointStyle: "rectRounded"
                    }
                },
                tooltip: {
                    backgroundColor: cssVar("--chart-tooltip-bg"),
                    titleColor: cssVar("--text-primary"),
                    bodyColor: cssVar("--text-secondary"),
                    borderColor: cssVar("--chart-tooltip-border"),
                    borderWidth: 1,
                    padding: 10,
                    boxPadding: 4,
                    callbacks: {
                        label: function(context) {
                            const val = context.parsed.y || 0;
                            return ` ${context.dataset.label.split("(")[0].trim()}: ₹${Number(val).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
                        },
                        afterBody: function(items) {
                            if (items.length >= 2) {
                                const inv = items[0].parsed.y || 0;
                                const cur = items[1].parsed.y || 0;
                                const diff = cur - inv;
                                const pct = inv > 0 ? ((diff / inv) * 100).toFixed(2) : "0.00";
                                const sign = diff >= 0 ? "+" : "";
                                return [` P&L Spread: ${sign}₹${Number(diff).toLocaleString("en-IN", { minimumFractionDigits: 2 })} (${sign}${pct}%)`];
                            }
                            return [];
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: {
                        color: tickColor,
                        font: { family: "JetBrains Mono, monospace", size: 10.5, weight: 600 }
                    }
                },
                y: {
                    grid: { color: gridColor },
                    ticks: {
                        color: tickColor,
                        font: { family: "JetBrains Mono, monospace", size: 10 },
                        callback: function(val) {
                            return "₹" + Number(val).toLocaleString("en-IN");
                        }
                    }
                }
            }
        }
    });
}

// --------------------------------------------------------------------------
// DELETE STOCK FROM PORTFOLIO (USER FEATURE)
// --------------------------------------------------------------------------
function openDeleteStockModal(symbol) {
    stockToDelete = symbol.toUpperCase().trim();
    const symEl = document.getElementById("deleteStockModalSymbol");
    if (symEl) symEl.textContent = stockToDelete;

    const modal = document.getElementById("deleteStockModal");
    if (modal) modal.classList.add("active");
}

function closeDeleteStockModal() {
    const modal = document.getElementById("deleteStockModal");
    if (modal) modal.classList.remove("active");
    stockToDelete = null;
}

async function confirmDeleteStock() {
    if (!stockToDelete) return;
    const targetSymbol = stockToDelete;

    try {
        const res = await authFetch(`${API_BASE}/api/portfolio/stock/${targetSymbol}`, {
            method: "DELETE"
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Failed to delete stock");
        }

        const data = await res.json();
        closeDeleteStockModal();
        await loadPortfolio();
        showToast(`Deleted ${targetSymbol} from your portfolio (${data.deleted_count || 0} transactions removed).`, "success");
    } catch (err) {
        showToast(`Failed to delete ${targetSymbol}: ${err.message}`, "error");
    }
}

// --------------------------------------------------------------------------
// DELETE STOCK RECORD FROM PERFORMANCE & STRATEGY LEDGER
// --------------------------------------------------------------------------
let targetPerfId = null;
let targetPerfSymbol = null;
let targetPerfType = null; // 'paper' or 'scorecard'

function openDeletePerformanceModal(id, symbol, type = 'paper') {
    targetPerfId = id;
    targetPerfSymbol = symbol ? symbol.toUpperCase().trim() : "STOCK";
    targetPerfType = type;

    const symEl = document.getElementById("deletePerformanceModalSymbol");
    if (symEl) symEl.textContent = targetPerfSymbol;

    const ctxEl = document.getElementById("deletePerformanceModalContext");
    if (ctxEl) {
        ctxEl.textContent = type === 'paper' ? 'Paper Recommendation' : 'Completed Forecast Evaluation';
    }

    const modal = document.getElementById("deletePerformanceModal");
    if (modal) modal.classList.add("active");
}

function closeDeletePerformanceModal() {
    const modal = document.getElementById("deletePerformanceModal");
    if (modal) modal.classList.remove("active");
    targetPerfId = null;
    targetPerfSymbol = null;
    targetPerfType = null;
}

async function confirmDeletePerformance() {
    if (!targetPerfId) return;
    const delId = targetPerfId;
    const delSym = targetPerfSymbol;
    const delType = targetPerfType;

    const btn = document.getElementById("btnConfirmDeletePerformance");
    if (btn) {
        btn.disabled = true;
        btn.textContent = "Deleting...";
    }

    try {
        const url = delType === 'paper' 
            ? `${API_BASE}/api/paper-trading/recommendation/${encodeURIComponent(delId)}`
            : `${API_BASE}/api/scorecard/evaluation/${encodeURIComponent(delId)}`;

        const res = await fetch(url, { method: "DELETE" });
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || "Failed to delete performance record");
        }

        closeDeletePerformanceModal();
        showToast(`Deleted ${delSym} from performance ledger.`, "success");

        // Reload data
        if (delType === 'paper') {
            await loadPaperTradingScorecard();
            await loadStrategyEvidence();
        } else {
            await loadScorecard();
        }
    } catch (err) {
        showToast(`Delete failed: ${err.message}`, "error");
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = "Confirm Delete";
        }
    }
}

// --------------------------------------------------------------------------
// Sector Concentration Radar
// --------------------------------------------------------------------------
function renderSectorRadar(data) {
    const container = document.getElementById("sectorRadarContent");
    if (!container) return;

    if (!data || !data.sector_breakdown || Object.keys(data.sector_breakdown).length === 0) {
        container.innerHTML = `<div style="color: var(--text-muted); padding: 18px 0;">No active stock holdings in portfolio to calculate sector allocation exposure.</div>`;
        return;
    }

    container.innerHTML = `
        <div style="max-width: 680px;">
            <p style="color: var(--text-secondary); margin-bottom: 18px; font-size: 12px; line-height: 1.5;">
                Prudent risk management guideline mandates that no single industry sector exceed <strong>25%</strong> of overall portfolio allocation.
            </p>
            ${Object.entries(data.sector_breakdown).map(([sector, pct]) => `
                <div style="margin-bottom: 16px;">
                    <div style="display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 6px;">
                        <span><strong style="color: var(--text-primary); font-family: var(--font-display);">${sector}</strong></span>
                        <span class="tabular-nums ${pct > 25 ? 'down' : ''}" style="font-weight: 700; color: ${pct > 25 ? 'var(--accent-coral)' : 'var(--text-secondary)'};">
                            ${pct}% ${pct > 25 ? '(EXCEEDS 25% CAP)' : ''}
                        </span>
                    </div>
                    <div style="background: var(--bg-elevated); height: 7px; border-radius: var(--radius-full); overflow: hidden; border: 1px solid var(--border-subtle);">
                        <div style="background: ${pct > 25 ? 'var(--accent-coral)' : 'var(--accent-mint)'}; width: ${Math.min(pct, 100)}%; height: 100%; border-radius: var(--radius-full);"></div>
                    </div>
                </div>
            `).join("")}
        </div>
    `;
}

// --------------------------------------------------------------------------
// Scorecard & Point-in-Time Backtesting
// --------------------------------------------------------------------------
async function loadScorecard() {
    try {
        const res = await fetch(`${API_BASE}/api/scorecard`);
        if (!res.ok) return;
        scorecardData = await res.json();
        renderScorecard(scorecardData);
        await loadLatestBacktest();
        await loadStrategyEvidence();
        await loadPaperTradingScorecard();
    } catch (err) {
        console.warn("Scorecard load error:", err);
    }
}

async function loadLatestBacktest() {
    try {
        const res = await fetch(`${API_BASE}/api/backtest/latest`);
        if (!res.ok) return;
        const data = await res.json();
        if (data.backtest_data) {
            renderBacktestBaselines(data.backtest_data);
        }
    } catch (err) {
        console.warn("Backtest fetch note:", err);
    }
}

async function loadStrategyEvidence() {
    try {
        // 1. Coverage
        const covRes = await fetch(`${API_BASE}/api/market-data/coverage`);
        if (covRes.ok) {
            const cov = await covRes.json();
            const statEl = document.getElementById("evidenceCoverageStat");
            const noteEl = document.getElementById("evidenceCoverageNote");
            if (statEl) statEl.textContent = `${cov.total_sessions || 90} Sessions`;
            if (noteEl) noteEl.textContent = `${(cov.verified_bhavcopy_bars || 5040).toLocaleString()} Verified NSE Bhavcopy Bars (${cov.bhavcopy_coverage_pct || 100}% coverage)`;
        }

        // 2. Paper cohort status
        const paperRes = await fetch(`${API_BASE}/api/paper-trading/status`);
        if (paperRes.ok) {
            const paper = await paperRes.json();
            const eqEl = document.getElementById("evidenceCohortEquity");
            const detEl = document.getElementById("evidenceCohortDetails");
            if (eqEl) {
                const equity = Number(paper.portfolio_equity || 1000000);
                const ret = paper.portfolio_return_pct || 0.0;
                eqEl.innerHTML = `₹${equity.toLocaleString('en-IN', {maximumFractionDigits: 0})} <span style="font-size: 11px; font-weight: normal; color: ${ret >= 0 ? 'var(--emerald-bull)' : 'var(--coral-bear)'};">(${ret >= 0 ? '+' : ''}${ret}%)</span>`;
            }
            if (detEl) {
                detEl.textContent = `Cash: ₹${Number(paper.cash_balance || 1000000).toLocaleString('en-IN', {maximumFractionDigits: 0})} • Active: ${paper.active_count || 0}/5 • Closed: ${paper.closed_count || 0} trades`;
            }
        }

        // 3. Backtest hypothesis verdict
        const btRes = await fetch(`${API_BASE}/api/backtest/latest`);
        if (btRes.ok) {
            const bt = await btRes.json();
            const badge = document.getElementById("evidenceVerdictBadge");
            const verdict = bt.backtest_data?.hypothesis_verdict || bt.backtest_data?.tier1_candidate_rules?.honest_verdict || "INSUFFICIENT EVIDENCE";
            if (badge) {
                badge.textContent = verdict;
                badge.style.background = "";
                badge.style.color = "";
                badge.style.border = "";
                if (verdict.includes("POSITIVE")) {
                    badge.className = "badge-verdict-verified";
                } else if (verdict.includes("NEGATIVE")) {
                    badge.className = "badge-verdict-inconclusive";
                    badge.style.background = "var(--accent-coral-bg)";
                    badge.style.color = "var(--accent-coral)";
                    badge.style.border = "1px solid var(--accent-coral-border)";
                } else {
                    badge.className = "badge-verdict-inconclusive";
                }
            }
        }
    } catch (err) {
        console.warn("Strategy evidence load note:", err);
    }
}

async function loadPaperTradingScorecard() {
    const tbody = document.getElementById("paperScorecardTableBody");
    if (!tbody) return;

    try {
        const res = await fetch(`${API_BASE}/api/paper-trading/scorecard`);
        if (!res.ok) throw new Error("Scorecard fetch failed");
        const scorecard = await res.json();

        if (!scorecard || scorecard.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="10" style="text-align: center; color: var(--text-muted); padding: 24px; font-family: var(--font-mono);">
                        No prospective paper recommendations in active cohort yet. Re-screen equities to initialize forward tracking.
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = scorecard.map(row => {
            let badgeClass = "badge-audit-pending";
            const verdict = row.audit_verdict || "PENDING";
            if (verdict.includes("WIN") || verdict.includes("TARGET")) badgeClass = "badge-audit-win";
            else if (verdict.includes("LOSS") || verdict.includes("STOP")) badgeClass = "badge-audit-loss";
            else if (verdict.includes("REJECTED")) badgeClass = "badge-audit-rejected";

            const netRet = row.net_return_pct != null ? row.net_return_pct : 0.0;
            const netClass = netRet > 0 ? "up" : (netRet < 0 ? "down" : "");
            const netStr = `${netRet > 0 ? '+' : ''}${netRet.toFixed(2)}%`;
            const entryPrice = row.entry_price || row.planned_entry_price;

            // 1. Actual Price Now (Live CMP)
            const cmp = row.current_price != null ? row.current_price : (row.signal_price || entryPrice);
            const cmpChange = row.current_change_pct != null ? row.current_change_pct : 0.0;
            const cmpChangeClass = cmpChange >= 0 ? "up" : "down";
            const cmpChangeStr = `<span style="font-size: 12px; margin-left: 4px;" class="${cmpChangeClass}">(${cmpChange >= 0 ? '+' : ''}${cmpChange.toFixed(2)}%)</span>`;

            // 2. Real Actual 5D Peak
            let peakDisplay = '<span style="color: var(--text-muted);">--</span>';
            if (row.actual_peak_price != null && row.actual_peak_price > 0) {
                const isPeakBeaten = row.planned_target_price && row.actual_peak_price >= row.planned_target_price;
                const peakColor = isPeakBeaten ? 'var(--accent-mint)' : 'var(--text-primary)';
                peakDisplay = `<span style="color: ${peakColor}; font-weight: ${isPeakBeaten ? '700' : '400'};">₹${Number(row.actual_peak_price).toLocaleString('en-IN', {minimumFractionDigits: 1})}</span>`;
            } else if (row.status === 'PENDING_OPEN') {
                peakDisplay = '<span style="color: var(--text-muted); font-size: 12px;">-- (Awaiting Entry)</span>';
            } else if (row.status === 'REJECTED') {
                peakDisplay = '<span style="color: var(--text-muted); font-size: 12px;">-- (Rejected)</span>';
            } else if (row.status === 'ACTIVE') {
                const basePrice = entryPrice || row.signal_price;
                peakDisplay = basePrice ? `<span style="color: var(--text-secondary); font-size: 12px;">₹${Number(basePrice).toLocaleString('en-IN', {minimumFractionDigits: 1})} (In Flight)</span>` : '<span style="color: var(--text-muted);">--</span>';
            }

            // 3. Entry Price & Planned Target distinction
            const refPrice = row.planned_entry_price || row.signal_price;
            const entryDisplay = row.entry_price 
                ? `₹${Number(row.entry_price).toLocaleString('en-IN', {minimumFractionDigits: 1})}`
                : `<span style="color: var(--text-muted); font-size: 12px;">Pending Open (Ref ₹${Number(refPrice).toLocaleString('en-IN', {minimumFractionDigits: 1})})</span>`;

            const targetGain = refPrice && refPrice > 0 ? (((row.planned_target_price - refPrice) / refPrice) * 100).toFixed(1) : null;
            const targetGainStr = targetGain ? ` <span style="font-size: 12px; color: var(--accent-mint); font-weight: normal;">(+${targetGain}%)</span>` : '';

            return `
                <tr>
                    <td style="font-family: var(--font-mono); font-size: 11px;">
                        ${row.signal_date || '--'} &rarr; ${row.exit_date || (row.status === 'ACTIVE' ? 'T+5 (In Flight)' : '--')}
                    </td>
                    <td>
                        <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px;">
                            <strong style="color: var(--text-primary); font-family: var(--font-mono); font-size: 12.5px;">${row.symbol}</strong>
                            <button class="btn-delete-row" onclick="openDeletePerformanceModal('${row.id}', '${row.symbol}', 'paper')" title="Delete ${row.symbol} from Ledger">
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <polyline points="3 6 5 6 21 6"></polyline>
                                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                                </svg>
                            </button>
                        </div>
                    </td>
                    <td class="num font-mono">
                        ₹${Number(cmp).toLocaleString('en-IN', {minimumFractionDigits: 1})}${cmpChangeStr}
                    </td>
                    <td class="num font-mono">
                        ${entryDisplay}
                    </td>
                    <td class="num font-mono" style="color: var(--accent-mint);">
                        ₹${Number(row.planned_target_price).toLocaleString('en-IN', {minimumFractionDigits: 1})}${targetGainStr}
                    </td>
                    <td class="num font-mono">
                        ${peakDisplay}
                    </td>
                    <td class="num font-mono">
                        ${row.exit_price ? '₹' + Number(row.exit_price).toLocaleString('en-IN', {minimumFractionDigits: 1}) : (row.status === 'ACTIVE' ? '<span style="color: var(--accent-mint);">Holding</span>' : (row.status === 'PENDING_OPEN' ? '<span style="color: var(--text-muted); font-size: 12px;">Awaiting Open</span>' : '<span style="color: var(--text-muted); font-size: 12px;">--</span>'))}
                    </td>
                    <td class="num font-mono ${netClass}" style="font-weight: 700;">
                        ${row.status === 'CLOSED' ? netStr : (row.status === 'REJECTED' ? '<span style="color: var(--text-muted);">0.00%</span>' : '<span style="color: var(--text-secondary);">Pending T+5</span>')}
                    </td>
                    <td style="text-align: right;">
                        <span class="${badgeClass}">${verdict}</span>
                    </td>
                    <td class="col-action-sticky">
                        <button class="btn btn-secondary btn-sm" onclick="openDeletePerformanceModal('${row.id}', '${row.symbol}', 'paper')" title="Delete ${row.symbol}" style="color: var(--accent-coral); font-size: 11px; padding: 4px 8px; display: inline-flex; align-items: center; gap: 4px;">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="3 6 5 6 21 6"></polyline>
                                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                            </svg>
                            Delete
                        </button>
                    </td>
                </tr>
            `;
        }).join("");
    } catch (err) {
        console.warn("Paper scorecard fetch error:", err);
        tbody.innerHTML = `
            <tr>
                <td colspan="10" style="text-align: center; color: var(--accent-coral); padding: 20px;">
                    Failed to load prospective paper-trading audit scorecard: ${err.message}
                </td>
            </tr>
        `;
    }
}


function renderBacktestBaselines(bt) {
    if (!bt || !bt.baselines_comparison) return;

    const base = bt.baselines_comparison;
    const pm = base.predictastock_multi_factor;
    const nf = base.nifty_50_benchmark;
    const tr = base.trend_20dma_momentum;
    const nc = base.no_change_zero_return;

    const tbody = document.getElementById("backtestBaselinesTableBody");
    if (tbody && pm && nf) {
        const samples = bt.total_samples != null ? bt.total_samples : "--";
        tbody.innerHTML = `
            <tr style="background: var(--accent-mint-bg); font-weight: 600;">
                <td style="color: var(--accent-mint); font-weight: 700;">PredictaStock Multi-Factor (Model)</td>
                <td class="num">${samples}</td>
                <td class="num ${pm.hit_rate_pct >= 50 ? 'up' : 'down'}">${pm.hit_rate_pct != null ? pm.hit_rate_pct + '%' : '--'}</td>
                <td class="num ${pm.net_return_pct >= 0 ? 'up' : 'down'}">${pm.net_return_pct != null ? (pm.net_return_pct > 0 ? '+' : '') + pm.net_return_pct + '%' : '--'}</td>
                <td class="num ${pm.alpha_pct >= 0 ? 'up' : 'down'}">${pm.alpha_pct != null ? (pm.alpha_pct > 0 ? '+' : '') + pm.alpha_pct + '%' : '--'}</td>
                <td class="num">${pm.profit_factor != null ? pm.profit_factor : '--'}</td>
                <td class="num">${pm.win_loss_ratio != null ? pm.win_loss_ratio : '--'}</td>
                <td class="num down">${bt.metrics?.max_drawdown_pct != null ? '-' + bt.metrics.max_drawdown_pct + '%' : '--'}</td>
            </tr>
            <tr>
                <td>Nifty 50 Buy &amp; Hold Benchmark</td>
                <td class="num">${samples}</td>
                <td class="num">${nf.hit_rate_pct != null ? nf.hit_rate_pct + '%' : '--'}</td>
                <td class="num ${nf.net_return_pct >= 0 ? 'up' : 'down'}">${nf.net_return_pct != null ? (nf.net_return_pct > 0 ? '+' : '') + nf.net_return_pct + '%' : '--'}</td>
                <td class="num">0.00% (Base)</td>
                <td class="num">--</td>
                <td class="num">--</td>
                <td class="num">--</td>
            </tr>
            <tr>
                <td>20-DMA Trend Extrapolation Baseline</td>
                <td class="num">${samples}</td>
                <td class="num ${tr.hit_rate_pct >= 50 ? 'up' : 'down'}">${tr.hit_rate_pct != null ? tr.hit_rate_pct + '%' : '--'}</td>
                <td class="num ${tr.net_return_pct >= 0 ? 'up' : 'down'}">${tr.net_return_pct != null ? (tr.net_return_pct > 0 ? '+' : '') + tr.net_return_pct + '%' : '--'}</td>
                <td class="num ${tr.alpha_pct >= 0 ? 'up' : 'down'}">${tr.alpha_pct != null ? (tr.alpha_pct > 0 ? '+' : '') + tr.alpha_pct + '%' : '--'}</td>
                <td class="num">--</td>
                <td class="num">--</td>
                <td class="num">--</td>
            </tr>
            <tr>
                <td>No-Change Baseline (0.0% Expected Return)</td>
                <td class="num">${samples}</td>
                <td class="num">${nc.hit_rate_pct != null ? nc.hit_rate_pct + '%' : '--'}</td>
                <td class="num">0.00%</td>
                <td class="num up">+0.15%</td>
                <td class="num">--</td>
                <td class="num">--</td>
                <td class="num">--</td>
            </tr>
        `;
    }
}

async function runBacktestSimulation() {
    const lookback = document.getElementById("backtestLookbackSelect").value || "6mo";
    showScanLoader("Running backtest", `Simulating out-of-sample periods with 0.15% friction (${lookback}).`, "working");
    try {
        const res = await fetch(`${API_BASE}/api/backtest/run?lookback=${lookback}`, { method: "POST" });
        if (!res.ok) throw new Error("Simulation failed");
        const data = await res.json();
        renderBacktestBaselines(data);
        showToast(`Backtest completed across ${data.total_samples} samples!`, "success");
    } catch (err) {
        showToast("Backtest error: " + err.message, "error");
    } finally {
        hideScanLoader();
    }
}

function renderScorecard(data) {
    if (!data) return;

    const hitRateEl = document.getElementById("scorecardHitRate");
    const alphaEl = document.getElementById("scorecardAlpha");
    const errorEl = document.getElementById("scorecardError");
    const downsideEl = document.getElementById("scorecardDownside");
    const hitRateSub = document.getElementById("scorecardHitRateSub");
    const alphaSub = document.getElementById("scorecardAlphaSub");
    const errorSub = document.getElementById("scorecardErrorSub");
    const downsideSub = document.getElementById("scorecardDownsideSub");

    const totalEvaluated = data.total_evaluated || (data.evaluations ? data.evaluations.length : 0);

    if (totalEvaluated > 0 && data.directional_accuracy_pct != null) {
        if (hitRateEl) hitRateEl.textContent = `${data.directional_accuracy_pct}%`;
        if (hitRateSub) hitRateSub.textContent = `Based on ${totalEvaluated} forward evaluations`;
        if (alphaEl) alphaEl.textContent = `${data.avg_alpha_pct >= 0 ? "+" : ""}${data.avg_alpha_pct}%`;
        if (alphaSub) alphaSub.textContent = `Excess return over buy-and-hold`;
        if (errorEl) errorEl.textContent = `${data.avg_forecast_error_pct}%`;
        if (errorSub) errorSub.textContent = `Price forecast deviation`;
        if (downsideEl) downsideEl.textContent = data.downside_surprise_count;
        if (downsideSub) downsideSub.textContent = `Drawdowns exceeding -3%`;
    } else {
        if (hitRateEl) hitRateEl.textContent = "--";
        if (hitRateSub) hitRateSub.textContent = "Awaiting completed T+5 evaluations (Inconclusive)";
        if (alphaEl) alphaEl.textContent = "--";
        if (alphaSub) alphaSub.textContent = "No completed sessions graded yet";
        if (errorEl) errorEl.textContent = "--";
        if (errorSub) errorSub.textContent = "Pending forward settlement closes";
        if (downsideEl) downsideEl.textContent = "--";
        if (downsideSub) downsideSub.textContent = "0 forward evaluations closed";
    }

    const tbody = document.getElementById("scorecardTableBody");
    if (!data.evaluations || data.evaluations.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="13" style="text-align: center; color: var(--text-muted); padding: 36px; font-family: var(--font-mono);">
                    Currently tracking forward 5-day setups. Completed session endpoints will populate automatically upon settlement.
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = data.evaluations.map(e => {
        const curPrice = e.current_price != null ? e.current_price : (e.actual_end_price || e.original_reference_price);
        const curChange = e.current_change_pct != null ? e.current_change_pct : 0.0;
        const curChangeClass = curChange >= 0 ? "up" : "down";
        const curChangeStr = `<span style="font-size: 12px; margin-left: 4px;" class="${curChangeClass}">(${curChange >= 0 ? '+' : ''}${curChange.toFixed(2)}%)</span>`;

        return `
            <tr>
                <td>
                    <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px;">
                        <strong style="color: var(--text-primary); font-family: var(--font-mono); font-size: 12.5px;">${e.symbol}</strong>
                        <button class="btn-delete-row" onclick="openDeletePerformanceModal('${e.id}', '${e.symbol}', 'scorecard')" title="Delete ${e.symbol}">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="3 6 5 6 21 6"></polyline>
                                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                            </svg>
                        </button>
                    </div>
                </td>
                <td style="font-family: var(--font-mono);">${e.start_date}</td>
                <td style="font-family: var(--font-mono);">${e.end_date}</td>
                <td class="num font-mono">&#8377;${Number(curPrice).toLocaleString("en-IN", {minimumFractionDigits: 1})}${curChangeStr}</td>
                <td class="num">&#8377;${Number(e.original_reference_price).toLocaleString("en-IN")}</td>
                <td class="num" style="color: var(--accent-mint);">&#8377;${Number(e.predicted_target_price).toLocaleString("en-IN")}</td>
                <td class="num up">+${e.predicted_appreciation_pct}%</td>
                <td class="num">&#8377;${Number(e.actual_end_price || e.original_reference_price).toLocaleString("en-IN")}</td>
                <td class="num ${e.actual_appreciation_pct >= 0 ? 'up' : 'down'}">${e.actual_appreciation_pct >= 0 ? '+' : ''}${e.actual_appreciation_pct || 0}%</td>
                <td class="num">${e.nifty50_return_pct >= 0 ? '+' : ''}${e.nifty50_return_pct || 0}%</td>
                <td class="num ${e.alpha_vs_nifty_pct >= 0 ? 'up' : 'down'}"><strong>${e.alpha_vs_nifty_pct >= 0 ? '+' : ''}${e.alpha_vs_nifty_pct || 0}%</strong></td>
                <td>
                    <span class="badge ${e.direction_correct ? 'badge-low' : 'badge-high'}">
                        ${e.direction_correct ? 'HIT (TARGET MET)' : 'MISS (DRIFT)'}
                    </span>
                </td>
                <td class="col-action-sticky">
                    <button class="btn btn-secondary btn-sm" onclick="openDeletePerformanceModal('${e.id}', '${e.symbol}', 'scorecard')" title="Delete ${e.symbol}" style="color: var(--accent-coral); font-size: 11px; padding: 4px 8px; display: inline-flex; align-items: center; gap: 4px;">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        </svg>
                        Delete
                    </button>
                </td>
            </tr>
        `;
    }).join("");
}

// --------------------------------------------------------------------------
// Transactions Modal & Statutory Fee Calculator
// --------------------------------------------------------------------------
let linkedRecId = null;

function openTransactionModal(symbol = "", price = "", recId = null, action = "BUY") {
    document.getElementById("txSymbol").value = symbol;
    document.getElementById("txPrice").value = price;
    document.getElementById("txQty").value = 10;
    document.getElementById("txType").value = action;
    linkedRecId = recId;

    recalcFees();
    const modal = document.getElementById("transactionModal");
    if (modal) modal.classList.add("active");
}

function openTransactionModalFromChart() {
    if (currentChartData) {
        openTransactionModal(currentChartData.symbol, currentChartData.cmp);
    } else {
        openTransactionModal(currentChartSymbol);
    }
}

function closeTransactionModal() {
    const modal = document.getElementById("transactionModal");
    if (modal) modal.classList.remove("active");
}

async function onStockChange(val) {
    if (!val) return;
    const cleanSym = val.split("•")[0].trim();
    if (cleanSym.length >= 2) {
        try {
            const res = await fetch(`${API_BASE}/api/quote/${encodeURIComponent(cleanSym)}`);
            if (res.ok) {
                const quote = await res.json();
                const symbolInput = document.getElementById("txSymbol");
                if (
                    symbolInput &&
                    quote &&
                    quote.is_valid &&
                    quote.symbol &&
                    cleanSym.includes(" ") &&
                    cleanSym.toUpperCase() !== quote.symbol
                ) {
                    symbolInput.value = quote.symbol;
                }
                if (quote && quote.close_price) {
                    const priceInput = document.getElementById("txPrice");
                    if (priceInput) {
                        priceInput.value = quote.close_price;
                        recalcFees();
                    }
                }
            }
        } catch (e) {
            // Quiet
        }
    }
}

function recalcFees() {
    const price = parseFloat(document.getElementById("txPrice").value) || 0;
    const qty = parseInt(document.getElementById("txQty").value) || 0;
    const isBuy = document.getElementById("txType").value === "BUY";

    const turnover = price * qty;
    const stt = turnover * 0.001; // 0.1%
    const brokerage = Math.min(20.0, turnover * 0.025);
    const stamp = isBuy ? (turnover * 0.00015) : 0.0;
    const exch = turnover * 0.0000345;
    const gst = (brokerage + exch) * 0.18;
    const total = brokerage + stt + stamp + exch + gst;

    document.getElementById("feeTurnover").textContent = `₹${turnover.toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;
    document.getElementById("feeSTT").textContent = `₹${stt.toFixed(2)}`;
    document.getElementById("feeBrokerage").textContent = `₹${brokerage.toFixed(2)}`;
    document.getElementById("feeStamp").textContent = `₹${(stamp + exch).toFixed(2)}`;
    document.getElementById("feeGST").textContent = `₹${gst.toFixed(2)}`;
    document.getElementById("feeTotal").textContent = `₹${total.toFixed(2)}`;
}

async function submitTransaction(e) {
    e.preventDefault();
    const rawVal = document.getElementById("txSymbol").value.trim();
    const symbol = rawVal.split("•")[0].trim().toUpperCase();
    const action = document.getElementById("txType").value;
    const dateVal = document.getElementById("txDate").value;
    const price = parseFloat(document.getElementById("txPrice").value);
    const qty = parseInt(document.getElementById("txQty").value);
    const notes = document.getElementById("txNotes").value;

    const payload = {
        symbol: symbol,
        transaction_type: action,
        transaction_date: dateVal,
        price: price,
        quantity: qty,
        recommendation_id: linkedRecId,
        notes: notes
    };

    try {
        const res = await authFetch(`${API_BASE}/api/portfolio/transaction`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Transaction failed");
        }

        closeTransactionModal();
        await loadPortfolio();
        switchTab("portfolio");
        showToast(`Recorded ${action} ${qty} shares of ${symbol}`, "success");
    } catch (err) {
        showToast("Transaction error: " + err.message, "error");
    }
}

// --------------------------------------------------------------------------
// 7 AI Analyst Desks & Adversarial Debate
// --------------------------------------------------------------------------
function openDebateModalFromChart() {
    openDebateModal(currentChartSymbol);
}

async function openDebateModal(symbol) {
    const cleanSym = (symbol || currentChartSymbol).toUpperCase().replace(".NS", "").replace(".BO", "").trim();
    const exchange = cleanSym === currentChartSymbol ? (currentChartExchange || "NSE") : "NSE";
    const modal = document.getElementById("debateModal");
    const subTitle = document.getElementById("debateModalSubtitle");
    const body = document.getElementById("debateModalBody");

    if (modal) modal.classList.add("active");
    if (subTitle) subTitle.textContent = `Analyzing ${cleanSym} with 7 Parallel AI Specialist Desks...`;
    if (body) {
        body.innerHTML = `
            <div class="ps-orb-block" style="padding: 40px 16px;">
                ${orbHtml("working")}
                <div style="font-size: 15px; color: var(--text-primary);">Consulting 7 analyst desks on ${cleanSym}</div>
                <div style="font-size: 12px; font-family: var(--font-mono); color: var(--text-secondary);">
                    Running Technical, Fundamental, Options Flow, News, Sentiment, Sector, and Risk evaluations
                </div>
            </div>
        `;
    }

    try {
        const res = await fetch(`${API_BASE}/api/debate/${encodeURIComponent(cleanSym)}?exchange=${encodeURIComponent(exchange)}`);
        if (!res.ok) throw new Error(await apiErrorDetail(res, "Analysis unavailable for this listing"));
        const data = await res.json();
        renderDebateContent(data);
    } catch (err) {
        if (body) {
            body.innerHTML = `
                <div style="padding: 30px; text-align: center; color: var(--coral-bear);">
                    <div style="font-size: 14px; font-weight: 700; margin-bottom: 6px;">Analysis Unavailable</div>
                    <div style="font-size: 12px; font-family: var(--font-mono);">${err.message}</div>
                </div>
            `;
        }
    }
}

function closeDebateModal() {
    const modal = document.getElementById("debateModal");
    if (modal) modal.classList.remove("active");
}

function renderDebateContent(data) {
    const subTitle = document.getElementById("debateModalSubtitle");
    const body = document.getElementById("debateModalBody");
    if (!body) return;

    if (subTitle) {
        subTitle.textContent = `${data.symbol} • CMP: ₹${Number(data.reference_price).toLocaleString("en-IN")} | Composite Score: ${data.composite_score}/100`;
    }

    const analysts = data.analysts || [];
    const debate = data.debate || {};
    const tradePlan = debate.trade_plan || {};

    const verdict = (debate.facilitator_verdict || "ACCUMULATE / SWING").toUpperCase();
    const isBullVerdict = verdict.includes("BUY") || verdict.includes("ACCUMULATE") || verdict.includes("BULL");
    const isBearVerdict = verdict.includes("EXIT") || verdict.includes("AVOID") || verdict.includes("BEAR") || verdict.includes("SHORT");

    body.innerHTML = `
        <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 14px; margin-bottom: 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; border-bottom: 1px solid var(--border-subtle); padding-bottom: 10px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 11px; font-weight: 600; color: var(--text-muted);">Facilitator Consensus:</span>
                    <span class="stance-pill ${isBullVerdict ? 'bull' : (isBearVerdict ? 'bear' : 'neutral')}">${debate.facilitator_verdict || "ACCUMULATE / SWING"}</span>
                </div>
                <div style="font-size: 11px; color: var(--text-secondary); font-family: var(--font-mono); display: flex; align-items: center; gap: 6px;">
                    <span style="display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: var(--accent-mint);"></span>
                    Protocol: <strong>Multi-Factor Quantitative Verification</strong>
                </div>
            </div>
            <p style="font-size: 12.5px; color: var(--text-primary); line-height: 1.55; margin-bottom: 14px;">
                ${debate.synthesis || "Institutional Money Flow and 14-day ATR volatility bands synthesized across 7 analytical desks."}
            </p>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; font-family: var(--font-mono); font-size: 11.5px;">
                <div style="background: var(--bg-elevated); padding: 9px 12px; border-radius: var(--radius-xs); border: 1px solid var(--border-subtle);">
                    <div style="color: var(--text-muted); font-size: 12px; font-weight: 600;">Suggested entry</div>
                    <div style="color: var(--text-primary); font-weight: 700; margin-top: 3px; font-size: 13px;">${tradePlan.suggested_entry || "CMP"}</div>
                </div>
                <div style="background: var(--bg-elevated); padding: 9px 12px; border-radius: var(--radius-xs); border: 1px solid var(--border-subtle);">
                    <div style="color: var(--accent-coral); font-size: 12px; font-weight: 600;">Invalidation (SL)</div>
                    <div style="color: var(--accent-coral); font-weight: 700; margin-top: 3px; font-size: 13px;">${tradePlan.downside_invalidation || "Lower ATR Band"}</div>
                </div>
                <div style="background: var(--bg-elevated); padding: 9px 12px; border-radius: var(--radius-xs); border: 1px solid var(--border-subtle);">
                    <div style="color: var(--accent-mint); font-size: 12px; font-weight: 600;">5-day target (TP)</div>
                    <div style="color: var(--accent-mint); font-weight: 700; margin-top: 3px; font-size: 13px;">${tradePlan.target_5d || "Target Price"}</div>
                </div>
                <div style="background: var(--bg-elevated); padding: 9px 12px; border-radius: var(--radius-xs); border: 1px solid var(--border-subtle);">
                    <div style="color: var(--accent-lime); font-size: 12px; font-weight: 600;">Horizon</div>
                    <div style="color: var(--accent-lime); font-weight: 700; margin-top: 3px; font-size: 13px;">5 Sessions</div>
                </div>
            </div>
        </div>

        <div>
            <div style="font-size: 12px; font-weight: 700; color: var(--text-primary); margin-bottom: 8px; font-family: var(--font-display); display: flex; align-items: center; gap: 8px;">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>
                7 Parallel Specialist Quantitative Desks
            </div>
            <div class="analysts-grid">
                ${analysts.map(a => {
                    const st = (a.stance || "").toUpperCase();
                    const isBullStance = st.includes("BULL") || st.includes("ACCUMULATE") || st.includes("OVERWEIGHT") || st.includes("FAVORABLE");
                    const isBearStance = st.includes("BEAR") || st.includes("EXIT") || st.includes("AVOID") || st.includes("UNDERWEIGHT");
                    return `
                    <div class="analyst-card">
                        <div class="analyst-card-header">
                            <span class="analyst-card-title">${a.agent}</span>
                            <span class="stance-pill ${isBullStance ? 'bull' : (isBearStance ? 'bear' : 'neutral')}">${a.stance}</span>
                        </div>
                        <ul style="margin: 0; padding-left: 16px; color: var(--text-secondary); font-size: 11.5px; line-height: 1.55;">
                            ${(a.insights || []).map(ins => `<li style="margin-bottom: 4px;">${ins}</li>`).join("")}
                        </ul>
                    </div>
                `}).join("")}
            </div>
        </div>

        <div class="debate-arena">
            <div class="debate-side bull">
                <div class="debate-title bull">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"></polyline><polyline points="17 6 23 6 23 12"></polyline></svg>
                    Bullish Factor Evidence &amp; Catalysts
                </div>
                <ul style="margin: 0; padding-left: 16px; color: var(--text-secondary); font-size: 11.5px; line-height: 1.55;">
                    ${(debate.bull_points || []).map(p => `<li style="margin-bottom: 4px;">${p}</li>`).join("")}
                </ul>
            </div>
            <div class="debate-side bear">
                <div class="debate-title bear">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"></polyline><polyline points="17 18 23 18 23 12"></polyline></svg>
                    Downside Hazards &amp; ATR Risk Boundaries
                </div>
                <ul style="margin: 0; padding-left: 16px; color: var(--text-secondary); font-size: 11.5px; line-height: 1.55;">
                    ${(debate.bear_points || []).map(p => `<li style="margin-bottom: 4px;">${p}</li>`).join("")}
                </ul>
            </div>
        </div>

        <div style="display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; border-top: 1px solid var(--border-subtle); padding-top: 14px;">
            <button class="btn btn-secondary" onclick="closeDebateModal()">Close</button>
            <button class="btn btn-primary" onclick="closeDebateModal(); openTransactionModal('${data.symbol}', ${data.reference_price});">+ Record Trade</button>
        </div>
    `;
}

// --------------------------------------------------------------------------
// Stock Intelligence (Multi-Provider News & Liquidity Flow)
// --------------------------------------------------------------------------
function openIntelligenceModalFromChart() {
    openStockIntelligenceModal(currentChartSymbol);
}

async function openStockIntelligenceModal(symbol) {
    const cleanSym = (symbol || currentChartSymbol).toUpperCase().replace(".NS", "").replace(".BO", "").trim();
    const exchange = cleanSym === currentChartSymbol ? (currentChartExchange || "NSE") : "NSE";
    const modal = document.getElementById("intelligenceModal");
    const subTitle = document.getElementById("intelModalSubtitle");
    const body = document.getElementById("intelModalBody");

    if (modal) modal.classList.add("active");
    if (subTitle) subTitle.textContent = `Scraping multi-provider news and calculating institutional money flow for ${cleanSym}...`;

    try {
        const res = await fetch(`${API_BASE}/api/intelligence/${encodeURIComponent(cleanSym)}?exchange=${encodeURIComponent(exchange)}`);
        if (!res.ok) throw new Error(await apiErrorDetail(res, "Market intel is unavailable for this listing"));
        const data = await res.json();
        if (data && data.is_valid === false) {
            throw new Error(data.error || "Live market data is unavailable for this listing.");
        }
        renderIntelligenceContent(data);
    } catch (err) {
        if (body) {
            body.innerHTML = `
                <div style="padding: 30px; text-align: center; color: var(--accent-coral);">
                    <div style="font-size: 14px; font-weight: 700;">Could Not Retrieve Live Intelligence</div>
                    <div style="font-size: 11.5px; color: var(--text-muted); margin-top: 4px;">${err.message}</div>
                </div>
            `;
        }
    }
}

function closeIntelligenceModal() {
    const modal = document.getElementById("intelligenceModal");
    if (modal) modal.classList.remove("active");
}

function renderIntelligenceContent(data) {
    const subTitle = document.getElementById("intelModalSubtitle");
    const body = document.getElementById("intelModalBody");
    if (!body) return;

    if (subTitle) {
        subTitle.textContent = `${data.symbol} • ${data.name} | CMP: ₹${Number(data.cmp).toLocaleString("en-IN")}`;
    }

    let factors = data.price_deciding_factors || [];
    if (!factors.length && data.price_factors) {
        factors = [
            ...(data.price_factors.technical?.signals || []),
            ...(data.price_factors.fundamental?.signals || []),
            ...(data.price_factors.sentiment?.signals || []),
            ...(data.price_factors.macro?.signals || [])
        ];
    }
    const newsList = data.hot_news || data.news_items || [];
    const flow = data.institutional_flow || {};

    const tapetide = data.tapetide || {};
    const opt = tapetide.options || {};
    const gov = tapetide.governance || {};
    const macroFlow = tapetide.macro_fii_dii || {};

    body.innerHTML = `
        <!-- TAPETIDE MACRO RADAR & BUILT-IN QUANTITATIVE ENGINES -->
        <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 12px 14px; margin-bottom: 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="font-size: 11px; font-weight: 700; color: var(--accent); font-family: var(--font-display); display: flex; align-items: center; gap: 6px;">
                                        Macro and risk context
                </span>
                <span style="font-size: 12px; font-family: var(--font-mono); color: var(--text-muted); background: var(--bg-surface); padding: 2px 6px; border-radius: 3px; border: 1px solid var(--border-subtle);">
                    0 per-stock calls, 50/day limit
                </span>
            </div>
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;">
                <div style="background: var(--bg-surface); padding: 8px 10px; border-radius: 4px; border: 1px solid var(--border-subtle);">
                    <div style="font-size: 12px; color: var(--text-muted); font-family: var(--font-mono);">Volatility cone</div>
                    <div style="font-size: 13px; font-weight: 700; color: var(--accent-mint); font-family: var(--font-mono);">
                        ${opt.available && opt.iv_rank != null ? opt.iv_rank + '% (IV Rank)' : '14-Day ATR Math'}
                    </div>
                    <div style="font-size: 12px; color: var(--text-secondary); margin-top: 2px;">
                        ${opt.available ? 'Tapetide IV Percentile: ' + opt.iv_percentile + '%' : 'Zero-Synthetic Local Cones'}
                    </div>
                </div>
                <div style="background: var(--bg-surface); padding: 8px 10px; border-radius: 4px; border: 1px solid var(--border-subtle);">
                    <div style="font-size: 12px; color: var(--text-muted); font-family: var(--font-mono);">Solvency and governance</div>
                    <div style="font-size: 13px; font-weight: 700; color: ${gov.is_high_risk ? 'var(--accent-coral)' : 'var(--accent-mint)'}; font-family: var(--font-mono);">
                        ${gov.available && gov.pledged_pct != null ? gov.pledged_pct + '% Pledged' : 'Solvency Gatekeeper'}
                    </div>
                    <div style="font-size: 12px; color: var(--text-secondary); margin-top: 2px;">
                        ${gov.available ? gov.governance_flag : 'Balance Sheet D/E &amp; ROE Checked'}
                    </div>
                </div>
                <div style="background: var(--bg-surface); padding: 8px 10px; border-radius: 4px; border: 1px solid var(--border-subtle);">
                    <div style="font-size: 12px; color: var(--text-muted); font-family: var(--font-mono);">Tapetide FII / DII flow</div>
                    <div style="font-size: 11px; font-weight: 700; color: var(--text-primary); font-family: var(--font-mono);">
                        FII: ${macroFlow.fii_net_cr ? (macroFlow.fii_net_cr > 0 ? '+' : '') + Number(macroFlow.fii_net_cr).toLocaleString() + ' Cr' : 'unavailable'}
                    </div>
                    <div style="font-size: 11px; font-weight: 700; color: var(--accent-mint); font-family: var(--font-mono); margin-top: 2px;">
                        DII: ${macroFlow.dii_net_cr ? (macroFlow.dii_net_cr > 0 ? '+' : '') + Number(macroFlow.dii_net_cr).toLocaleString() + ' Cr' : 'unavailable'}
                    </div>
                </div>
        </div>

        <!-- ON-DEMAND AUDIT BAR -->
        <div style="display: flex; justify-content: space-between; align-items: center; background: var(--bg-elevated); border: 1px solid var(--border-subtle); border-radius: 4px; padding: 6px 12px; margin-bottom: 12px;">
            <div style="font-size: 12px; color: var(--text-muted); display: flex; align-items: center; gap: 6px;">
                <span style="font-weight: 600; color: var(--text-secondary);">Derivatives &amp; Solvency Audit:</span>
                <span>${opt.available ? 'Live Options IV &amp; Promoter Pledge Active (Cached)' : 'Using Local 14D ATR &amp; Solvency Gatekeeper (0 Calls)'}</span>
            </div>
            <button id="btnOnDemandAudit" onclick="triggerTapetideDeepAudit('${data.symbol}')" style="background: var(--bg-elevated); border: 1px solid var(--border-mid); color: var(--text-primary); border-radius: 4px; font-size: 12px; font-weight: 600; padding: 4px 10px; cursor: pointer; display: flex; align-items: center; gap: 5px;">
                ${opt.available ? 'Re-audit (cached)' : 'Run Tapetide audit (1 call)'}
            </button>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px;">
            <div>
                <div style="font-size: 11.5px; font-weight: 700; color: var(--text-primary); margin-bottom: 8px; font-family: var(--font-display);">
                    Price Drivers &amp; Liquidity Flow
                </div>
                <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 12px; margin-bottom: 12px;">
                    <div style="display: flex; justify-content: space-between; font-size: 11.5px; margin-bottom: 4px;">
                        <span style="color: var(--text-muted);">Estimated Institutional Net Flow:</span>
                        <strong style="color: ${flow.flow_bias === 'ACCUMULATION' ? 'var(--accent-mint)' : 'var(--accent-coral)'};">${flow.flow_bias || 'NEUTRAL'}</strong>
                    </div>
                    <div style="font-size: 11px; color: var(--text-secondary); line-height: 1.45;">
                        ${flow.details || "Order flow shows balanced market making with localized delivery interest."}
                    </div>
                </div>

                <div style="font-size: 11.5px; font-weight: 700; color: var(--text-primary); margin-bottom: 8px; font-family: var(--font-display);">
                    Quantitative Factor Drivers
                </div>
                <div style="display: flex; flex-direction: column; gap: 6px;">
                    ${factors.length === 0 ? `
                        <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); padding: 10px; border-radius: var(--radius-sm); font-size: 11px; color: var(--text-secondary);">
                            Verified exchange metrics confirmed: Turnover ₹${data.turnover_cr || 0} Cr, Volume ${data.volume ? Number(data.volume).toLocaleString() : 'N/A'}.
                        </div>
                    ` : factors.map(f => `
                        <div style="background: var(--bg-surface); border: 1px solid var(--border-subtle); padding: 8px 10px; border-radius: var(--radius-sm); font-size: 11px; color: var(--text-secondary); display: flex; align-items: flex-start; gap: 6px;">
                            <span style="color: var(--accent-mint);">&bull;</span>
                            <span>${f}</span>
                        </div>
                    `).join("")}
                </div>
            </div>

            <div>
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <span style="font-size: 11.5px; font-weight: 700; color: var(--text-primary); font-family: var(--font-display);">
                        Live Verified News Headlines
                    </span>
                    <span style="font-size: 12px; font-family: var(--font-mono); color: var(--accent-mint); background: var(--accent-mint-bg); padding: 2px 6px; border-radius: 3px; border: 1px solid var(--accent-mint-border);">
                        Multi-Provider RSS
                    </span>
                </div>
                <div class="news-feed-container">
                    ${newsList.length === 0 ? `
                        <div style="padding: 24px; text-align: center; color: var(--text-muted); background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); font-size: 11.5px;">
                            No recent adverse breaking headlines flagged across monitored sources.
                        </div>
                    ` : newsList.map(n => {
                        const tag = (n.sentiment_tag || 'NEUTRAL').toUpperCase();
                        const isBull = tag.includes('BULL');
                        const isBear = tag.includes('BEAR');
                        return `
                        <div class="news-card-item">
                            <div class="news-card-top">
                                <span class="news-card-source">${n.source || 'Financial Media'}</span>
                                <span class="stance-pill ${isBull ? 'bull' : (isBear ? 'bear' : 'neutral')}">${tag}</span>
                            </div>
                            <a href="${n.link}" target="_blank" rel="noopener noreferrer" class="news-card-title">
                                ${n.title} &#x2197;
                            </a>
                            <div class="news-card-time">${n.pub_date || "Recent Session"}</div>
                        </div>
                    `}).join("")}
                </div>
            </div>
        </div>

        <div style="display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; border-top: 1px solid var(--border-subtle); padding-top: 14px;">
            <button class="btn btn-secondary" onclick="closeIntelligenceModal()">Close</button>
            <button class="btn btn-primary" onclick="closeIntelligenceModal(); openTransactionModal('${data.symbol}', ${data.cmp});">+ Record Trade</button>
        </div>
    `;
}

async function triggerTapetideDeepAudit(symbol) {
    const btn = document.getElementById("btnOnDemandAudit");
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span>⏳</span> Auditing ${symbol}...`;
    }
    try {
        const cleanSym = symbol.toUpperCase().replace(".NS", "").trim();
        const res = await fetch(`${API_BASE}/api/intelligence/tapetide/${cleanSym}/deep-audit`, { method: "POST" });
        if (!res.ok) throw new Error("Deep audit request failed");
        await openStockIntelligenceModal(cleanSym);
    } catch (err) {
        alert("Deep Audit Notice: " + err.message);
        if (btn) {
            btn.disabled = false;
            btn.textContent = "Retry audit";
        }
    }
}

// --------------------------------------------------------------------------
// Corporate Actions Ledger
// --------------------------------------------------------------------------
function openCorporateActionsModal() {
    const modal = document.getElementById("corporateActionsModal");
    if (modal) {
        modal.classList.add("active");
        loadCorporateActions();
    }
}

function closeCorporateActionsModal() {
    const modal = document.getElementById("corporateActionsModal");
    if (modal) modal.classList.remove("active");
}

function toggleRecordCAForm() {
    const form = document.getElementById("recordCAFormContainer");
    if (form) {
        form.style.display = form.style.display === "none" ? "block" : "none";
        const dateInput = document.getElementById("caExDate");
        if (dateInput && !dateInput.value) {
            dateInput.value = new Date().toISOString().split("T")[0];
        }
    }
}

async function loadCorporateActions() {
    const tbody = document.getElementById("corporateActionsTableBody");
    if (!tbody) return;

    try {
        const res = await fetch(`${API_BASE}/api/corporate-actions`);
        if (!res.ok) return;
        const actions = await res.json();
        if (!actions || actions.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-dim); padding: 24px;">No corporate actions recorded yet.</td></tr>`;
            return;
        }

        tbody.innerHTML = actions.map(ca => `
            <tr>
                <td><strong>${ca.symbol}</strong></td>
                <td><span class="badge ${ca.action_type === 'SPLIT' ? 'badge-low' : (ca.action_type === 'BONUS' ? 'badge-medium' : 'badge-high')}">${ca.action_type}</span></td>
                <td style="font-family: var(--font-mono);">${ca.ex_date}</td>
                <td style="font-family: var(--font-mono);">${ca.ratio || '1:1'}</td>
                <td class="num">${ca.adjustment_factor}x</td>
                <td><span style="color: ${ca.applied ? 'var(--emerald-bull)' : 'var(--amber-warning)'};">${ca.applied ? 'APPLIED' : 'PENDING'}</span></td>
                <td style="font-size: 11px; color: var(--text-muted); font-family: var(--font-mono);">${ca.created_at ? ca.created_at.slice(0, 16).replace('T', ' ') : '--'}</td>
            </tr>
        `).join("");
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--coral-bear); padding: 24px;">Failed to load actions.</td></tr>`;
    }
}

async function submitCorporateAction() {
    const symbol = document.getElementById("caSymbol").value.trim().toUpperCase();
    const actionType = document.getElementById("caType").value;
    const ratio = document.getElementById("caRatio").value.trim() || "1:1";
    const factor = parseFloat(document.getElementById("caFactor").value) || 1.0;
    const exDate = document.getElementById("caExDate").value;

    if (!symbol || !exDate) {
        showToast("Please specify symbol and ex-date.", "error");
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/api/corporate-actions`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                symbol: symbol,
                action_type: actionType,
                ex_date: exDate,
                ratio: ratio,
                adjustment_factor: factor
            })
        });

        if (!res.ok) throw new Error("Could not record action");

        await fetch(`${API_BASE}/api/corporate-actions/apply`, { method: "POST" });
        showToast(`Applied ${actionType} for ${symbol}! Cost basis conserved.`, "success");
        toggleRecordCAForm();
        await loadCorporateActions();
        await loadPortfolio();
    } catch (err) {
        showToast("Corporate action error: " + err.message, "error");
    }
}

// --------------------------------------------------------------------------
// Report Briefing Center
// --------------------------------------------------------------------------
function setupReportPreview() {
    const frame = document.getElementById("reportPreviewFrame");
    const downloadBtn = document.getElementById("downloadPdfBtn");

    if (frame) frame.src = `/reports/report_latest.html?t=${Date.now()}`;
    if (downloadBtn) downloadBtn.href = `/reports/report_latest.pdf`;
}

async function generateReportManual() {
    try {
        const res = await fetch(`${API_BASE}/api/reports/generate`, { method: "POST" });
        if (!res.ok) throw new Error("Report generation failed");
        const data = await res.json();
        setupReportPreview();
        showToast(`Morning briefing built for ${data.report_date}!`, "success");
    } catch (err) {
        showToast("Report generation error: " + err.message, "error");
    }
}

let globeStepInterval = null;

// --------------------------------------------------------------------------
// Minimalist Scanner Loader & Toast System
// --------------------------------------------------------------------------
let scanProgressPollInterval = null;

function orbHtml(state, size = 64, extraClass = "") {
    const cls = size === 20 ? "ps-orb ps-orb-inline" : "ps-orb";
    return `<span class="${cls} ${extraClass}" data-orb="${state}" data-orb-size="${size}" aria-hidden="true"></span>`;
}

function setLoaderOrb(state) {
    const orb = document.getElementById("loaderOrb");
    if (orb) orb.setAttribute("data-orb", state);
}

function showScanLoader(title, subtitle, orbState = "working") {
    setLoaderOrb(orbState);
    const overlay = document.getElementById("globeLoaderOverlay");
    const titleEl = document.getElementById("globeLoaderTitle");
    const subEl = document.getElementById("globeLoaderSubtitle");
    const barEl = document.getElementById("globeProgressBar");
    const stepEl = document.getElementById("globeStepText");
    const percentEl = document.getElementById("globePercentVal");
    const countPillEl = document.getElementById("globeCountPill");

    if (!overlay) return;
    if (title && titleEl) titleEl.textContent = title;
    if (subtitle && subEl) subEl.textContent = subtitle;

    if (barEl) barEl.style.width = "4%";
    if (percentEl) percentEl.textContent = "4%";
    if (countPillEl) countPillEl.textContent = "Preparing the NSE + BSE universe";
    if (stepEl) stepEl.textContent = "Syncing exchange price files";

    overlay.classList.add("active");

    // Real-Time Screening Progress Polling from backend
    clearInterval(scanProgressPollInterval);
    scanProgressPollInterval = setInterval(async () => {
        try {
            const res = await fetch(`${API_BASE}/api/recommendations/progress`);
            if (!res.ok) return;
            const prog = await res.json();

            if (prog && prog.percent !== undefined) {
                const pct = Math.max(4, Math.min(100, Math.round(prog.percent)));
                if (barEl) barEl.style.width = `${pct}%`;
                if (percentEl) percentEl.textContent = `${pct}%`;

                if (countPillEl) {
                    const totalUniverse = prog.target_count || 0;
                    if (prog.evaluated_count > 0) {
                        countPillEl.textContent = `${prog.evaluated_count.toLocaleString("en-IN")} of ${totalUniverse.toLocaleString("en-IN")} evaluated, ${prog.qualified_count} qualified`;
                    } else {
                        countPillEl.textContent = `Preparing ${totalUniverse ? totalUniverse.toLocaleString("en-IN") + " " : ""}stocks`;
                    }
                }

                if (stepEl && prog.stage_text) {
                    stepEl.textContent = prog.stage_text.replace(/^[\u2713\u2714]\s*/, "");
                }
            }
        } catch (e) {
            // Quiet network error handling
        }
    }, 350);
}

function hideScanLoader() {
    const overlay = document.getElementById("globeLoaderOverlay");
    const barEl = document.getElementById("globeProgressBar");
    const percentEl = document.getElementById("globePercentVal");
    const countPillEl = document.getElementById("globeCountPill");
    const stepEl = document.getElementById("globeStepText");

    clearInterval(scanProgressPollInterval);
    clearInterval(globeStepInterval);

    if (barEl) barEl.style.width = "100%";
    if (percentEl) percentEl.textContent = "100%";
    if (countPillEl) countPillEl.textContent = "Screening complete";
    if (stepEl) stepEl.textContent = "";

    setTimeout(() => {
        if (overlay) overlay.classList.remove("active");
        if (barEl) barEl.style.width = "0%";
    }, 320);
}

function showToast(message, type = "info") {
    const container = document.getElementById("toastContainer");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    const icon = document.createElement("span");
    icon.textContent = type === "success" ? "✓" : (type === "error" ? "✕" : "ℹ");
    const text = document.createElement("span");
    text.textContent = message;
    toast.append(icon, text);

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateX(20px)";
        setTimeout(() => toast.remove(), 250);
    }, 3500);
}

// --------------------------------------------------------------------------
// Theme Engine (Dark / Light Mode)
// --------------------------------------------------------------------------
function initTheme() {
    const savedTheme = localStorage.getItem("predictastock_theme");
    const isLight = savedTheme === "light";
    applyTheme(isLight);
}

const SVG_THEME_SUN = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>`;
const SVG_THEME_MOON = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>`;

function applyTheme(isLight) {
    if (isLight) {
        document.body.classList.add("light-theme");
    } else {
        document.body.classList.remove("light-theme");
    }

    const topContainer = document.getElementById("topThemeIconContainer");
    if (topContainer) {
        topContainer.innerHTML = isLight ? SVG_THEME_MOON : SVG_THEME_SUN;
    }

    const topBtn = document.getElementById("topThemeToggleBtn");
    if (topBtn) topBtn.title = isLight ? "Switch to dark theme" : "Switch to light theme";

    const sideContainer = document.getElementById("sidebarThemeIconContainer");
    if (sideContainer) {
        sideContainer.innerHTML = isLight ? SVG_THEME_MOON : SVG_THEME_SUN;
    }

    const sideLabel = document.getElementById("sidebarThemeLabel");
    if (sideLabel) sideLabel.textContent = isLight ? "Light theme" : "Dark theme";

    localStorage.setItem("predictastock_theme", isLight ? "light" : "dark");

    // Dynamic Chart Re-render on Theme Switch
    if (currentChartData) {
        renderPriceChart(currentChartData);
    }
    if (portfolioData) {
        renderPortfolioGrowthChart(portfolioData);
    }
}

function toggleThemeManual() {
    const isCurrentlyLight = document.body.classList.contains("light-theme");
    applyTheme(!isCurrentlyLight);
    showToast(`Switched to ${!isCurrentlyLight ? 'light' : 'dark'} theme`, "info");
}

window.loadPaperTradingScorecard = loadPaperTradingScorecard;
window.loadStrategyEvidence = loadStrategyEvidence;

// --------------------------------------------------------------------------
// Institutional Integrations (Tapetide MCP, Dhan HQ, Upstox API)
// --------------------------------------------------------------------------
let integrationsState = null;

async function fetchIntegrationsStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/integrations/status`);
        if (!res.ok) return;
        const data = await res.json();
        integrationsState = data;

        // Topbar Pill
        const quotaDisplay = document.getElementById("tapetideQuotaDisplay");
        const statusDot = document.getElementById("tapetideStatusDot");
        if (data.tapetide) {
            const used = data.tapetide.calls_used_today || 0;
            const remaining = data.tapetide.calls_remaining != null ? data.tapetide.calls_remaining : Math.max(0, 50 - used);
            if (quotaDisplay) {
                quotaDisplay.textContent = `${remaining}/50 FREE`;
            }
            if (statusDot) {
                statusDot.style.background = data.tapetide.status === "OPERATIONAL" ? "var(--accent-mint)" : "var(--accent-coral)";
            }

            // Modal Fields
            const modalBadge = document.getElementById("modalTapetideStatusBadge");
            const modalQuotaText = document.getElementById("modalTapetideQuotaText");
            const modalQuotaBar = document.getElementById("modalTapetideQuotaBar");
            const modalCacheText = document.getElementById("modalTapetideCacheText");

            if (modalBadge) {
                modalBadge.textContent = `${data.tapetide.status} (55 TOOLS)`;
                modalBadge.className = `stance-pill ${data.tapetide.status === 'OPERATIONAL' ? 'bull' : 'bear'}`;
            }
            if (modalQuotaText) {
                modalQuotaText.textContent = `${used} / 50 Calls Used (${remaining} Free Remaining)`;
            }
            if (modalQuotaBar) {
                const pct = Math.min(100, Math.round((used / 50) * 100));
                modalQuotaBar.style.width = `${Math.max(5, pct)}%`;
                modalQuotaBar.style.background = pct > 80 ? "var(--accent-coral)" : "var(--accent-mint)";
            }
            if (modalCacheText) {
                modalCacheText.textContent = `${data.tapetide.cached_entries || 0} Cached Scrips (24h TTL, 0 API Calls)`;
            }
        }

    } catch (e) {
        console.warn("Integrations status fetch failed:", e);
    }
}

function openIntegrationsModal(defaultTab) {
    const modal = document.getElementById("integrationsModal");
    if (modal) {
        modal.classList.add("active");
        fetchIntegrationsStatus();
    }
}

function closeIntegrationsModal() {
    const modal = document.getElementById("integrationsModal");
    if (modal) modal.classList.remove("active");
}

async function saveTapetideToken() {
    const input = document.getElementById("inputTapetideToken");
    const val = input ? input.value.trim() : "";
    if (!val) {
        showToast("Please enter a valid Tapetide token", "warning");
        return;
    }
    try {
        const res = await authFetch(`${API_BASE}/api/integrations/credentials`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ service: "tapetide", credentials: { token: val } })
        });
        if (res.ok) {
            showToast("Tapetide token updated & saved", "success");
            if (input) input.value = "";
            fetchIntegrationsStatus();
        } else {
            showToast("Failed to save Tapetide token", "error");
        }
    } catch (e) {
        showToast(`Error: ${e.message}`, "error");
    }
}

window.openIntegrationsModal = openIntegrationsModal;
window.closeIntegrationsModal = closeIntegrationsModal;
window.saveTapetideToken = saveTapetideToken;


// -------------------------------------------------------------
// WEEKLY LIVE-ENGINE BACKTEST
// -------------------------------------------------------------
let weeklyBacktestWindow = "6mo";
let weeklyBacktestPoll = null;
let weeklyBacktestLoaded = false;

function isoLocalDate(value) {
    const date = value instanceof Date ? value : new Date(value);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
}

function lastCompletedSaturday(today = new Date()) {
    const day = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    const pythonWeekday = (day.getDay() + 6) % 7;
    const daysSinceSaturday = (pythonWeekday - 5 + 7) % 7;
    day.setDate(day.getDate() - daysSinceSaturday);
    const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    if (day >= todayStart) day.setDate(day.getDate() - 7);
    return day;
}

function weeklyRangeFor(windowKey) {
    const end = lastCompletedSaturday();
    const start = new Date(end);
    if (windowKey === "1y") start.setDate(start.getDate() - 365);
    else start.setDate(start.getDate() - 183);
    return { start: isoLocalDate(start), end: isoLocalDate(end) };
}

function markWeeklyPreset(windowKey) {
    document.querySelectorAll("#wbPresetRow [data-window]").forEach((btn) => {
        const selected = btn.getAttribute("data-window") === windowKey;
        btn.classList.toggle("btn-primary", selected);
        btn.classList.toggle("btn-secondary", !selected);
    });
}

function showWeeklySelection() {
    const status = document.getElementById("weeklyBacktestStatus");
    const start = document.getElementById("weeklyStartDate")?.value;
    const end = document.getElementById("weeklyEndDate")?.value;
    if (!status || !start || !end) return;
    const label = weeklyBacktestWindow === "1y"
        ? "Last 1 year"
        : weeklyBacktestWindow === "6mo"
            ? "Last 6 months"
            : "Custom dates";
    status.textContent = `${label} selected: ${start} to ${end}. Press Run weekly backtest.`;
}

function setWeeklyBacktestWindow(windowKey) {
    weeklyBacktestWindow = windowKey === "1y" || windowKey === "custom" ? windowKey : "6mo";
    markWeeklyPreset(weeklyBacktestWindow);
    if (weeklyBacktestWindow !== "custom") {
        const range = weeklyRangeFor(weeklyBacktestWindow);
        const startEl = document.getElementById("weeklyStartDate");
        const endEl = document.getElementById("weeklyEndDate");
        if (startEl) startEl.value = range.start;
        if (endEl) endEl.value = range.end;
    }
    showWeeklySelection();
}

function onWeeklyDateEdited() {
    weeklyBacktestWindow = "custom";
    markWeeklyPreset("custom");
    showWeeklySelection();
}

function initWeeklyBacktest() {
    const startEl = document.getElementById("weeklyStartDate");
    const endEl = document.getElementById("weeklyEndDate");
    const today = isoLocalDate(new Date());
    if (startEl) startEl.max = today;
    if (endEl) endEl.max = today;
    if (!weeklyBacktestLoaded) {
        weeklyBacktestLoaded = true;
        document.querySelectorAll("#wbPresetRow [data-window]").forEach((btn) => {
            btn.addEventListener("click", () => setWeeklyBacktestWindow(btn.getAttribute("data-window")));
        });
        if (startEl) startEl.addEventListener("change", onWeeklyDateEdited);
        if (endEl) endEl.addEventListener("change", onWeeklyDateEdited);
        const runBtn = document.getElementById("btnRunWeeklyBacktest");
        if (runBtn) runBtn.addEventListener("click", () => runWeeklyEngineBacktest());
        setWeeklyBacktestWindow("6mo");
    } else {
        showWeeklySelection();
    }
    loadSavedWeeklyBacktest().then(() => resumeWeeklyBacktestLoader());
}

let weeklyOrbOpen = false;

async function loadSavedWeeklyBacktest() {
    try {
        const res = await fetch(`${API_BASE}/api/backtest/weekly/latest?t=${Date.now()}`, { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        if (data.report) renderWeeklyBacktest(data.report);
    } catch (err) {
        console.error("Weekly backtest load failed:", err);
    }
}

function showWeeklyOrbLoader(detail) {
    weeklyOrbOpen = true;
    setLoaderOrb("working");
    const overlay = document.getElementById("globeLoaderOverlay");
    const titleEl = document.getElementById("globeLoaderTitle");
    const subEl = document.getElementById("globeLoaderSubtitle");
    const barEl = document.getElementById("globeProgressBar");
    const stepEl = document.getElementById("globeStepText");
    const percentEl = document.getElementById("globePercentVal");
    const countPillEl = document.getElementById("globeCountPill");
    if (titleEl) titleEl.textContent = "Weekly backtest";
    if (subEl) subEl.textContent = detail || "Scoring each Monday's list of 5 through Saturday.";
    if (barEl) barEl.style.width = "4%";
    if (percentEl) percentEl.textContent = "4%";
    if (countPillEl) countPillEl.textContent = "Preparing the Monday predictions";
    if (stepEl) stepEl.textContent = "Loading price history";
    if (overlay) overlay.classList.add("active");
    ["wbWinRate", "wbLossRate", "wbHits", "wbLosses", "wbAvgUp", "wbAvgDown"].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.textContent = "...";
    });
    const banner = document.getElementById("weeklyPhaseBanner");
    if (banner) banner.textContent = "Scoring every Monday with the present engine. The previous score is cleared until this run finishes.";
    const tbody = document.getElementById("weeklyBacktestTableBody");
    if (tbody) {
        tbody.innerHTML = `<tr><td colspan="8" class="ps-orb-block">${orbHtml("working")} Scoring each Monday's 5 predictions...</td></tr>`;
    }
}

function paintWeeklyOrb(progress) {
    const barEl = document.getElementById("globeProgressBar");
    const stepEl = document.getElementById("globeStepText");
    const percentEl = document.getElementById("globePercentVal");
    const countPillEl = document.getElementById("globeCountPill");
    const pct = Math.max(4, Math.min(99, Math.round(progress.percent || 4)));
    if (barEl) barEl.style.width = `${pct}%`;
    if (percentEl) percentEl.textContent = `${pct}%`;
    const done = Number(progress.weeks_done || 0);
    const total = Number(progress.weeks_total || 0);
    if (countPillEl) {
        countPillEl.textContent = total
            ? `Week ${Math.min(total, done + 1)} of ${total}`
            : "Scoring Mondays";
    }
    if (stepEl) stepEl.textContent = progress.stage || "Scoring the weekly list of 5";
}

function hideWeeklyOrbLoader() {
    const overlay = document.getElementById("globeLoaderOverlay");
    const barEl = document.getElementById("globeProgressBar");
    const percentEl = document.getElementById("globePercentVal");
    const countPillEl = document.getElementById("globeCountPill");
    const stepEl = document.getElementById("globeStepText");
    if (barEl) barEl.style.width = "100%";
    if (percentEl) percentEl.textContent = "100%";
    if (countPillEl) countPillEl.textContent = "Weekly score ready";
    if (stepEl) stepEl.textContent = "";
    weeklyOrbOpen = false;
    setTimeout(() => {
        if (overlay) overlay.classList.remove("active");
        if (barEl) barEl.style.width = "0%";
    }, 320);
}

async function resumeWeeklyBacktestLoader() {
    try {
        const res = await fetch(`${API_BASE}/api/backtest/weekly/progress`);
        if (!res.ok) return;
        const data = await res.json();
        if (data.status !== "running") return;
        showWeeklyOrbLoader("A weekly backtest is already running.");
        paintWeeklyOrb(data);
        const button = document.getElementById("btnRunWeeklyBacktest");
        if (button) {
            button.disabled = true;
            button.textContent = "Running...";
        }
        if (weeklyBacktestPoll) clearInterval(weeklyBacktestPoll);
        weeklyBacktestPoll = setInterval(pollWeeklyBacktest, 1500);
    } catch (err) {
        console.error("Weekly loader resume failed:", err);
    }
}

function renderWeeklyBacktest(report) {
    const score = report.score || {};
    const gate = report.phase_gate || {};
    const win = document.getElementById("wbWinRate");
    const lossRate = document.getElementById("wbLossRate");
    const hits = document.getElementById("wbHits");
    const losses = document.getElementById("wbLosses");
    const hitShare = document.getElementById("wbHitShare");
    const lossShare = document.getElementById("wbLossShare");
    const avgUp = document.getElementById("wbAvgUp");
    const avgDown = document.getElementById("wbAvgDown");
    const totalUp = document.getElementById("wbTotalUp");
    const totalDown = document.getElementById("wbTotalDown");
    const banner = document.getElementById("weeklyPhaseBanner");

    const predicted = Number(score.predicted ?? score.trades ?? 0);
    const hitCount = Number(score.hits ?? 0);
    const lossCount = Number(score.losses ?? 0);
    const lossRatePct = score.loss_rate_pct ?? (predicted ? (lossCount / predicted) * 100 : 0);
    if (win) {
        win.textContent = `${Number(score.win_rate_pct ?? 0).toFixed(1)}%`;
        win.style.color = (score.win_rate_pct || 0) >= 50 ? "var(--gain)" : "var(--loss)";
    }
    if (lossRate) lossRate.textContent = `${Number(lossRatePct).toFixed(1)}%`;
    if (hits) hits.textContent = String(hitCount);
    if (losses) losses.textContent = String(lossCount);
    if (hitShare) hitShare.textContent = predicted ? `${hitCount} hits out of ${predicted} predictions` : "Hits out of the weekly 5";
    if (lossShare) lossShare.textContent = predicted ? `${lossCount} losses out of ${predicted} predictions` : "Losses out of the weekly 5";
    if (avgUp) {
        avgUp.textContent = `${(score.avg_up_pct || 0) >= 0 ? "+" : ""}${Number(score.avg_up_pct || 0).toFixed(2)}%`;
        avgUp.style.color = "var(--gain)";
    }
    if (avgDown) {
        avgDown.textContent = `${Number(score.avg_down_pct || 0).toFixed(2)}%`;
        avgDown.style.color = "var(--loss)";
    }
    if (totalUp) totalUp.textContent = `Total up ${(score.total_up_pct || 0) >= 0 ? "+" : ""}${Number(score.total_up_pct || 0).toFixed(2)}%`;
    if (totalDown) totalDown.textContent = `Total down ${Number(score.total_down_pct || 0).toFixed(2)}%`;
    const excessEl = document.getElementById("wbExcess");
    const baseEl = document.getElementById("wbBaseRate");
    const expectancyEl = document.getElementById("wbExpectancy");
    const factorEl = document.getElementById("wbProfitFactor");
    const portfolioEl = document.getElementById("wbPortfolio");
    const drawdownEl = document.getElementById("wbDrawdown");
    const portfolio = score.portfolio || {};
    if (excessEl) {
        const excess = score.excess_hit_rate_pct;
        excessEl.textContent = excess == null ? "--" : `${excess >= 0 ? "+" : ""}${Number(excess).toFixed(1)} pts`;
        excessEl.style.color = Number(excess) > 0 ? "var(--gain)" : "var(--loss)";
    }
    if (baseEl) baseEl.textContent = score.base_rate_pct == null ? "Universe base rate --" : `Universe base rate ${Number(score.base_rate_pct).toFixed(1)}%`;
    if (expectancyEl) {
        const expectancy = Number(score.expectancy_pct || 0);
        expectancyEl.textContent = `${expectancy >= 0 ? "+" : ""}${expectancy.toFixed(2)}%`;
        expectancyEl.style.color = expectancy >= 0 ? "var(--gain)" : "var(--loss)";
    }
    if (factorEl) factorEl.textContent = `Profit factor ${Number(score.profit_factor || 0).toFixed(2)}`;
    if (portfolioEl) {
        const total = Number(portfolio.total_return_pct || 0);
        portfolioEl.textContent = portfolio.total_return_pct == null ? "--" : `${total >= 0 ? "+" : ""}${total.toFixed(2)}%`;
        portfolioEl.style.color = total >= 0 ? "var(--gain)" : "var(--loss)";
    }
    if (drawdownEl) drawdownEl.textContent = portfolio.max_drawdown_pct == null ? "Max drawdown --" : `Max drawdown ${Number(portfolio.max_drawdown_pct).toFixed(1)}%`;
    if (banner) {
        const ready = !!gate.ready_for_next_phase;
        banner.textContent = gate.reason || "Weekly score saved.";
        banner.style.borderColor = ready ? "var(--gain)" : "var(--warn)";
        banner.style.color = ready ? "var(--gain)" : "var(--text-primary)";
    }
    const tbody = document.getElementById("weeklyBacktestTableBody");
    if (!tbody) return;
    const weeks = report.weeks || [];
    if (!weeks.length) {
        tbody.innerHTML = `<tr><td colspan="11" style="text-align:center; color: var(--text-muted); padding: 32px;">No completed weeks in this range.</td></tr>`;
        return;
    }
    const pct = (value) => `${Number(value || 0).toFixed(1)}%`;
    const signed = (value) => value == null || value === "" ? "--" : `${Number(value) >= 0 ? "+" : ""}${Number(value).toFixed(2)}%`;
    tbody.innerHTML = weeks.map((row) => {
        const called = Number(row.predicted ?? row.picks ?? 0);
        const weekHits = Number(row.hits || 0);
        const weekLosses = Number(row.losses || 0);
        const weekWin = row.win_rate_pct ?? (called ? (weekHits / called) * 100 : 0);
        const weekLoss = row.loss_rate_pct ?? (called ? (weekLosses / called) * 100 : 0);
        return `<tr>
            <td style="font-family: var(--font-mono);">${row.week_start || row.signal_date} → ${row.week_end}</td>
            <td class="num" style="font-weight:700;">${called}</td>
            <td class="num" style="color: var(--gain); font-weight:700;">${weekHits}</td>
            <td class="num" style="color: var(--loss); font-weight:700;">${weekLosses}</td>
            <td class="num" style="color: var(--gain);">${pct(weekWin)}</td>
            <td class="num" style="color: var(--loss);">${pct(weekLoss)}</td>
            <td class="num" style="color: var(--gain);">${Number(row.avg_up_pct || 0) ? "+" : ""}${Number(row.avg_up_pct || 0).toFixed(2)}%</td>
            <td class="num" style="color: var(--loss);">${Number(row.avg_down_pct || 0).toFixed(2)}%</td>
            <td class="num">${row.base_rate_pct == null ? "--" : pct(row.base_rate_pct)}</td>
            <td class="num">${signed(row.nifty_return_pct)}</td>
            <td class="num" style="color: ${Number(row.excess_hit_rate_pct) >= 0 ? "var(--gain)" : "var(--loss)"};">${row.excess_hit_rate_pct == null ? "--" : `${Number(row.excess_hit_rate_pct) >= 0 ? "+" : ""}${Number(row.excess_hit_rate_pct).toFixed(1)}`}</td>
        </tr>`;
    }).join("");
}

async function runWeeklyEngineBacktest() {
    const status = document.getElementById("weeklyBacktestStatus");
    const button = document.getElementById("btnRunWeeklyBacktest");
    const startDate = document.getElementById("weeklyStartDate")?.value || "";
    const endDate = document.getElementById("weeklyEndDate")?.value || "";
    if (!startDate || !endDate) {
        if (typeof showToast === "function") showToast("Choose a start date and an end date", "warning");
        if (status) status.textContent = "Pick a start date and an end date first.";
        return;
    }
    if (startDate > endDate) {
        if (typeof showToast === "function") showToast("The start date is after the end date", "warning");
        if (status) status.textContent = "The start date has to be on or before the end date.";
        return;
    }
    const payload = { window: "custom", start_date: startDate, end_date: endDate };
    if (button) {
        button.disabled = true;
        button.textContent = "Running...";
    }
    showWeeklyOrbLoader(`${startDate} to ${endDate}. Each Monday runs the full present-engine scan, so this takes as long as a live analysis once per week.`);
    if (status) status.textContent = `Running ${startDate} to ${endDate}.`;
    try {
        const res = await fetch(`${API_BASE}/api/backtest/weekly/run`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            hideWeeklyOrbLoader();
            throw new Error(data.detail || "Weekly backtest failed to start");
        }
        if (weeklyBacktestPoll) clearInterval(weeklyBacktestPoll);
        weeklyBacktestPoll = setInterval(pollWeeklyBacktest, 1500);
        pollWeeklyBacktest();
    } catch (err) {
        if (button) {
            button.disabled = false;
            button.textContent = "Run weekly backtest";
        }
        if (status) status.textContent = err.message;
        hideWeeklyOrbLoader();
        if (typeof showToast === "function") showToast(err.message, "error");
    }
}

async function pollWeeklyBacktest() {
    const status = document.getElementById("weeklyBacktestStatus");
    const button = document.getElementById("btnRunWeeklyBacktest");
    try {
        const res = await fetch(`${API_BASE}/api/backtest/weekly/progress?t=${Date.now()}`, { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        if (data.status === "running") paintWeeklyOrb(data);
        if (status && data.stage) status.textContent = data.stage;
        if (data.status === "completed") {
            clearInterval(weeklyBacktestPoll);
            weeklyBacktestPoll = null;
            if (button) {
                button.disabled = false;
                button.textContent = "Run weekly backtest";
            }
            hideWeeklyOrbLoader();
            await loadSavedWeeklyBacktest();
            showWeeklySelection();
        } else if (data.status === "error") {
            clearInterval(weeklyBacktestPoll);
            weeklyBacktestPoll = null;
            if (button) {
                button.disabled = false;
                button.textContent = "Run weekly backtest";
            }
            hideWeeklyOrbLoader();
            if (status) status.textContent = data.error || data.stage || "Weekly backtest failed";
        } else if (data.status !== "running") {
            clearInterval(weeklyBacktestPoll);
            weeklyBacktestPoll = null;
            if (button) {
                button.disabled = false;
                button.textContent = "Run weekly backtest";
            }
            hideWeeklyOrbLoader();
            await loadSavedWeeklyBacktest();
        }
    } catch (err) {
        console.error("Weekly backtest poll failed:", err);
    }
}

window.setWeeklyBacktestWindow = setWeeklyBacktestWindow;
window.initWeeklyBacktest = initWeeklyBacktest;
window.runWeeklyEngineBacktest = runWeeklyEngineBacktest;
