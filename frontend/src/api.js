const IS_LOCALHOST = typeof window !== "undefined" && ["localhost", "127.0.0.1"].includes(window.location.hostname);
const API_BASE = import.meta.env.VITE_API_BASE || (IS_LOCALHOST ? "http://localhost:8000/api" : "/api");

function getHeaders() {
    const token = localStorage.getItem("token");
    const headers = {
        "Content-Type": "application/json"
    };
    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }
    return headers;
}

function redirectToLogin() {
    localStorage.removeItem("token");
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
    }
}

// Every authenticated request goes through here so an expired/invalid token
// (backend returns 401) clears the stale token and sends the user back to
// login immediately, instead of leaving the app rendered with silently
// failing requests (each caller's own catch block otherwise just shows an
// empty/generic state with no explanation of why).
async function authorizedFetch(url, options = {}) {
    const res = await fetch(url, {
        ...options,
        headers: { ...getHeaders(), ...(options.headers || {}) },
    });
    if (res.status === 401) {
        redirectToLogin();
    }
    return res;
}

export async function login(username, password) {
    const formData = new URLSearchParams();
    formData.append("username", username);
    formData.append("password", password);

    const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded"
        },
        body: formData
    });
    
    const data = await res.json().catch(() => null);
    if (!res.ok) {
        const error = new Error(data?.detail || "Login failed");
        error.status = res.status;
        throw error;
    }
    localStorage.setItem("token", data.access_token);
    return data;
}

export function logout() {
    localStorage.removeItem("token");
}

export async function fetchQuota() {
    const res = await authorizedFetch(`${API_BASE}/quota/status`);
    if (!res.ok) {
        if (res.status === 401) throw new Error("Unauthorized");
        throw new Error("Failed to fetch quota");
    }
    return res.json();
}

export async function fetchAdminUsers() {
    const res = await authorizedFetch(`${API_BASE}/admin/users`);
    if (!res.ok) throw new Error("Failed to fetch users");
    return res.json();
}

export async function fetchAdminUsageStats() {
    const res = await authorizedFetch(`${API_BASE}/admin/usage-stats`);
    if (!res.ok) throw new Error("Failed to fetch usage statistics");
    return res.json();
}

export async function fetchAdminLlmUsageStats() {
    const res = await authorizedFetch(`${API_BASE}/admin/llm-usage-stats`);
    if (!res.ok) throw new Error("Failed to fetch LLM usage statistics");
    return res.json();
}

export async function createAdminUser(payload) {
    const res = await authorizedFetch(`${API_BASE}/admin/users`, {
        method: "POST",
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || "Failed to create user");
    }
    return res.json();
}

export async function updateAdminUserPassword(username, password) {
    const res = await authorizedFetch(`${API_BASE}/admin/users/${encodeURIComponent(username)}/password`, {
        method: "PUT",
        body: JSON.stringify({ password }),
    });
    if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || "Failed to update password");
    }
    return res.json();
}

export async function normalizeAdminCountries() {
    const res = await authorizedFetch(`${API_BASE}/admin/normalize-countries`, {
        method: "POST",
    });
    if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || "Failed to normalize countries");
    }
    return res.json();
}

export async function updateAdminUserActive(username, active) {
    const res = await authorizedFetch(`${API_BASE}/admin/users/${encodeURIComponent(username)}/active`, {
        method: "PUT",
        body: JSON.stringify({ active }),
    });
    if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || "Failed to update user status");
    }
    return res.json();
}

export async function fetchCountries() {
    const res = await authorizedFetch(`${API_BASE}/countries`);
    if (!res.ok) throw new Error("Failed to fetch countries");
    return res.json();
}

export async function fetchStates(countryCode) {
    const params = new URLSearchParams({ country_code: countryCode });
    const res = await authorizedFetch(`${API_BASE}/geo/states?${params.toString()}`);
    if (!res.ok) throw new Error("Failed to fetch states");
    return res.json();
}

export async function fetchCities(countryCode, stateCode) {
    const params = new URLSearchParams({ country_code: countryCode, state_code: stateCode });
    const res = await authorizedFetch(`${API_BASE}/geo/cities?${params.toString()}`);
    if (!res.ok) throw new Error("Failed to fetch cities");
    return res.json();
}

export async function fetchPopulatedCountries() {
    const res = await authorizedFetch(`${API_BASE}/businesses/countries`);
    if (!res.ok) throw new Error("Failed to fetch countries with data");
    return res.json();
}

export async function fetchCountryBusinesses(country, page = 1, crawlTier = "all", businessRole = "all") {
    const params = new URLSearchParams({ country, page });
    if (crawlTier && crawlTier !== "all") params.append("crawl_tier", crawlTier);
    if (businessRole && businessRole !== "all") params.append("business_role", businessRole);
    const res = await authorizedFetch(`${API_BASE}/businesses?${params.toString()}`);
    if (!res.ok) throw new Error("Failed to fetch country businesses");
    return res.json();
}

export function getCountryExportUrl(country, format, selectedColumns = [], selectedTiers = [], selectedRoles = []) {
    const params = new URLSearchParams({ country, format });
    selectedColumns.forEach(column => params.append("selected_columns", column));
    selectedTiers.forEach(tier => params.append("selected_tiers", tier));
    selectedRoles.forEach(role => params.append("selected_roles", role));
    return `${API_BASE}/businesses/export?${params.toString()}`;
}

export async function downloadCountryExport(country, format, selectedColumns = [], selectedTiers = [], selectedRoles = []) {
    const res = await authorizedFetch(getCountryExportUrl(country, format, selectedColumns, selectedTiers, selectedRoles));
    if (!res.ok) throw new Error("Download failed");

    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `country_${country}.${format}`;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    a.remove();
}

export async function createSearch(payload) {
    const res = await authorizedFetch(`${API_BASE}/searches`, {
        method: "POST",
        body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error("Failed to create search");
    return res.json();
}

export async function cancelSearch(id) {
    const res = await authorizedFetch(`${API_BASE}/searches/${id}/cancel`, {
        method: "POST",
    });
    if (!res.ok) throw new Error("Failed to stop search");
    return res.json();
}

export async function fetchSearch(id) {
    const res = await authorizedFetch(`${API_BASE}/searches/${id}`);
    if (!res.ok) throw new Error("Failed to fetch search");
    return res.json();
}

export async function fetchHistory(page = 1, pageSize = 20) {
    const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
    });
    const res = await authorizedFetch(`${API_BASE}/searches?${params.toString()}`);
    if (!res.ok) throw new Error("Failed to fetch history");
    return res.json();
}

export function getExportUrl(id, format, selectedColumns = [], selectedTiers = [], selectedRoles = []) {
    const params = new URLSearchParams({ format });
    selectedColumns.forEach(column => params.append("selected_columns", column));
    selectedTiers.forEach(tier => params.append("selected_tiers", tier));
    selectedRoles.forEach(role => params.append("selected_roles", role));
    return `${API_BASE}/searches/${id}/export?${params.toString()}`;
}

export async function downloadFile(id, format, selectedColumns = [], selectedTiers = [], selectedRoles = []) {
    const res = await authorizedFetch(getExportUrl(id, format, selectedColumns, selectedTiers, selectedRoles));
    if (!res.ok) throw new Error("Download failed");
    
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `export_${id}.${format}`;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
    a.remove();
}

// ---- Company Enrichment ----

export async function parseEnrichmentFile(file) {
    const form = new FormData();
    form.append("file", file);
    // multipart: let the browser set Content-Type (with boundary) itself
    const token = localStorage.getItem("token");
    const res = await fetch(`${API_BASE}/enrichment/parse-file`, {
        method: "POST",
        body: form,
        headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (res.status === 401) redirectToLogin();
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(data?.detail || "Could not parse file");
    return data.companies;
}

// Streams Server-Sent Events from POST /enrichment/enrich (EventSource can't
// POST or send an Authorization header, so this reads the fetch body).
export async function streamEnrichment(companies, forceRefresh, onEvent, signal, profile = "tritorc") {
    const res = await authorizedFetch(`${API_BASE}/enrichment/enrich`, {
        method: "POST",
        body: JSON.stringify({ companies, force_refresh: forceRefresh, profile }),
        signal,
    });
    if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || "Enrichment failed to start");
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop();
        for (const part of parts) {
            const line = part.split("\n").find((l) => l.startsWith("data: "));
            if (line) onEvent(JSON.parse(line.slice(6)));
        }
    }
}

export async function enrichSingle({ companyName, website, placeId, profile = "tritorc" }) {
    const res = await authorizedFetch(`${API_BASE}/enrichment/enrich-single`, {
        method: "POST",
        body: JSON.stringify({ company_name: companyName, website, place_id: placeId, profile }),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(data?.detail || "Enrichment failed");
    return data;
}

async function postEnrichment(path, body, fallback) {
    const res = await authorizedFetch(`${API_BASE}/enrichment/${path}`, { method: "POST", body: JSON.stringify(body) });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(typeof data?.detail === "string" ? data.detail : fallback);
    return data;
}

// "Wrong company?": the user gives the right website for a typed name.
export const correctEnrichment = ({ input, website, wrongId, profile = "tritorc" }) =>
    postEnrichment("correct", { input, website, wrong_id: wrongId, profile }, "Couldn't fix the match. Try again.");

// Save the user's own accept/review/reject call (decision null clears it).
export const setEnrichmentOverride = ({ id, decision, note, profile = "tritorc" }) =>
    postEnrichment("override", { id, decision, note, profile }, "Couldn't save your decision. Try again.");

// The sellers enrichment can judge leads for (drives the Tritorc | Ozat toggle).
export async function fetchEnrichmentProfiles() {
    const res = await authorizedFetch(`${API_BASE}/enrichment/profiles`);
    if (!res.ok) throw new Error("Failed to load sellers");
    return res.json();
}

export async function fetchEnrichments({ q = "", category = "", skip = 0, limit = 50, profile = "tritorc" } = {}) {
    const params = new URLSearchParams({ skip, limit, profile });
    if (q) params.set("q", q);
    if (category) params.set("category", category);
    const res = await authorizedFetch(`${API_BASE}/enrichment?${params}`);
    if (!res.ok) throw new Error("Failed to load stored enrichments");
    return res.json();
}

export async function downloadEnrichmentXlsx(results) {
    const res = await authorizedFetch(`${API_BASE}/enrichment/export-xlsx`, {
        method: "POST",
        body: JSON.stringify({ results }),
    });
    if (!res.ok) throw new Error("Export failed");
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "company_enrichment.xlsx";
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
}
