import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Icon, RiskBadge } from "./Icons.jsx";
import { dateLabel, money } from "./format.js";

export function CustomerDrawer({ id, onClose }) {
  const [customer, setCustomer] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setCustomer(null);
    api
      .customer(id)
      .then((result) => {
        if (active) setCustomer(result);
      })
      .catch((requestError) => {
        if (active) setError(requestError.message);
      });
    return () => {
      active = false;
    };
  }, [id]);
  useEffect(() => {
    const closeOnEscape = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  const serviceStatus = {
    active: "Активна",
    suspended: "Приостановлена",
    prolong_wait: "Ждёт оплаты",
    deleted: "Удалена",
    blocked: "Заблокирована",
  };
  const transactionStatus = {
    performed: "Успешно",
    not_performed: "Не прошла",
  };
  return (
    <div
      className="drawer-layer"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside
        className="customer-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Карточка клиента"
      >
        <div className="drawer-top">
          <span className="section-index">КАРТОЧКА КЛИЕНТА</span>
          <button
            className="icon-button drawer-close"
            onClick={onClose}
            aria-label="Закрыть"
          >
            <Icon name="close" />
          </button>
        </div>
        {customer ? (
          <>
            <div className="drawer-identity">
              <span className="drawer-avatar">
                {customer.email.slice(0, 1).toUpperCase()}
              </span>
              <div>
                <h2>{customer.email}</h2>
                <span>ID клиента #{customer.id}</span>
              </div>
            </div>
            <div className="drawer-score">
              <div>
                <span>Оценка непродления</span>
                <b>
                  {customer.risk_score == null
                    ? "—"
                    : `${customer.risk_score} / 100`}
                </b>
              </div>
              <RiskBadge
                level={customer.risk_level}
                label={customer.risk_label}
              />
            </div>
            <div className="drawer-metrics">
              <div>
                <span>Баланс</span>
                <b>{money(customer.balance_minor)}</b>
              </div>
              <div>
                <span>Сумма риска</span>
                <b className="drawer-loss">
                  {money(customer.potential_loss_minor)}
                </b>
              </div>
              <div>
                <span>
                  Продления за {customer.calculation.horizon_days} дней
                </span>
                <b>{money(customer.due_revenue_minor)}</b>
              </div>
              <div>
                <span>Услуг</span>
                <b>{customer.service_count}</b>
              </div>
            </div>
            <section className="drawer-section">
              <div className="drawer-section-title">
                <h3>Почему такой риск</h3>
                <span>
                  {customer.reasons.length}{" "}
                  {customer.reasons.length === 1 ? "сигнал" : "сигнала"}
                </span>
              </div>
              {customer.reasons.map((reason) => (
                <div className="signal-card" key={reason.code}>
                  <span className={`signal-icon signal-${reason.code}`}>
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
                  <div>
                    <b>
                      {reason.title}
                      {reason.points > 0 && <i>+{reason.points}</i>}
                    </b>
                    <p>{reason.explanation}</p>
                  </div>
                </div>
              ))}
            </section>
            <section className="drawer-section">
              <div className="drawer-section-title">
                <h3>Услуги</h3>
                <span>{customer.services.length}</span>
              </div>
              {customer.services.length ? (
                customer.services.map((service) => (
                  <div className="service-card" key={service.id}>
                    <span className="service-icon">
                      <Icon name="server" size={17} />
                    </span>
                    <div className="service-info">
                      <b>{service.name}</b>
                      <small>
                        {service.auto_prolong
                          ? "Автопродление включено"
                          : "Автопродление выключено"}{" "}
                        · до {dateLabel(service.expires_at)}
                      </small>
                    </div>
                    <div className="service-amount">
                      <b>{money(service.price_minor)}</b>
                      <small>
                        {serviceStatus[service.status] || service.status}
                      </small>
                    </div>
                  </div>
                ))
              ) : (
                <div className="drawer-empty">В снимке нет услуг клиента.</div>
              )}
            </section>
            <section className="drawer-section">
              <div className="drawer-section-title">
                <h3>Последние транзакции</h3>
                <span>{customer.transactions.length}</span>
              </div>
              {customer.transactions.length ? (
                customer.transactions.slice(0, 5).map((transaction) => (
                  <div className="transaction-row" key={transaction.id}>
                    <span
                      className={`transaction-state${transaction.status === "performed" ? " transaction-ok" : " transaction-failed"}`}
                    >
                      <Icon
                        name={
                          transaction.status === "performed" ? "check" : "close"
                        }
                        size={14}
                      />
                    </span>
                    <span>
                      <b>
                        {transaction.type === "prolong"
                          ? "Продление услуги"
                          : "Платёж"}
                      </b>
                      <small>{dateLabel(transaction.created_at)}</small>
                    </span>
                    <b className="transaction-amount">
                      {money(transaction.amount_minor)}
                    </b>
                    <span
                      className={`transaction-label${transaction.status === "performed" ? " label-ok" : " label-failed"}`}
                    >
                      {transactionStatus[transaction.status]}
                    </span>
                  </div>
                ))
              ) : (
                <div className="drawer-empty">Транзакций в снимке нет.</div>
              )}
            </section>
            <section className="calculation-detail">
              <div className="calculation-detail-title">
                <Icon name="info" size={16} />
                <b>Как рассчитана сумма</b>
              </div>
              <div>
                <span>Нехватка на продления</span>
                <b>{money(customer.uncovered_revenue_minor)}</b>
              </div>
              <div>
                <span>Оценка риска</span>
                <b>
                  {customer.risk_score == null
                    ? "Нет оценки"
                    : `${customer.risk_score}%`}
                </b>
              </div>
              <div className="calculation-result">
                <span>Потенциальная потеря</span>
                <b>{money(customer.potential_loss_minor)}</b>
              </div>
            </section>
            <div className="drawer-bottom-note">
              Расчёт сделан по текущему снимку данных и горизонту{" "}
              {customer.calculation.horizon_days} дней.
            </div>
          </>
        ) : error ? (
          <div className="drawer-error">{error}</div>
        ) : (
          <div className="drawer-loading">
            <span className="spinner" />
            Загружаем карточку…
          </div>
        )}
      </aside>
    </div>
  );
}
