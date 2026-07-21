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
    const res = await fetch(`${API_BASE}/quota/status`, { headers: getHeaders() });
    if (!res.ok) {
        if (res.status === 401) throw new Error("Unauthorized");
        throw new Error("Failed to fetch quota");
    }
    return res.json();
}

export async function fetchAdminUsers() {
    const res = await fetch(`${API_BASE}/admin/users`, { headers: getHeaders() });
    if (!res.ok) throw new Error("Failed to fetch users");
    return res.json();
}

export async function createAdminUser(payload) {
    const res = await fetch(`${API_BASE}/admin/users`, {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || "Failed to create user");
    }
    return res.json();
}

export async function updateAdminUserPassword(username, password) {
    const res = await fetch(`${API_BASE}/admin/users/${encodeURIComponent(username)}/password`, {
        method: "PUT",
        headers: getHeaders(),
        body: JSON.stringify({ password }),
    });
    if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || "Failed to update password");
    }
    return res.json();
}

export async function normalizeAdminCountries() {
    const res = await fetch(`${API_BASE}/admin/normalize-countries`, {
        method: "POST",
        headers: getHeaders(),
    });
    if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || "Failed to normalize countries");
    }
    return res.json();
}

export async function updateAdminUserActive(username, active) {
    const res = await fetch(`${API_BASE}/admin/users/${encodeURIComponent(username)}/active`, {
        method: "PUT",
        headers: getHeaders(),
        body: JSON.stringify({ active }),
    });
    if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || "Failed to update user status");
    }
    return res.json();
}

export async function fetchCountries() {
    const res = await fetch(`${API_BASE}/countries`, { headers: getHeaders() });
    if (!res.ok) throw new Error("Failed to fetch countries");
    return res.json();
}

export async function fetchPopulatedCountries() {
    const res = await fetch(`${API_BASE}/businesses/countries`, { headers: getHeaders() });
    if (!res.ok) throw new Error("Failed to fetch countries with data");
    return res.json();
}

export async function fetchCountryBusinesses(country, page = 1) {
    const params = new URLSearchParams({ country, page });
    const res = await fetch(`${API_BASE}/businesses?${params.toString()}`, { headers: getHeaders() });
    if (!res.ok) throw new Error("Failed to fetch country businesses");
    return res.json();
}

export function getCountryExportUrl(country, format, selectedColumns = []) {
    const params = new URLSearchParams({ country, format });
    selectedColumns.forEach(column => params.append("selected_columns", column));
    return `${API_BASE}/businesses/export?${params.toString()}`;
}

export async function downloadCountryExport(country, format, selectedColumns = []) {
    const res = await fetch(getCountryExportUrl(country, format, selectedColumns), { headers: getHeaders() });
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
    const res = await fetch(`${API_BASE}/searches`, {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error("Failed to create search");
    return res.json();
}

export async function fetchSearch(id) {
    const res = await fetch(`${API_BASE}/searches/${id}`, { headers: getHeaders() });
    if (!res.ok) throw new Error("Failed to fetch search");
    return res.json();
}

export async function fetchHistory(page = 1, pageSize = 20) {
    const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
    });
    const res = await fetch(`${API_BASE}/searches?${params.toString()}`, { headers: getHeaders() });
    if (!res.ok) throw new Error("Failed to fetch history");
    return res.json();
}

export function getExportUrl(id, format, selectedColumns = []) {
    const params = new URLSearchParams({ format });
    selectedColumns.forEach(column => params.append("selected_columns", column));
    return `${API_BASE}/searches/${id}/export?${params.toString()}`;
}

export async function downloadFile(id, format, selectedColumns = []) {
    const res = await fetch(getExportUrl(id, format, selectedColumns), { headers: getHeaders() });
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
