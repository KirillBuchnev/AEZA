import { useMemo } from "react";
import { Icon } from "./Icons.jsx";
import { CustomerTable, MetricCard, PageHeader } from "./Shared.jsx";
import { featureOrder, money } from "./format.js";

export function ReasonList({ customers, activeReason, onSelect }) {
  const reasons = useMemo(() => {
    const counts = new Map();
    customers.forEach((customer) =>
      customer.reasons?.forEach((reason) => {
        if (reason.code === "no_active_signals") return;
        const item = counts.get(reason.code) || { ...reason, count: 0 };
        item.count += 1;
        counts.set(reason.code, item);
      }),
    );
    return featureOrder.map((code) => counts.get(code)).filter(Boolean);
  }, [customers]);

  return (
    <div className="reason-list">
      <button
        className={`reason-row${activeReason === "" ? " reason-row-active" : ""}`}
        aria-pressed={activeReason === ""}
        onClick={() => onSelect("")}
      >
        <span className="reason-marker reason-marker-all">
          <Icon name="grid" size={16} />
        </span>
        <span className="reason-copy">
          <b>Все причины</b>
          <small>Полная картина клиентов</small>
        </span>
        <span className="reason-count">{customers.length}</span>
      </button>
      {reasons.map((reason) => (
        <button
          key={reason.code}
          className={`reason-row${activeReason === reason.code ? " reason-row-active" : ""}`}
          aria-pressed={activeReason === reason.code}
          onClick={() => onSelect(reason.code)}
        >
          <span className={`reason-marker reason-marker-${reason.code}`}>
            <Icon
              name={
                reason.code === "insufficient_balance"
                  ? "wallet"
                  : reason.code === "prolong_wait"
                    ? "clock"
                    : "pulse"
              }
              size={16}
            />
          </span>
          <span className="reason-copy">
            <b>{reason.title}</b>
            <small>{reason.explanation}</small>
          </span>
          <span className="reason-count">{reason.count}</span>
        </button>
      ))}
    </div>
  );
}

export function ExposureBars({ customers }) {
  const data = useMemo(
    () =>
      [...customers]
        .filter((customer) => customer.potential_loss_minor > 0)
        .sort((a, b) => b.potential_loss_minor - a.potential_loss_minor)
        .slice(0, 5),
    [customers],
  );
  const max = Math.max(
    1,
    ...data.map((customer) => customer.potential_loss_minor),
  );
  return (
    <div className="exposure-bars">
      {data.length ? (
        data.map((customer) => (
          <div
            key={customer.id}
            className="exposure-row"
            title={`${customer.email}: ${money(customer.potential_loss_minor)}`}
          >
            <span className="exposure-email">{customer.email}</span>
            <span className="exposure-track">
              <i
                style={{
                  width: `${Math.max(5, (customer.potential_loss_minor / max) * 100)}%`,
                }}
              />
            </span>
            <b>{money(customer.potential_loss_minor)}</b>
          </div>
        ))
      ) : (
        <div className="chart-empty">
          Пока нет клиентов с рассчитанной суммой риска.
        </div>
      )}
    </div>
  );
}

export function Overview({
  summary,
  customers,
  activeReason,
  setActiveReason,
  onSelectCustomer,
  onNavigate,
  sortBy,
  order,
  onSort,
  onExport,
}) {
  const filtered = activeReason
    ? customers.filter((customer) =>
        customer.reasons?.some((reason) => reason.code === activeReason),
      )
    : customers;
  const displayed = filtered.slice(0, 6);
  const scored = summary?.assessed_total || 0;
  const total = summary?.customers_total || 0;
  const reasonLabel = activeReason
    ? filtered[0]?.reasons.find((reason) => reason.code === activeReason)?.title
    : "Приоритетные клиенты";
  return (
    <>
      <PageHeader
        eyebrow="ЦЕНТР УДЕРЖАНИЯ"
        title="Риск непродления"
        description="Поймите, кому помочь в первую очередь и какая выручка под угрозой."
        onMenu={onNavigate.menu}
        action={
          <>
            <span className="horizon-chip">
              <Icon name="clock" size={16} />
              Следующие {summary?.prediction_horizon_days || 30} дней
            </span>
            <button
              className="button button-secondary export-button"
              onClick={onExport}
            >
              <Icon name="download" size={16} />
              Скачать CSV
            </button>
          </>
        }
      />
      <section className="metric-grid" aria-label="Сводка по клиентам">
        <MetricCard
          label="Клиентов оценено"
          value={
            <>
              {scored}
              <span className="metric-total"> / {total}</span>
            </>
          }
          note="По текущим данным"
          icon="users"
          onClick={() => onNavigate.page("customers")}
        />
        <MetricCard
          label="Высокий риск"
          value={summary?.risk_counts?.high ?? "—"}
          note={`${summary?.risk_counts?.medium ?? 0} со средним риском`}
          icon="pulse"
          tone="metric-high"
          onClick={() => onNavigate.filter("high")}
        />
        <MetricCard
          label="Выручка под риском"
          value={money(summary?.potential_loss_minor)}
          note={`За ${summary?.prediction_horizon_days || 30} дней · оценка`}
          icon="wallet"
          tone="metric-highlight"
        />
        <MetricCard
          label="Недостаточно данных"
          value={summary?.risk_counts?.unscored ?? "—"}
          note="Нужна проверка источника"
          icon="info"
          tone="metric-muted"
          onClick={() => onNavigate.filter("unscored")}
        />
      </section>
      <section className="overview-grid">
        <article className="panel reason-panel">
          <div className="panel-heading">
            <div>
              <span className="section-index">01 / СИГНАЛЫ</span>
              <h2>Почему клиенты в риске</h2>
              <p>Выберите причину, чтобы сузить список.</p>
            </div>
            <span className="heading-icon">
              <Icon name="pulse" />
            </span>
          </div>
          <ReasonList
            customers={customers}
            activeReason={activeReason}
            onSelect={setActiveReason}
          />
          <div className="reason-footnote">
            <span className="mini-check">
              <Icon name="check" size={13} />
            </span>
            Оценка объясняется конкретными сигналами
          </div>
        </article>
        <article className="panel priority-panel">
          <div className="panel-heading priority-heading">
            <div>
              <span className="section-index">02 / ВЫБОРКА</span>
              <h2>{reasonLabel || "Приоритетные клиенты"}</h2>
              <p>
                {activeReason
                  ? `${filtered.length} клиентов с этой причиной`
                  : "Клиенты, которым стоит уделить внимание в первую очередь"}
              </p>
            </div>
            <button
              className="text-link"
              onClick={() => onNavigate.page("customers")}
            >
              Все клиенты <Icon name="arrow" size={15} />
            </button>
          </div>
          <CustomerTable
            customers={displayed}
            onSelect={onSelectCustomer}
            sortBy={sortBy}
            order={order}
            onSort={onSort}
            compact
          />
          {filtered.length > 6 && (
            <button
              className="table-more"
              onClick={() => onNavigate.page("customers")}
            >
              Показать всех {filtered.length} клиентов{" "}
              <Icon name="arrow" size={15} />
            </button>
          )}
        </article>
      </section>
      <section className="panel exposure-panel">
        <div className="panel-heading exposure-heading">
          <div>
            <span className="section-index">03 / ДЕНЕЖНЫЙ ЭФФЕКТ</span>
            <h2>Где сосредоточена сумма риска</h2>
            <p>
              Потенциальная потеря учитывает недостаток средств и оценку
              клиента.
            </p>
          </div>
          <div className="exposure-total">
            <small>Общая оценка</small>
            <b>{money(summary?.potential_loss_minor)}</b>
          </div>
        </div>
        <ExposureBars customers={customers} />
        <div className="calculation-note">
          <Icon name="info" size={15} />
          <span>
            Это ориентир для работы команды, а не гарантированный финансовый
            прогноз.
          </span>
          <button onClick={() => onNavigate.page("model")}>
            Как считается <Icon name="arrow" size={14} />
          </button>
        </div>
      </section>
    </>
  );
}
