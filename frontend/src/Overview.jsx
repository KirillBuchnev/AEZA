import { useMemo, useState } from "react";
import { AezaIcon } from "./AezaIcon.jsx";
import { Icon } from "./Icons.jsx";
import {
  CardHead,
  CustomerTable,
  Empty,
  PageHead,
  Segments,
} from "./Shared.jsx";
import { money, moneyShort, plural, riskText } from "./format.js";
import { OutflowChart } from "./OutflowChart.jsx";
import mascotHappy from "./assets/mascot-happy.webp";

const levels = ["high", "medium", "low", "unscored"];
const levelColor = {
  high: "var(--risk-high)",
  medium: "var(--risk-medium)",
  low: "var(--risk-low)",
  unscored: "var(--border-default)",
};

const reasonTitles = {
  autoprolong_disabled: "Ручное продление",
  insufficient_balance: "Не хватает средств",
  renewal_urgency: "Срочность продления",
  prolong_wait: "Ожидание оплаты",
};

// Counts come from the summary, which covers every customer, not from the loaded page.
function topReasons(summary) {
  return Object.entries(summary?.reason_counts || {})
    .filter(([, count]) => count > 0)
    .map(([code, count]) => ({ code, title: reasonTitles[code] || code, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 3);
}

export function Overview({
  summary,
  outflow,
  outflowDays = 30,
  setOutflowDays,
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
  const [level, setLevel] = useState("");
  const counts = summary?.risk_counts || {};
  const horizon = summary?.prediction_horizon_days || 30;
  const high = counts.high ?? 0;
  const reasons = useMemo(() => topReasons(summary), [summary]);
  const maxReason = Math.max(1, ...reasons.map((reason) => reason.count));

  const expectedByLevel = summary?.revenue_at_risk_by_level_minor || {};
  const exposedServices = summary?.exposed_services ?? 0;

  const exposure = useMemo(
    () => (summary?.top_exposure || []).slice(0, 6),
    [summary],
  );
  const maxExposure = Math.max(
    1,
    ...exposure.map((customer) => customer.revenue_at_risk_minor),
  );

  const filtered = customers.filter(
    (customer) =>
      (!level || (customer.risk_level || "unscored") === level) &&
      (!activeReason ||
        customer.reasons?.some((reason) => reason.code === activeReason)),
  );
  const activeReasonTitle = reasons.find(
    (reason) => reason.code === activeReason,
  )?.title;

  return (
    <>
      <PageHead
        title="Риск оттока"
        description="Кому нужно внимание, почему и сколько можем потерять"
      >
        <button
          className="chip chip-link"
          onClick={() => onNavigate.page("model")}
          title="Горизонт меняется в «Модели риска»"
        >
          Горизонт: {horizon} дней
        </button>
        <button className="button button-secondary" onClick={onExport}>
          <Icon name="download" size={16} />
          Экспорт CSV
        </button>
      </PageHead>
      <section className="outflow-section">
        <CardHead
          title="Отток: факты и прогноз"
          description="Слева — что уже ушло по снимкам, справа — услуги под риском по дням решения и ожидаемые непродления. Линия «сегодня» разделяет их."
        />
        <OutflowChart outflow={outflow} days={outflowDays} onDays={setOutflowDays} />
      </section>

      <section className="hero" aria-label="Главное">
        <div className="hero-col">
          <span className="hero-q">
            <AezaIcon name="error" variant="keyBlue" size={34} />
            Кому нужно внимание
          </span>
          <div className="hero-value">
            <span className="display">{high}</span>
            <span className="h2">
              {plural(high, ["клиент", "клиента", "клиентов"])}
            </span>
          </div>
          <span className="hero-note">
            в высоком риске из {summary?.customers_total ?? 0} · ещё{" "}
            {counts.medium ?? 0} в среднем
          </span>
          <button className="link" onClick={() => onNavigate.filter("high")}>
            Показать список →
          </button>
        </div>
        <div className="hero-col">
          <span className="hero-q">
            <AezaIcon name="info" variant="keyBlue" size={34} />
            Главные причины риска
          </span>
          {reasons.length ? (
            reasons.map((reason) => (
              <button
                key={reason.code}
                className="hero-reason"
                onClick={() =>
                  setActiveReason(
                    activeReason === reason.code ? "" : reason.code,
                  )
                }
                aria-pressed={activeReason === reason.code}
              >
                <span className="hero-reason-row">
                  <span>{reason.title}</span>
                  <b>{reason.count}</b>
                </span>
                <span className="hero-bar">
                  <i
                    style={{ width: `${(reason.count / maxReason) * 100}%` }}
                  />
                </span>
              </button>
            ))
          ) : (
            <span className="hero-note">
              Сейчас нет клиентов с активным риском.
            </span>
          )}
        </div>
        <div className="hero-col">
          <span className="hero-q">
            <AezaIcon name="euro" variant="keyBlue" size={34} />
            Сколько можем потерять
          </span>
          <div className="hero-value">
            <span className="display">
              {moneyShort(summary?.revenue_at_risk_minor)}
            </span>
            <span className="h1">€</span>
          </div>
          <span className="hero-note">
            ожидаемо за ближайшие 7 дней · по {exposedServices}{" "}
            {plural(exposedServices, ["услуге", "услугам", "услугам"])} с
            признаками риска
          </span>
          <dl className="hero-money">
            <div>
              <dt>Максимум по этим услугам</dt>
              <dd>{money(summary?.near_term_loss_minor)}</dd>
            </div>
            <div>
              <dt>Из ожидаемого: не хватает средств</dt>
              <dd>{money(summary?.potential_loss_minor)}</dd>
            </div>
          </dl>
          <button className="link" onClick={() => onNavigate.page("model")}>
            Открыть методику →
          </button>
        </div>
        <div className="stripes" aria-hidden="true">
          <i />
          <i />
          <i />
        </div>
      </section>

      <div className="row-split">
        <section className="card">
          <CardHead
            icon="wallet"
            title="Где сосредоточены потери"
            description="Клиенты с наибольшей суммой под риском. Рядом — верхняя граница по тем же услугам."
          />
          {exposure.length ? (
            <div className="exposure">
              {exposure.map((customer) => (
                <button
                  key={customer.id}
                  className="exposure-row"
                  onClick={() => onSelectCustomer(customer.id)}
                  title={`Ожидаемо ${money(customer.revenue_at_risk_minor)}, максимум ${money(customer.near_term_loss_minor)}, из ожидаемого не хватает средств на ${money(customer.potential_loss_minor)}`}
                >
                  <span>{customer.email}</span>
                  <span className="exposure-track">
                    <i
                      style={{
                        width: `${Math.max(3, (customer.revenue_at_risk_minor / maxExposure) * 100)}%`,
                      }}
                    />
                  </span>
                  <span className="exposure-value">
                    <b>{money(customer.revenue_at_risk_minor)}</b>
                    <small>из {money(customer.near_term_loss_minor)}</small>
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <Empty title="Потерь не ожидается">
              Ни у одной услуги в ближайшие 7 дней нет признаков непродления.
            </Empty>
          )}
        </section>
        <section className="card">
          <CardHead
            icon="error"
            title="Уровни риска"
            description={`${summary?.customers_total ?? 0} ${plural(summary?.customers_total ?? 0, ["клиент", "клиента", "клиентов"])} · сумма под риском по уровню`}
          />
          <div className="levels-bar" aria-hidden="true">
            {levels.map((key) =>
              counts[key] ? (
                <i
                  key={key}
                  style={{ flex: counts[key], background: levelColor[key] }}
                />
              ) : null,
            )}
          </div>
          <div className="kv-list">
            {levels.map((key) => (
              <button
                key={key}
                className="kv-row"
                onClick={() => onNavigate.filter(key)}
              >
                <span
                  className={`swatch${key === "unscored" ? " swatch-unscored" : ""}`}
                  style={
                    key === "unscored"
                      ? undefined
                      : { background: levelColor[key] }
                  }
                />
                <span>{riskText[key]}</span>
                <b>{counts[key] ?? 0}</b>
                <em>{key === "unscored" ? "—" : money(expectedByLevel[key])}</em>
              </button>
            ))}
          </div>
          <p className="note small muted">
            <AezaIcon name="info" variant="flat" size={22} />
            «Нет оценки»: у клиента нет активных услуг или дат окончания,
            поэтому риск не считаем.
          </p>
        </section>
      </div>

      <section className="table-card">
        <div className="table-card-head">
          <CardHead
            title={
              activeReasonTitle
                ? `Причина: ${activeReasonTitle}`
                : "Очередь клиентов"
            }
            description="Сверху те, с кого ожидаем потерять больше всего. Нажмите на заголовок колонки, чтобы отсортировать"
          >
            {activeReason && (
              <button className="link" onClick={() => setActiveReason("")}>
                Сбросить причину
              </button>
            )}
          </CardHead>
          <Segments
            label="Фильтр по уровню риска"
            value={level}
            onChange={setLevel}
            items={[
              { value: "", label: "Все", count: summary?.customers_total },
              ...levels.map((key) => ({
                value: key,
                label: riskText[key],
                count: counts[key] ?? 0,
              })),
            ]}
          />
        </div>
        {filtered.length ? (
          <CustomerTable
            customers={filtered.slice(0, 6)}
            sortBy={sortBy}
            order={order}
            onSort={onSort}
            onSelect={onSelectCustomer}
          />
        ) : (
          <Empty
            image={
              level === "high"
                ? { src: mascotHappy, width: 260, height: 390 }
                : undefined
            }
            title={
              level === "high" ? "В высоком риске никого" : "Никого не нашли"
            }
            action={
              <button
                className="button button-secondary"
                onClick={() => {
                  setLevel("");
                  setActiveReason("");
                }}
              >
                Сбросить фильтр
              </button>
            }
          >
            {level === "high"
              ? "Редкий день: никто не собирается уходить."
              : "Попробуйте другой уровень риска."}
          </Empty>
        )}
        <div className="table-foot">
          <span>
            Показано {Math.min(6, filtered.length)} из {filtered.length}
          </span>
          <button className="link" onClick={() => onNavigate.page("customers")}>
            Все клиенты →
          </button>
        </div>
      </section>
    </>
  );
}
