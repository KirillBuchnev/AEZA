import { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { Brand } from "./Icons.jsx";
import { CustomerDrawer } from "./CustomerDrawer.jsx";
import { CustomersPage } from "./CustomersPage.jsx";
import { Login } from "./Login.jsx";
import { PasswordDialog } from "./PasswordDialog.jsx";
import { ModelPage } from "./ModelPage.jsx";
import { Overview } from "./Overview.jsx";
import { Sidebar } from "./Sidebar.jsx";
import { Toast } from "./Shared.jsx";

const CUSTOMER_PAGE_SIZE = 8;

function toCsvCell(cell) {
  const value = String(cell);
  const safeValue = /^[\t\r\n ]*[=+\-@]/.test(value) ? `'${value}` : value;
  return `"${safeValue.replaceAll('"', '""')}"`;
}

export default function App() {
  const [authenticated, setAuthenticated] = useState(false);
  const [checkingSession, setCheckingSession] = useState(true);
  const [user, setUser] = useState(null);
  const [page, setPage] = useState("overview");
  const [summary, setSummary] = useState(null);
  const [customers, setCustomers] = useState([]);
  const [total, setTotal] = useState(0);
  const [settings, setSettings] = useState(null);
  const [drawerId, setDrawerId] = useState("");
  const [activeReason, setActiveReason] = useState("");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [filters, setFilters] = useState({
    q: "",
    risk_level: "",
    sort_by: "risk_score",
    order: "desc",
  });
  const [debouncedQuery, setDebouncedQuery] = useState("");

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
    const timer = window.setTimeout(() => setDebouncedQuery(filters.q), 220);
    return () => window.clearTimeout(timer);
  }, [filters.q]);

  const refreshData = useCallback(async () => {
    if (!authenticated) return;
    setLoading(true);
    try {
      const [nextSummary, nextCustomers, nextSettings] = await Promise.all([
        api.summary(),
        api.customers({
          q: debouncedQuery,
          risk_level: filters.risk_level,
          sort_by: filters.sort_by,
          order: filters.order,
          limit: page === "customers" ? CUSTOMER_PAGE_SIZE : 200,
          offset:
            page === "customers" ? (pageNumber - 1) * CUSTOMER_PAGE_SIZE : 0,
        }),
        api.settings(),
      ]);
      setSummary(nextSummary);
      setCustomers(nextCustomers.items);
      setTotal(nextCustomers.total);
      setSettings(nextSettings);
    } catch (error) {
      if (error.status === 401) {
        setAuthenticated(false);
        setUser(null);
        setPasswordOpen(false);
        setDrawerId("");
        setSummary(null);
        setCustomers([]);
        setSettings(null);
        setPage("overview");
      } else setToast({ kind: "error", message: error.message });
    } finally {
      setLoading(false);
    }
  }, [
    authenticated,
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
    stream.addEventListener("data_changed", () => {
      refreshData();
    });
    // On a dropped stream, a fresh read tells whether the session is still valid.
    stream.addEventListener("error", () => {
      refreshData();
    });
    return () => stream.close();
  }, [authenticated, refreshData]);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(() => setToast(null), 4600);
    return () => window.clearTimeout(timer);
  }, [toast]);

  function handleSession(currentUser) {
    setUser(currentUser);
    setAuthenticated(true);
  }

  async function handleLogout() {
    try {
      await api.logout();
    } catch {
      /* The session may already have expired. */
    }
    setAuthenticated(false);
    setPasswordOpen(false);
    setDrawerId("");
    setSummary(null);
    setCustomers([]);
    setSettings(null);
    setUser(null);
    setPage("overview");
  }

  async function handleSaveSettings(draft) {
    setSaving(true);
    try {
      const saved = await api.saveSettings({
        prediction_horizon_days: Number(draft.prediction_horizon_days),
        high_risk_min: Number(draft.high_risk_min),
        medium_risk_min: Number(draft.medium_risk_min),
        weights: draft.weights,
      });
      setSettings(saved);
      await refreshData();
      setToast({
        kind: "success",
        message: "Настройки сохранены. Оценки клиентов пересчитаны.",
      });
    } catch (error) {
      throw error;
    } finally {
      setSaving(false);
    }
  }

  function handleSort(key) {
    const sortMap = {
      balance: "balance",
      risk_score: "risk_score",
      potential_loss: "potential_loss",
      id: "id",
    };
    const nextSort = sortMap[key] || key;
    setFilters((current) => ({
      ...current,
      sort_by: nextSort,
      order:
        current.sort_by === nextSort && current.order === "desc"
          ? "asc"
          : "desc",
    }));
    setPageNumber(1);
  }

  function exportCsv() {
    const header = [
      "ID",
      "Email",
      "Баланс EUR",
      "Оценка риска",
      "Уровень риска",
      "Сумма риска EUR",
      "Причина",
    ];
    const rows = customers.map((customer) => [
      customer.id,
      customer.email,
      (customer.balance_minor / 100).toFixed(2),
      customer.risk_score ?? "",
      customer.risk_label,
      (customer.potential_loss_minor / 100).toFixed(2),
      customer.reasons?.[0]?.title || "",
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
    setToast({
      kind: "success",
      message: `CSV готов: ${rows.length} клиентов.`,
    });
  }

  if (checkingSession)
    return (
      <div className="app-loading">
        <Brand />
        <span className="spinner" />
        <p>Открываем рабочее пространство…</p>
      </div>
    );
  if (!authenticated)
    return (
      <>
        <Login onSession={handleSession} />
        <Toast
          message={toast?.message}
          kind={toast?.kind}
          onClose={() => setToast(null)}
        />
      </>
    );

  const navigate = {
    page: (nextPage) => {
      setPage(nextPage);
      setActiveReason("");
      setPageNumber(1);
    },
    menu: () => setMobileOpen(true),
    filter: (riskLevel) => {
      setFilters((current) => ({ ...current, risk_level: riskLevel }));
      setPage("customers");
      setActiveReason("");
      setPageNumber(1);
    },
  };
  const isLoadingOnly = loading && !summary;

  return (
    <div className="app-shell">
      <Sidebar
        page={page}
        setPage={(nextPage) => {
          setPage(nextPage);
          setPageNumber(1);
          if (nextPage === "overview") {
            setFilters((current) => ({
              ...current,
              q: "",
              risk_level: "",
              sort_by: "risk_score",
              order: "desc",
            }));
            setActiveReason("");
          }
        }}
        user={user}
        onLogout={handleLogout}
        onChangePassword={() => setPasswordOpen(true)}
        mobileOpen={mobileOpen}
        setMobileOpen={setMobileOpen}
      />
      <main className="main-content">
        <div className="main-content-inner">
          {isLoadingOnly ? (
            <div className="panel loading-card">
              <span className="spinner" />
              Загружаем рабочие данные…
            </div>
          ) : (
            <>
              {page === "overview" && (
                <Overview
                  summary={summary}
                  customers={customers}
                  activeReason={activeReason}
                  setActiveReason={setActiveReason}
                  onSelectCustomer={setDrawerId}
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
                  filters={filters}
                  setFilters={setFilters}
                  onSelectCustomer={setDrawerId}
                  onNavigate={navigate}
                  onSort={handleSort}
                  pageNumber={pageNumber}
                  setPageNumber={setPageNumber}
                />
              )}
              {page === "model" && (
                <ModelPage
                  settings={settings}
                  onSave={handleSaveSettings}
                  saving={saving}
                />
              )}
            </>
          )}
          <footer className="app-footer">
            <span>
              <Brand compact />
            </span>
            <span className="footer-live">
              <i />
              Данные обновлены{" "}
              {summary?.calculated_at
                ? new Intl.DateTimeFormat("ru-RU", {
                    hour: "2-digit",
                    minute: "2-digit",
                  }).format(new Date(summary.calculated_at))
                : "—"}
            </span>
          </footer>
        </div>
      </main>
      {drawerId && (
        <CustomerDrawer id={drawerId} onClose={() => setDrawerId("")} />
      )}
      {passwordOpen && (
        <PasswordDialog
          username={user?.username}
          onExpired={() => {
            setPasswordOpen(false);
            setDrawerId("");
            setAuthenticated(false);
            setUser(null);
            setSummary(null);
            setCustomers([]);
            setSettings(null);
            setPage("overview");
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
