import { Fragment, useEffect, useState } from "react";
import { api } from "./api.js";
import { AezaIcon, reasonIcon } from "./AezaIcon.jsx";
import { RiskBadge, RiskKey } from "./Icons.jsx";
import { CardHead, Empty, SkeletonRows } from "./Shared.jsx";
import {
  dateLabel,
  money,
  paymentTermText,
  plural,
  serviceStatusText,
} from "./format.js";
import mascotSurprised from "./assets/mascot-surprised.webp";

const points = (value) => (Math.round(value * 10) / 10).toString().replace(".", ",");

// Waiting past the grace period: the service should already be deleted, so no money is counted for it.
const isStaleWait = (service) =>
  service.status === "prolong_wait" &&
  service.grace_remaining_days === 0 &&
  service.risk_score > 0;

// Explanation under a service: its own reasons with numbers, the money at stake and the next step.
function ServiceDetail({ service }) {
  const reasons = service.reasons || [];
  const index = service.risk_score == null ? null : points(service.risk_score);
  const staleWait = isStaleWait(service);
  return (
    <div className="service-detail">
      {reasons.length > 0 && (
        <ul className="service-reasons">
          {reasons.map((reason) => (
            <li key={reason.code}>
              <b>{reason.title}</b>
              {reason.points > 0 && <span className="factor-pts"> +{points(reason.points)}</span>}
              <span> — {reason.explanation}</span>
            </li>
          ))}
        </ul>
      )}
      {service.revenue_at_risk_minor > 0 && (
        <p className="service-loss">
          Ожидаемо: {money(service.revenue_at_risk_minor)} = цена{" "}
          {money(service.price_minor)} × индекс {index} / 100. Максимум —{" "}
          {money(service.near_term_loss_minor)}, полная цена продления
        </p>
      )}
      {service.potential_loss_minor > 0 && (
        <p className="service-loss">
          Из ожидаемого не хватает средств: {money(service.potential_loss_minor)}{" "}
          = недостаток {money(service.uncovered_revenue_minor)} × индекс {index}{" "}
          / 100
        </p>
      )}
      {staleWait && (
        <p className="service-loss">
          Деньги не считаем: ожидание оплаты дольше 5 дней, услуга уже должна
          быть удалена. Проверьте данные в источнике.
        </p>
      )}
      <p className="service-action">
        <b>Действие:</b> {service.recommended_action?.text || "—"}
      </p>
    </div>
  );
}

const transactionStatus = {
  performed: "Выполнена",
  not_performed: "Не выполнена",
};

export function CustomerPage({ id, version, onToast }) {
  const [customer, setCustomer] = useState(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setError("");
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
  }, [id, version, attempt]);

  if (error && !customer)
    return (
      <section className="card">
        <Empty
          image={{ src: mascotSurprised, width: 300, height: 451 }}
          title="Не удалось загрузить клиента"
          action={
            <button
              className="button button-primary"
              onClick={() => setAttempt((value) => value + 1)}
            >
              Повторить
            </button>
          }
        >
          {error}
        </Empty>
      </section>
    );

  if (!customer)
    return (
      <section className="table-card">
        <SkeletonRows rows={4} />
      </section>
    );

  const calc = customer.calculation || {};
  const horizon = calc.horizon_days || 30;
  const reasons = (customer.reasons || []).filter(
    (reason) => reason.code !== "no_active_signals",
  );
  const maxPoints = Math.max(1, ...reasons.map((reason) => reason.points));
  const scored = customer.risk_score != null;
  // Services that carry some risk: the account index is built from exactly these.
  const indexed = customer.services.filter((service) => service.risk_score > 0);
  const indexedSum = indexed.reduce((sum, service) => sum + service.risk_score, 0);
  const staleWaits = customer.services.filter(isStaleWait).length;
  const scorePercent =
    calc.risk_score_percent ?? calc.risk_score_index ?? customer.risk_score;
  const showServiceRisk = customer.services.some(
    (service) => service.risk_score != null,
  );

  async function copyEmail() {
    try {
      await navigator.clipboard.writeText(customer.email);
      onToast({ kind: "success", message: "Email скопирован" });
    } catch {
      onToast({ kind: "error", message: "Не удалось скопировать email" });
    }
  }

  return (
    <>
      <div className="client-head">
        <RiskKey
          level={customer.risk_level}
          score={customer.risk_score}
          large
        />
        <div className="client-head-text">
          <div className="client-title">
            <h1 className="h1">{customer.email}</h1>
            <RiskBadge
              level={customer.risk_level}
              label={
                customer.risk_level
                  ? `${customer.risk_label} риск`
                  : customer.risk_label
              }
            />
          </div>
          <p className="muted">
            ID {customer.id} · {customer.service_count}{" "}
            {plural(customer.service_count, ["услуга", "услуги", "услуг"])}
          </p>
        </div>
        <div className="page-head-actions">
          <button className="button button-secondary" onClick={copyEmail}>
            Скопировать email
          </button>
          <a
            className="button button-primary"
            href={`mailto:${customer.email}`}
          >
            Написать клиенту
          </a>
        </div>
      </div>

      <section className="strip" aria-label="Деньги клиента">
        <div>
          <span>Баланс</span>
          <b className="number">{money(customer.balance_minor)}</b>
          <small>balance · основной</small>
        </div>
        <div>
          <span>Бонусы</span>
          <b className="number">{money(customer.bonus_balance_minor)}</b>
          <small>
            {customer.bonus_spend_enabled
              ? "bonusBalance · можно тратить"
              : "bonusBalance · тратить нельзя"}
          </small>
        </div>
        <div>
          <span>Реферальный</span>
          <b className="number">{money(customer.withdraw_balance_minor)}</b>
          <small>withdrawBalance</small>
        </div>
        <div>
          <span>Пополнено всего</span>
          <b className="number">{money(customer.total_replenished_minor)}</b>
          <small>totalReplenished</small>
        </div>
        <div>
          <span>Продления за {horizon} дней</span>
          <b className="number">{money(customer.due_revenue_minor)}</b>
          <small>стоимость услуг в горизонте</small>
        </div>
      </section>

      <div className="row-split">
        <section className="card">
          <CardHead
            icon="info"
            title={
              customer.risk_score == null
                ? "Почему нет оценки"
                : "Почему такой риск"
            }
            description={
              customer.risk_score == null
                ? "Мало данных: нет активных услуг или даты окончания. Когда появятся, оценка посчитается сама."
                : "Индекс аккаунта — «хотя бы одна услуга не продлится»: 100 × (1 − Π(1 − индекс услуги / 100)), не выше 100. У аккаунта с одной услугой он равен её индексу. Веса — в «Модели риска»."
            }
          />
          {customer.risk_score == null ? (
            <p className="muted">
              {customer.reasons?.[0]?.explanation ||
                "Недостаточно данных для оценки: нет активных услуг или дат окончания."}
            </p>
          ) : reasons.length ? (
            <div>
              {reasons.map((reason) => (
                <div className="factor" key={reason.code}>
                  <AezaIcon
                    name={reasonIcon[reason.code] || "info"}
                    size={36}
                  />
                  <div className="factor-text">
                    <b>{reason.title}</b>
                    <small>{reason.explanation}</small>
                  </div>
                  <span className="factor-bar" aria-hidden="true">
                    <i
                      style={{ width: `${(reason.points / maxPoints) * 100}%` }}
                    />
                  </span>
                  <span className="factor-pts">
                    +{points(reason.points)}
                  </span>
                </div>
              ))}
              <div className="total-row">
                <b>Индекс аккаунта</b>
                <span className="muted">
                  {reasons.map((reason) => points(reason.points)).join(" + ")}{" "}
                  = {points(customer.risk_score)}
                </span>
              </div>
              {indexed.length > 1 && (
                <p className="small muted">
                  Индексы услуг: {indexed.slice(0, 6).map((service) => points(service.risk_score)).join(", ")}
                  {indexed.length > 6 && "…"}. Просто сложить их нельзя: вышло бы{" "}
                  {points(indexedSum)}. Индекс аккаунта отвечает на вопрос
                  «хотя бы одна услуга не продлится», поэтому он ниже суммы и не
                  выше 100.
                </p>
              )}
            </div>
          ) : (
            <p className="muted">Признаков риска нет, клиент в порядке.</p>
          )}
        </section>

        <section className="card">
          <CardHead
            icon="euro"
            title="Сколько можем потерять"
            description="Ожидаемая потеря и максимум по услугам, у которых срок в пределах 7 дней или идёт ожидание оплаты"
          />
          <div>
            <div className="calc-line">
              <i />
              <span>Максимум: цена услуг с признаками риска</span>
              <b>{scored ? money(customer.near_term_loss_minor) : "—"}</b>
            </div>
            <div className="calc-line">
              <i>×</i>
              <span>Индекс каждой услуги / 100</span>
              <b>{scored ? "см. услуги" : "нет оценки"}</b>
            </div>
          </div>
          <div className="calc-result">
            <span className="small muted">Ожидаемо</span>
            <b className="number">
              {scored ? money(customer.revenue_at_risk_minor) : "—"}
            </b>
            {!scored && (
              <span className="small muted">
                Без оценки риска сумму не считаем
              </span>
            )}
            {scored && !customer.near_term_loss_minor && (
              <span className="small muted">
                {staleWaits
                  ? "Деньги не считаем: услуги ждут оплаты дольше 5 дней, проверьте данные в источнике"
                  : "Впереди нет услуг с признаками риска"}
              </span>
            )}
          </div>
          <div className="calc-line">
            <i />
            <span>Из ожидаемого: не хватает средств</span>
            <b>{scored ? money(customer.potential_loss_minor) : "—"}</b>
          </div>
          <p className="small muted">
            {calc.uncovered_revenue_minor > 0
              ? `Продления за ${horizon} дн. ${money(calc.due_revenue_minor)} против доступного баланса ${money(calc.available_balance_minor)}: не покрыто ${money(calc.uncovered_revenue_minor)}. `
              : `Баланс покрывает продления за ${horizon} дн.: ${money(calc.due_revenue_minor)} против ${money(calc.available_balance_minor)}. `}
            Доступный баланс: основной плюс бонусный, если bonusState разрешает
            его тратить. Реферальный не учитываем.
          </p>
        </section>
      </div>

      <section className="card flush">
        <CardHead
          icon="clock"
          title={`Услуги · ${customer.services.length}`}
          description="Статусы и сроки из текущего снимка"
        />
        {customer.services.length ? (
          <div className="plain-scroll">
            <table className="plain-table">
              <thead>
                <tr>
                  <th>Услуга</th>
                  <th>Оплата</th>
                  <th className="num">Цена</th>
                  <th>Статус</th>
                  <th>Истекает</th>
                  <th>Автопродление</th>
                  {showServiceRisk && <th className="num">Риск услуги</th>}
                </tr>
              </thead>
              <tbody>
                {customer.services.map((service) => (
                  <Fragment key={service.id}>
                  <tr>
                    <td>
                      <b>{service.name}</b>
                    </td>
                    <td>
                      {paymentTermText[service.payment_term] ||
                        service.payment_term ||
                        "—"}
                    </td>
                    <td className="num">{money(service.price_minor)}</td>
                    <td>
                      <span className={`status status-${service.status}`}>
                        <span className="dot" />
                        {serviceStatusText[service.status] || service.status}
                      </span>
                    </td>
                    <td>
                      {service.expires_at ? dateLabel(service.expires_at) : "—"}
                    </td>
                    <td>{service.auto_prolong ? "Включено" : "Выключено"}</td>
                    {showServiceRisk && (
                      <td className="num">
                        {service.risk_score == null
                          ? "—"
                          : points(service.risk_score)}
                      </td>
                    )}
                  </tr>
                  <tr className="service-detail-row">
                    <td colSpan={showServiceRisk ? 7 : 6}>
                      <ServiceDetail service={service} />
                    </td>
                  </tr>
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="Услуг нет">В снимке нет услуг этого клиента.</Empty>
        )}
      </section>

      <section className="card flush">
        <CardHead
          icon="info"
          title="Качество данных"
          description="Что мешает точной оценке и что проверить в источнике"
        />
        {customer.data_quality?.length ? (
          <ul className="data-issues">
            {customer.data_quality.map((issue, index) => (
              <li key={`${issue.code}-${issue.service_id}-${index}`}>
                <b>{issue.service_id ? `Услуга ${issue.service_id}` : "Клиент"}</b>
                <span> — {issue.message}</span>
              </li>
            ))}
          </ul>
        ) : (
          <Empty title="Замечаний нет">Данные по клиенту заполнены полностью.</Empty>
        )}
      </section>

      <section className="card flush">
        <CardHead
          icon="wallet"
          title={`Транзакции · ${customer.transactions.length}`}
          description="Заказы и продления из снимка"
        />
        {customer.transactions.length ? (
          <div className="plain-scroll">
            <table className="plain-table">
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Тип</th>
                  <th className="num">Сумма</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {customer.transactions.map((transaction) => (
                  <tr key={transaction.id}>
                    <td>{dateLabel(transaction.created_at)}</td>
                    <td>
                      {transaction.type === "prolong" ? "Продление" : "Заказ"}
                    </td>
                    <td className="num">{money(transaction.amount_minor)}</td>
                    <td>
                      <span
                        className={`status status-${transaction.status === "performed" ? "active" : "blocked"}`}
                      >
                        <span className="dot" />
                        {transactionStatus[transaction.status] ||
                          transaction.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="Транзакций нет">В снимке нет платежей клиента.</Empty>
        )}
      </section>
    </>
  );
}
