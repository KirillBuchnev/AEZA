import { Icon, RiskBadge } from "./Icons.jsx";
import { money, riskClass } from "./format.js";

export function PageHeader({ title, description, eyebrow, action, onMenu }) {
  return (
    <div className="page-header">
      <button
        className="mobile-menu-button icon-button"
        aria-label="Открыть меню"
        onClick={onMenu}
      >
        <span className="hamburger" />
      </button>
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action && <div className="page-header-action">{action}</div>}
    </div>
  );
}

export function MetricCard({ label, value, note, tone = "", icon, onClick }) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag
      className={`metric-card ${tone}${onClick ? " metric-card-clickable" : ""}`}
      onClick={onClick}
    >
      <div className="metric-top">
        <span>{label}</span>
        {icon && (
          <span className="metric-icon">
            <Icon name={icon} size={18} />
          </span>
        )}
      </div>
      <strong>{value}</strong>
      <small>{note}</small>
    </Tag>
  );
}

export function CustomerTable({
  customers,
  onSelect,
  sortBy,
  order,
  onSort,
  compact = false,
  includeAll = false,
}) {
  const headers = includeAll
    ? [
        { key: "id", label: "ID" },
        { key: "email", label: "Клиент" },
        { key: "balance", label: "Баланс" },
        { key: "total_replenished", label: "Пополнено" },
        { key: "risk_score", label: "Оценка" },
        { key: "potential_loss", label: "Сумма риска" },
      ]
    : [
        { key: "id", label: "Клиент" },
        { key: "balance", label: "Баланс" },
        { key: "risk_score", label: "Оценка" },
        { key: "potential_loss", label: "Сумма риска" },
      ];
  if (!customers.length)
    return (
      <div className="empty-state">
        <span className="empty-icon">
          <Icon name="search" size={22} />
        </span>
        <b>Ничего не найдено</b>
        <span>Измените запрос или снимите фильтр — список обновится.</span>
      </div>
    );
  return (
    <div className={`table-scroll${compact ? " table-scroll-compact" : ""}`}>
      <table
        className={`customer-table${includeAll ? " customer-table-all" : ""}`}
      >
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header.key}>
                <button
                  className={`table-sort${sortBy === header.key ? " table-sort-active" : ""}`}
                  onClick={() => onSort(header.key)}
                >
                  {header.label}
                  {sortBy === header.key && (
                    <span>{order === "desc" ? "↓" : "↑"}</span>
                  )}
                </button>
              </th>
            ))}
            <th>Статус</th>
          </tr>
        </thead>
        <tbody>
          {customers.map((customer) => (
            <tr
              key={customer.id}
              onClick={() => onSelect(customer.id)}
              tabIndex="0"
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(customer.id);
                }
              }}
            >
              {includeAll && <td className="id-cell">#{customer.id}</td>}
              <td>
                <span className="customer-email">
                  {includeAll ? (
                    customer.email
                  ) : (
                    <>
                      <span className="customer-id">#{customer.id}</span>
                      {customer.email}
                    </>
                  )}
                </span>
                <small className="customer-subline">
                  {customer.service_count}{" "}
                  {customer.service_count === 1 ? "услуга" : "услуг"}
                  {customer.reasons?.[0]?.code !== "no_active_signals"
                    ? ` · ${customer.reasons?.[0]?.title || "Без замечаний"}`
                    : ""}
                </small>
              </td>
              <td className="money-cell">
                {money(customer.balance_minor)}
                <small>на счёте</small>
              </td>
              {includeAll && (
                <td className="money-cell">
                  {money(customer.total_replenished_minor)}
                  <small>за всё время</small>
                </td>
              )}
              <td>
                {customer.risk_score == null ? (
                  <span className="score-empty">—</span>
                ) : (
                  <span
                    className={`score-value score-${riskClass(customer.risk_level)}`}
                  >
                    {customer.risk_score}
                    <small>/ 100</small>
                  </span>
                )}
              </td>
              <td className="money-cell">
                {money(customer.potential_loss_minor)}
                <small>оценка риска</small>
              </td>
              <td>
                <RiskBadge
                  level={customer.risk_level}
                  label={customer.risk_label}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Toast({ message, kind = "success", onClose }) {
  if (!message) return null;
  return (
    <div className={`toast toast-${kind}`} role="status">
      <span className="toast-icon">
        <Icon name={kind === "error" ? "info" : "check"} size={16} />
      </span>
      {message}
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
