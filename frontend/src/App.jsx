import { useCallback, useEffect, useState } from "react";
import { flushSync } from "react-dom";
import { api } from "./api.js";
import { Brand } from "./Icons.jsx";
import { CustomerPage } from "./CustomerPage.jsx";
import { CustomersPage } from "./CustomersPage.jsx";
import { Login } from "./Login.jsx";
import { PasswordDialog } from "./PasswordDialog.jsx";
import { ModelPage } from "./ModelPage.jsx";
import { Overview } from "./Overview.jsx";
import { Sidebar } from "./Sidebar.jsx";
import { SourcePage } from "./SourcePage.jsx";
import { SkeletonRows, Toast, Topbar } from "./Shared.jsx";
import { pageHref, readHash } from "./routes.js";

function toCsvCell(cell) {
  const value = String(cell);
  const safeValue = /^[\t\r\n ]*[=+\-@]/.test(value) ? `'${value}` : value;
  return `"${safeValue.replaceAll('"', '""')}"`;
}

function initialTheme() {
  try {
    const saved = window.localStorage.getItem("aeza-theme");
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* Хранилище может быть недоступно — берём системную тему. */
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

const CUSTOMER_PAGE_SIZE = 10;
const OVERVIEW_ROWS = 200;
const EXPORT_PAGE_SIZE = 200;

const pageTitles = {
  overview: [{ label: "Обзор" }],
  customers: [{ label: "Клиенты" }],
  model: [{ label: "Управление" }, { label: "Модель риска" }],
  source: [{ label: "Управление" }, { label: "Источник данных" }],
};

export default function App() {
  const [authenticated, setAuthenticated] = useState(false);
  const [checkingSession, setCheckingSession] = useState(true);
  const [user, setUser] = useState(null);
  const [page, setPage] = useState(() => readHash().page);
  const [customerId, setCustomerId] = useState(() => readHash().customerId);
  const [summary, setSummary] = useState(null);
  const [outflow, setOutflow] = useState(null);
  const [outflowDays, setOutflowDays] = useState(30);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [customers, setCustomers] = useState([]);
  const [total, setTotal] = useState(0);
  const [settings, setSettings] = useState(null);
  const [activeReason, setActiveReason] = useState("");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [theme, setTheme] = useState(initialTheme);
  const [live, setLive] = useState({ state: "online", updatedAt: null });
  const [version, setVersion] = useState(0);
  const [updates, setUpdates] = useState([]);
  const [filters, setFilters] = useState(() => ({
    q: "",
    risk_level: readHash().risk,
    sort_by: "revenue_at_risk",
    order: "desc",
  }));
  const [debouncedQuery, setDebouncedQuery] = useState("");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", theme === "dark" ? "#111113" : "#f4f4f4");
    try {
      window.localStorage.setItem("aeza-theme", theme);
    } catch {
      /* Тема просто не запомнится между сессиями. */
    }
  }, [theme]);

  useEffect(() => {
    let active = true;
    api
      .me()
      .then((currentUser) => {
        if (!active) return;
        setUser(currentUser);
        setAuthenticated(true);
      })
      .catch(() => {
        if (active) setAuthenticated(false);
      })
      .finally(() => {
        if (active) setCheckingSession(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const sync = () => {
      const route = readHash();
      setPage(route.page);
      setCustomerId(route.customerId);
      // Уровень риска живёт в адресе списка клиентов; обзор всегда по всем.
      if (route.page === "customers" || route.page === "overview")
        setFilters((current) => ({ ...current, risk_level: route.risk }));
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(filters.q), 220);
    return () => window.clearTimeout(timer);
  }, [filters.q]);

  const refreshData = useCallback(async () => {
    if (!authenticated) return;
    setLoading(true);
    try {
      const onCustomers = page === "customers";
      const [nextSummary, nextOutflow, nextCustomers, nextSettings] = await Promise.all([
        api.summary(),
        api.outflow(outflowDays),
        api.customers({
          q: debouncedQuery,
          risk_level: filters.risk_level,
          reason: activeReason,
          sort_by: filters.sort_by,
          order: filters.order,
          limit: onCustomers ? CUSTOMER_PAGE_SIZE : OVERVIEW_ROWS,
          offset: onCustomers ? (pageNumber - 1) * CUSTOMER_PAGE_SIZE : 0,
        }),
        api.settings(),
      ]);
      setSummary(nextSummary);
      setOutflow(nextOutflow);
      setCustomers(nextCustomers.items);
      setTotal(nextCustomers.total);
      setSettings(nextSettings);
      setLive((current) => ({
        ...current,
        updatedAt: nextSummary.calculated_at,
      }));
    } catch (error) {
      if (error.status === 401) {
        setAuthenticated(false);
        setUser(null);
      } else setToast({ kind: "error", message: error.message });
    } finally {
      setLoading(false);
    }
  }, [
    authenticated,
    activeReason,
    outflowDays,
    debouncedQuery,
    filters.risk_level,
    filters.sort_by,
    filters.order,
    page,
    pageNumber,
  ]);

  useEffect(() => {
    refreshData();
  }, [refreshData]);

  useEffect(() => {
    if (!authenticated) return undefined;
    const stream = new EventSource("/api/v1/events");
    stream.addEventListener("connected", () =>
      setLive((current) => ({ ...current, state: "online" })),
    );
    stream.addEventListener("data_changed", (event) => {
      let payload = {};
      try {
        payload = JSON.parse(event.data);
      } catch {
        /* Событие без тела всё равно означает «данные изменились». */
      }
      setUpdates((current) =>
        [
          {
            id: `${Date.now()}-${current.length}`,
            type: payload.type,
            at: payload.changed_at || new Date().toISOString(),
          },
          ...current,
        ].slice(0, 8),
      );
      setVersion((value) => value + 1);
      refreshData();
    });
    stream.onerror = () =>
      setLive((current) => ({ ...current, state: "reconnecting" }));
    return () => stream.close();
  }, [authenticated, refreshData]);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(() => setToast(null), 4600);
    return () => window.clearTimeout(timer);
  }, [toast]);

  // Новая тема раскрывается кругом от кнопки (View Transitions API).
  // Без поддержки API или при «уменьшить движение» тема меняется сразу.
  function toggleTheme(button) {
    const next = theme === "dark" ? "light" : "dark";
    const apply = () => {
      flushSync(() => setTheme(next));
      document.documentElement.dataset.theme = next;
    };
    const reduced = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    if (!document.startViewTransition || reduced) {
      apply();
      return;
    }
    const rect = button.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    const radius = Math.hypot(
      Math.max(x, window.innerWidth - x),
      Math.max(y, window.innerHeight - y),
    );
    document
      .startViewTransition(apply)
      .ready.then(() => {
        document.documentElement.animate(
          {
            clipPath: [
              `circle(0px at ${x}px ${y}px)`,
              `circle(${radius}px at ${x}px ${y}px)`,
            ],
          },
          {
            duration: 550,
            easing: "cubic-bezier(0.65, 0, 0.35, 1)",
            pseudoElement: "::view-transition-new(root)",
          },
        );
      })
      .catch(() => {});
  }

  async function handleLogin(username, password) {
    const result = await api.login(username, password);
    setUser(result.user);
    setAuthenticated(true);
  }

  async function handleLogout() {
    try {
      await api.logout();
    } catch {
      /* The session may already have expired. */
    }
    setAuthenticated(false);
    setSummary(null);
    setOutflow(null);
    setCustomers([]);
    setSettings(null);
    setUser(null);
    setUpdates([]);
    setPasswordOpen(false);
    setPage("overview");
  }

  async function handleSaveSettings(payload) {
    setSaving(true);
    try {
      const saved = await api.saveSettings(payload);
      setSettings(saved);
      await refreshData();
      setToast({
        kind: "success",
        message: "Сохранено. Рейтинг и деньги пересчитаны.",
      });
    } finally {
      setSaving(false);
    }
  }

  function handleSort(key) {
    setFilters((current) => ({
      ...current,
      sort_by: key,
      order:
        current.sort_by === key
          ? current.order === "desc"
            ? "asc"
            : "desc"
          : key === "id" || key === "email"
            ? "asc"
            : "desc",
    }));
    setPageNumber(1);
  }

  async function exportCsv() {
    setToast({ kind: "success", message: "Готовим CSV по всем клиентам…" });
    try {
      const all = [];
      let offset = 0;
      let totalCount = Infinity;
      while (offset < totalCount && offset < 5000) {
        const chunk = await api.customers({
          q: debouncedQuery,
          risk_level: filters.risk_level,
          reason: activeReason,
          sort_by: filters.sort_by,
          order: filters.order,
          limit: EXPORT_PAGE_SIZE,
          offset,
        });
        all.push(...chunk.items);
        totalCount = chunk.total;
        offset += EXPORT_PAGE_SIZE;
        if (!chunk.items.length) break;
      }
      const header = [
        "ID",
        "Email",
        "Баланс EUR",
        "Пополнено EUR",
        "Индекс аккаунта",
        "Уровень риска",
        "Ожидаемо EUR",
        "Максимум EUR",
        "Из ожидаемого: не хватает средств EUR",
        "Причина",
        "Действие",
      ];
      // Без оценки риска сумму не считаем: ячейка пустая, а не ноль.
      const euro = (customer, minor) =>
        customer.risk_score == null ? "" : (minor / 100).toFixed(2);
      const rows = all.map((customer) => [
        customer.id,
        customer.email,
        (customer.balance_minor / 100).toFixed(2),
        (customer.total_replenished_minor / 100).toFixed(2),
        customer.risk_score ?? "",
        customer.risk_label,
        euro(customer, customer.revenue_at_risk_minor),
        euro(customer, customer.near_term_loss_minor),
        euro(customer, customer.potential_loss_minor),
        customer.reasons?.[0]?.title || "",
        customer.recommended_action?.text || "",
      ]);
      const csv = [header, ...rows]
        .map((row) => row.map(toCsvCell).join(";"))
        .join("\r\n");
      const link = document.createElement("a");
      const downloadUrl = URL.createObjectURL(
        new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" }),
      );
      link.href = downloadUrl;
      link.download = "aeza-risk-clients.csv";
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 0);
      setToast({ kind: "success", message: `CSV готов: ${rows.length} клиентов.` });
    } catch (error) {
      if (error.status === 401) setAuthenticated(false);
      else setToast({ kind: "error", message: error.message });
    }
  }

  if (checkingSession)
    return (
      <div className="boot">
        <Brand />
        <span className="skeleton" style={{ width: 160 }} />
      </div>
    );
  if (!authenticated)
    return (
      <>
        <Login
          onLogin={handleLogin}
          onRegistered={(registered) => {
            setUser(registered);
            setAuthenticated(true);
          }}
        />
        <Toast
          message={toast?.message}
          kind={toast?.kind}
          onClose={() => setToast(null)}
        />
      </>
    );

  function goTo(nextPage) {
    window.history.pushState(null, "", pageHref(nextPage));
    setPage(nextPage);
    setActiveReason("");
    setPageNumber(1);
    if (nextPage === "overview")
      setFilters((current) => ({
        ...current,
        q: "",
        risk_level: "",
        sort_by: "revenue_at_risk",
        order: "desc",
      }));
    window.scrollTo(0, 0);
  }

  const navigate = {
    page: goTo,
    filter: (riskLevel) => {
      window.history.pushState(
        null,
        "",
        riskLevel ? `#/customers?risk=${riskLevel}` : "#/customers",
      );
      setFilters((current) => ({ ...current, risk_level: riskLevel }));
      setPage("customers");
      setActiveReason("");
      setPageNumber(1);
      window.scrollTo(0, 0);
    },
  };

  function openCustomer(id) {
    if (window.location.hash !== pageHref("customer", id))
      window.history.pushState(null, "", pageHref("customer", id));
    setCustomerId(id);
    setPage("customer");
    window.scrollTo(0, 0);
  }

  const crumbs =
    page === "customer"
      ? [
          { label: "Клиенты", onClick: () => goTo("customers") },
          { label: customerId },
        ]
      : pageTitles[page];

  return (
    <div className="app-shell">
      <a
        className="skip-link"
        href="#/"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        Перейти к содержимому
      </a>
      <Sidebar
        page={page}
        setPage={goTo}
        user={user}
        summary={summary}
        onLogout={handleLogout}
        onChangePassword={() => setPasswordOpen(true)}
        mobileOpen={mobileOpen}
        setMobileOpen={setMobileOpen}
      />
      <main className="main" id="main" tabIndex="-1">
        <div className="main-inner">
          <Topbar
            crumbs={crumbs}
            live={live}
            theme={theme}
            onTheme={(event) => toggleTheme(event.currentTarget)}
            onMenu={() => setMobileOpen(true)}
          />
          {loading && !summary ? (
            <section className="table-card">
              <SkeletonRows />
            </section>
          ) : (
            <>
              {page === "overview" && (
                <Overview
                  summary={summary}
                  outflow={outflow}
                  outflowDays={outflowDays}
                  setOutflowDays={setOutflowDays}
                  customers={customers}
                  activeReason={activeReason}
                  setActiveReason={setActiveReason}
                  onSelectCustomer={openCustomer}
                  onNavigate={navigate}
                  sortBy={filters.sort_by}
                  order={filters.order}
                  onSort={handleSort}
                  onExport={exportCsv}
                />
              )}
              {page === "customers" && (
                <CustomersPage
                  customers={customers}
                  total={total}
                  summary={summary}
                  filters={filters}
                  setFilters={setFilters}
                  loading={loading}
                  onSelectCustomer={openCustomer}
                  onSort={handleSort}
                  onExport={exportCsv}
                  pageNumber={pageNumber}
                  setPageNumber={setPageNumber}
                />
              )}
              {page === "customer" && (
                <CustomerPage
                  id={customerId}
                  version={version}
                  onToast={setToast}
                />
              )}
              {page === "model" && (
                <ModelPage
                  settings={settings}
                  summary={summary}
                  onSave={handleSaveSettings}
                  saving={saving}
                />
              )}
              {page === "source" && (
                <SourcePage
                  summary={summary}
                  updates={updates}
                  version={version}
                  onToast={setToast}
                />
              )}
            </>
          )}
        </div>
      </main>
      {passwordOpen && (
        <PasswordDialog
          username={user?.username}
          onExpired={() => {
            setPasswordOpen(false);
            setAuthenticated(false);
            setUser(null);
          }}
          onClose={() => setPasswordOpen(false)}
          onDone={() => {
            setPasswordOpen(false);
            setToast({
              kind: "success",
              message: "Пароль изменён. Другие сессии завершены.",
            });
          }}
        />
      )}
      <Toast
        message={toast?.message}
        kind={toast?.kind}
        onClose={() => setToast(null)}
      />
    </div>
  );
}
