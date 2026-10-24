const pages = new Set(["overview", "customers", "model", "source"]);

// Адрес отражает экран: #/customers, #/customers/1088, #/customers?risk=high
export function readHash() {
  const [path, query = ""] = window.location.hash
    .replace(/^#\/?/, "")
    .split("?");
  const [section, id] = path.split("/");
  const risk = new URLSearchParams(query).get("risk") || "";
  if (section === "customers" && id)
    return { page: "customer", customerId: decodeURIComponent(id), risk };
  return {
    page: pages.has(section) ? section : "overview",
    customerId: "",
    risk,
  };
}

export function pageHref(page, id) {
  if (page === "customer") return `#/customers/${encodeURIComponent(id)}`;
  return page === "overview" ? "#/" : `#/${page}`;
}
