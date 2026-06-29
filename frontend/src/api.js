const API_BASE = "http://localhost:8000/api";

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
    
    if (!res.ok) throw new Error("Login failed");
    const data = await res.json();
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

export async function fetchHistory() {
    const res = await fetch(`${API_BASE}/searches`, { headers: getHeaders() });
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
