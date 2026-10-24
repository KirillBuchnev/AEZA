async function request(path, options = {}) {
  const response = await fetch(path, {
    credentials: "include",
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });

  if (response.status === 204) return null;
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail;
    const firstIssue = Array.isArray(detail) ? detail[0] : null;
    const message =
      typeof detail === "string"
        ? detail
        : firstIssue?.msg
          ? `${(firstIssue.loc || []).slice(1).join(".") || "Данные"}: ${firstIssue.msg}.`
          : `Не удалось выполнить запрос (${response.status}).`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return payload;
}

export const api = {
  me: () => request("/api/v1/auth/me"),
  login: (username, password) =>
    request("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request("/api/v1/auth/logout", { method: "POST" }),
  summary: () => request("/api/v1/analytics/summary"),
  customers: (params = {}) => {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "")
        search.set(key, value);
    });
    return request(`/api/v1/customers?${search}`);
  },
  customer: (id) => request(`/api/v1/customers/${encodeURIComponent(id)}`),
  settings: () => request("/api/v1/model/settings"),
  saveSettings: (settings) =>
    request("/api/v1/model/settings", {
      method: "PATCH",
      body: JSON.stringify(settings),
    }),
  uploadSnapshot: (snapshot) =>
    request("/api/v1/source/snapshot", {
      method: "PUT",
      body: JSON.stringify(snapshot),
    }),
  metrics: async () => {
    const response = await fetch("/metrics", { credentials: "include" });
    if (!response.ok)
      throw new Error(`Метрики недоступны (${response.status}).`);
    return response.text();
  },
};
