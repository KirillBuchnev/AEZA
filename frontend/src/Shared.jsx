import { AezaIcon } from "./AezaIcon.jsx";
import { pageHref } from "./routes.js";
import { Icon, RiskKey } from "./Icons.jsx";
import { money, plural, timeLabel } from "./format.js";

export function Topbar({ crumbs, live, theme, onTheme, onMenu }) {
  return (
    <div className="topbar">
      <button
        className="icon-button menu-button"
        aria-label="Открыть меню"
        onClick={onMenu}
      >
        <Icon name="menu" size={18} />
      </button>
      <nav className="crumbs" aria-label="Путь">
        {crumbs.map((crumb, index) => {
          const last = index === crumbs.length - 1;
          return (
            <span key={crumb.label} style={{ display: "contents" }}>
              {index > 0 && <span aria-hidden="true">/</span>}
              {last ? (
                <b>{crumb.label}</b>
              ) : crumb.onClick ? (
                <button onClick={crumb.onClick}>{crumb.label}</button>
              ) : (
                <span>{crumb.label}</span>
              )}
            </span>
          );
        })}
      </nav>
      <LiveStatus {...live} />
      <button
        className="icon-button theme-key"
        onClick={onTheme}
        aria-label={
          theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему"
        }
        title={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
      >
        <span key={theme} className="theme-icon">
          <Icon name={theme === "dark" ? "sun" : "moon"} size={16} />
        </span>
      </button>
    </div>
  );
}

export function LiveStatus({ state, updatedAt }) {
  const time = timeLabel(updatedAt);
  const text =
    state === "reconnecting"
      ? `Нет связи, переподключаемся… Данные на ${time}`
      : `Обновляется автоматически · ${time}`;
  return (
    <span className="live" role="status" title={text}>
      <span className={`dot${state === "reconnecting" ? " dot-medium" : ""}`} />
      <span className="live-text">{text}</span>
    </span>
  );
}

export function PageHead({ title, description, children }) {
  return (
    <div className="page-head">
      <div className="page-head-text">
        <h1 className="h1">{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {children && <div className="page-head-actions">{children}</div>}
    </div>
  );
}

export function CardHead({ icon, title, description, children }) {
  return (
    <div className="card-head">
      {icon && <AezaIcon name={icon} size={44} />}
      <div className="card-head-text">
        <h2 className="h2">{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {children}
    </div>
  );
}

export function Segments({ items, value, onChange, label }) {
  return (
    <div className="segments" role="group" aria-label={label}>
      {items.map((item) => (
        <button
          key={item.value}
          className={`segment${value === item.value ? " segment-active" : ""}`}
          aria-pressed={value === item.value}
          onClick={() => onChange(item.value)}
        >
          {item.label}
          {item.count != null && <small>{item.count}</small>}
        </button>
      ))}
    </div>
  );
}

export function mainReason(customer) {
  const reasons = (customer.reasons || []).filter(
    (reason) => reason.code !== "no_active_signals",
  );
  if (!reasons.length)
    return {
      title: customer.reasons?.[0]?.title || "Признаков риска нет",
      detail: customer.reasons?.[0]?.explanation || "",
    };
  const rest = reasons.length - 1;
  const available =
    (customer.balance_minor || 0) +
    (customer.bonus_spend_enabled ? customer.bonus_balance_minor || 0 : 0);
  const specific =
    reasons[0].code === "insufficient_balance" && customer.due_revenue_minor
      ? `Нужно ${money(customer.due_revenue_minor)}, доступно ${money(available)}`
      : "";
  const more = rest
    ? `ещё ${rest} ${plural(rest, ["причина", "причины", "причин"])}`
    : "";
  return {
    title: reasons[0].title,
    detail:
      [specific, more].filter(Boolean).join(" · ") || reasons[0].explanation,
  };
}

const columns = [
  {
    key: "risk_score",
    label: "Риск",
    hint: "Риск клиента",
  },
  { key: "id", label: "ID" },
  { key: "email", label: "Email" },
  { key: "reason", label: "Главная причина" },
  { key: "balance", label: "Баланс", num: true },
  { key: "monthly_cost", label: "В месяц", num: true },
  { key: "total_replenished", label: "Пополнено", num: true },
  {
    key: "revenue_at_risk",
    label: "Ожидаемо",
    num: true,
    hint: "Ожидаемая потеря, ниже максимум",
  },
];

// Ожидаемая потеря крупно, под ней максимум по тем же услугам. Нет оценки или нет риска впереди — прочерк.
function ExpectedLoss({ customer }) {
  if (customer.risk_score == null)
    return (
      <span className="muted" title="Нет оценки риска, сумма не показывается">
        —
      </span>
    );
  if (!customer.revenue_at_risk_minor)
    return (
      <span className="muted" title="В ближайших продлениях нет риска">
        —
      </span>
    );
  return (
    <div className="money-pair">
      <b>{money(customer.revenue_at_risk_minor)}</b>
      <small>из {money(customer.near_term_loss_minor)}</small>
    </div>
  );
}

export function CustomerTable({ customers, sortBy, order, onSort, onSelect }) {
  return (
    <div className="table-scroll">
      <table className="ctable">
        <thead>
          <tr>
            {columns.map((column) => {
              const active = sortBy === column.key;
              return (
                <th
                  key={column.key}
                  className={column.num ? "num" : undefined}
                  aria-sort={
                    active
                      ? order === "asc"
                        ? "ascending"
                        : "descending"
                      : undefined
                  }
                >
                  {column.key === "reason" ? (
                    column.label
                  ) : (
                    <button
                      className={`sort${active ? " sort-active" : ""}`}
                      onClick={() => onSort(column.key)}
                      title={column.hint}
                    >
                      {column.label}
                      <Icon
                        name={
                          active
                            ? order === "asc"
                              ? "sortAsc"
                              : "sortDesc"
                            : "sortNone"
                        }
                        size={14}
                      />
                    </button>
                  )}
                </th>
              );
            })}
            <th aria-label="Открыть" />
          </tr>
        </thead>
        <tbody>
          {customers.map((customer) => {
            const reason = mainReason(customer);
            return (
              <tr
                key={customer.id}
                tabIndex="0"
                onClick={(event) => {
                  if (event.target.closest("a")) return;
                  onSelect(customer.id);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect(customer.id);
                  }
                }}
              >
                <td>
                  <RiskKey
                    level={customer.risk_level}
                    score={customer.risk_score}
                  />
                </td>
                <td className="id">
                  <a href={pageHref("customer", customer.id)} translate="no">
                    {customer.id}
                  </a>
                </td>
                <td className="email">{customer.email}</td>
                <td>
                  <div className="reason-cell">
                    <span>{reason.title}</span>
                    {reason.detail && <small>{reason.detail}</small>}
                  </div>
                </td>
                <td className="num money">{money(customer.balance_minor)}</td>
                <td className="num money">
                  {money(customer.monthly_cost_minor)}
                </td>
                <td className="num money">
                  {money(customer.total_replenished_minor)}
                </td>
                <td className="num money">
                  <ExpectedLoss customer={customer} />
                </td>
                <td className="chev">
                  <Icon name="right" size={18} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function SkeletonRows({ rows = 5 }) {
  return (
    <div aria-busy="true" aria-label="Загружаем">
      {Array.from({ length: rows }, (_, index) => (
        <div
          key={index}
          className="factor"
          style={{ padding: "18px 20px", opacity: 1 - index * 0.15 }}
        >
          <span className="skeleton" style={{ width: 40, height: 40 }} />
          <span className="skeleton" style={{ width: 80 }} />
          <span className="skeleton" style={{ width: 180 }} />
          <span className="skeleton" style={{ flex: 1, maxWidth: 360 }} />
          <span
            className="skeleton"
            style={{ width: 90, marginLeft: "auto" }}
          />
        </div>
      ))}
    </div>
  );
}

export function Empty({ image, title, children, action }) {
  return (
    <div className="empty">
      {image && (
        <img
          src={image.src}
          width={image.width}
          height={image.height}
          alt=""
          loading="lazy"
        />
      )}
      <h3 className="h2">{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function Toast({ message, kind = "success", onClose }) {
  if (!message) return null;
  return (
    <div className="toast" role={kind === "error" ? "alert" : "status"}>
      <span className={`dot${kind === "error" ? " dot-high" : ""}`} />
      <div>
        <b>{message}</b>
      </div>
      <button
        className="icon-button"
        onClick={onClose}
        aria-label="Закрыть уведомление"
      >
        <Icon name="close" size={16} />
      </button>
    </div>
  );
}
