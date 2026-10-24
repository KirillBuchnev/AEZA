async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      credentials: "include",
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...options.headers,
      },
    });
  } catch {
    throw new Error("Нет связи с сервером. Проверьте подключение и попробуйте снова.");
  }

  if (response.status === 204) return null;
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map((item) => {
                const location = Array.isArray(item?.loc)
                  ? item.loc.filter((part) => part !== "body").join(" → ")
                  : "";
                return location ? `${location}: ${item.msg}` : item.msg;
              })
              .filter(Boolean)
              .join("; ") || `Не удалось выполнить запрос (${response.status}).`
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
  register: (payload) =>
    request("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  verifyCodeword: (username, codeword) =>
    request("/api/v1/auth/password/verify-codeword", {
      method: "POST",
      body: JSON.stringify({ username, codeword }),
    }),
  resetPassword: (payload) =>
    request("/api/v1/auth/password/reset", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  changePassword: (payload) =>
    request("/api/v1/auth/password/change", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
