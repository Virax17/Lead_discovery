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
