import { Fragment, useEffect, useState } from "react";
import { api } from "./api.js";
import { AezaIcon, reasonIcon } from "./AezaIcon.jsx";
import { RiskBadge, RiskKey } from "./Icons.jsx";
import { CardHead, Empty, SkeletonRows } from "./Shared.jsx";
import {
  dateLabel,
  money,
  moneyToMinor,
  paymentTermText,
  plural,
  serviceStatusText,
} from "./format.js";
import mascotSurprised from "./assets/mascot-surprised.webp";

const points = (value) => (Math.round(value * 10) / 10).toString().replace(".", ",");

const moneyInput = (minor) => ((minor || 0) / 100).toFixed(2);
const dateTimeInput = (value) => {
  if (!value) return "";
  const date = new Date(value);
  const pad = (part) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

function CustomerEditor({ customer, onClose, onSaved, onToast }) {
  const [draft, setDraft] = useState({
    email: customer.email,
    balance: moneyInput(customer.balance_minor),
    bonus: moneyInput(customer.bonus_balance_minor),
    withdraw: moneyInput(customer.withdraw_balance_minor),
    replenished: moneyInput(customer.total_replenished_minor),
    bonusSpendEnabled: customer.bonus_spend_enabled,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save(event) {
    event.preventDefault();
    setError("");
    const fields = ["balance", "bonus", "withdraw", "replenished"];
    const values = Object.fromEntries(fields.map((field) => [field, moneyToMinor(draft[field])]));
    if (Object.values(values).some((value) => value == null) || !draft.email.trim().includes("@")) {
      setError("Проверьте email и суммы: используйте евро, например 125,50.");
      return;
    }
    setSaving(true);
    try {
      const updated = await api.updateCustomer(customer.id, {
        email: draft.email.trim(),
        balance_minor: values.balance,
        bonus_balance_minor: values.bonus,
        withdraw_balance_minor: values.withdraw,
        total_replenished_minor: values.replenished,
        bonus_spend_enabled: draft.bonusSpendEnabled,
      });
      onSaved(updated);
      onToast({ kind: "success", message: "Данные клиента сохранены, расчёт обновлён." });
      onClose();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="card edit-panel" aria-label="Редактирование клиента">
      <CardHead
        icon="info"
        title="Исправить данные клиента"
      />
      <form className="edit-form" onSubmit={save}>
        <div className="fields">
          <label className="field"><span>Email</span><input value={draft.email} onChange={(event) => setDraft({ ...draft, email: event.target.value })} /></label>
          <label className="field"><span>Основной баланс, €</span><input inputMode="decimal" value={draft.balance} onChange={(event) => setDraft({ ...draft, balance: event.target.value })} /></label>
          <label className="field"><span>Бонусы, €</span><input inputMode="decimal" value={draft.bonus} onChange={(event) => setDraft({ ...draft, bonus: event.target.value })} /></label>
        </div>
        <div className="fields">
          <label className="field"><span>Реферальный резерв, €</span><input inputMode="decimal" value={draft.withdraw} onChange={(event) => setDraft({ ...draft, withdraw: event.target.value })} /></label>
          <label className="field"><span>Пополнено всего, €</span><input inputMode="decimal" value={draft.replenished} onChange={(event) => setDraft({ ...draft, replenished: event.target.value })} /></label>
          <label className="edit-check"><input type="checkbox" checked={draft.bonusSpendEnabled} onChange={(event) => setDraft({ ...draft, bonusSpendEnabled: event.target.checked })} /> Бонусы можно тратить</label>
        </div>
        {error && <span className="inline-error" role="alert">{error}</span>}
        <div className="edit-actions">
          <button type="button" className="button button-secondary" onClick={onClose}>Отмена</button>
          <button type="submit" className="button button-primary" disabled={saving}>{saving ? "Сохраняем…" : "Сохранить данные"}</button>
        </div>
      </form>
    </section>
  );
}

function ServiceEditor({ customerId, service, onClose, onSaved, onToast }) {
  const [draft, setDraft] = useState({
    name: service.name,
    price: moneyInput(service.price_minor),
    autoProlong: service.auto_prolong,
    paymentTerm: service.payment_term || "month",
    status: service.status,
    expiresAt: dateTimeInput(service.expires_at),
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save(event) {
    event.preventDefault();
    const price = moneyToMinor(draft.price);
    if (!draft.name.trim() || price == null) {
      setError("Укажите название услуги и корректную цену.");
      return;
    }
    setError("");
    setSaving(true);
    try {
      const updated = await api.updateService(customerId, service.id, {
        name: draft.name.trim(),
        price_minor: price,
        auto_prolong: draft.autoProlong,
        payment_term: draft.paymentTerm || null,
        status: draft.status,
        expires_at: draft.expiresAt ? new Date(draft.expiresAt).toISOString() : null,
      });
      onSaved(updated);
      onToast({ kind: "success", message: "Данные услуги сохранены, расчёт обновлён." });
      onClose();
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="service-editor">
      <form className="edit-form" onSubmit={save}>
        <div className="fields">
          <label className="field"><span>Название</span><input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
          <label className="field"><span>Цена, €</span><input inputMode="decimal" value={draft.price} onChange={(event) => setDraft({ ...draft, price: event.target.value })} /></label>
          <label className="field"><span>Срок оплаты</span><select value={draft.paymentTerm} onChange={(event) => setDraft({ ...draft, paymentTerm: event.target.value })}><option value="hour">Почасово</option><option value="week">Еженедельно</option><option value="month">Ежемесячно</option><option value="quarter_year">Раз в квартал</option><option value="half_year">Раз в полгода</option><option value="year">Раз в год</option></select></label>
        </div>
        <div className="fields">
          <label className="field"><span>Статус</span><select value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}><option value="active">Активна</option><option value="suspended">Выключена</option><option value="prolong_wait">Ждёт оплаты</option><option value="deleted">Удалена</option><option value="blocked">Заблокирована</option></select></label>
          <label className="field"><span>Дата окончания</span><input type="datetime-local" value={draft.expiresAt} onChange={(event) => setDraft({ ...draft, expiresAt: event.target.value })} /></label>
          <label className="edit-check"><input type="checkbox" checked={draft.autoProlong} onChange={(event) => setDraft({ ...draft, autoProlong: event.target.checked })} /> Автопродление включено</label>
        </div>
        {error && <span className="inline-error" role="alert">{error}</span>}
        <div className="edit-actions">
          <button type="button" className="button button-secondary" onClick={onClose}>Отмена</button>
          <button type="submit" className="button button-primary" disabled={saving}>{saving ? "Сохраняем…" : "Сохранить услугу"}</button>
        </div>
      </form>
    </div>
  );
}

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
              <span>: {reason.explanation}</span>
            </li>
          ))}
        </ul>
      )}
      {service.revenue_at_risk_minor > 0 && (
        <p className="service-loss">
          Под риском: {money(service.revenue_at_risk_minor)} из {money(service.near_term_loss_minor)} полной цены продления
        </p>
      )}
      {service.potential_loss_minor > 0 && (
        <p className="service-loss">
          Не хватает на балансе: {money(service.potential_loss_minor)}
        </p>
      )}
      {staleWait && (
        <p className="service-loss">
          Ожидание оплаты длится больше 5 дней. Проверьте статус услуги в источнике.
        </p>
      )}
      <p className="service-action">
        <b>Действие:</b> {service.recommended_action?.text || "—"}
      </p>
    </div>
  );
}

// What the marketer does next: the situation, the facts behind it, steps by time and a ready letter.
function ActionPlanCard({ plan, onCopy }) {
  const signals = plan.signals || [];
  const steps = plan.steps || [];
  const tags = [plan.urgency_label, plan.segment?.title, plan.channel].filter(Boolean);
  const details = [
    `Приоритет ${points(plan.priority)} из 100`,
    plan.expected_revenue_at_risk_minor > 0 &&
      `под угрозой ${money(plan.expected_revenue_at_risk_minor)}`,
  ].filter(Boolean);
  return (
    <section className="card action-plan-card" aria-label="План действия">
      <CardHead
        icon="info"
        title={`Что делать: ${plan.title}`}
        description={details.join(" · ")}
      />
      {tags.length > 0 && (
        <div className="plan-tags">
          {tags.map((tag) => (
            <span
              key={tag}
              className={`chip${tag === "Срочно" ? " plan-urgent" : ""}`}
            >
              {tag}
            </span>
          ))}
        </div>
      )}
      <p className="plan-diagnosis">{plan.diagnosis}</p>
      <div className="plan-grid">
        {signals.length > 0 && (
          <div>
            <h3 className="plan-label">На чём основано</h3>
            <ul className="plan-facts">
              {signals.map((signal) => (
                <li key={signal}>{signal}</li>
              ))}
            </ul>
            {plan.segment?.reason && (
              <p className="small muted">{plan.segment.reason}</p>
            )}
          </div>
        )}
        <div>
          <h3 className="plan-label">Шаги</h3>
          <ol className="plan-steps">
            {steps.length ? (
              steps.map((step) => (
                <li key={step.when + step.text}>
                  <b>{step.when}</b>
                  <span>{step.text}</span>
                </li>
              ))
            ) : (
              <li>
                <b>Сейчас</b>
                <span>{plan.next_best_action}</span>
              </li>
            )}
          </ol>
          {plan.offer && (
            <div className="plan-offer">
              <b>Предложение</b>
              <span>{plan.offer}</span>
            </div>
          )}
        </div>
      </div>
      {plan.message_template && (
        <div className="action-message">
          <div className="action-message-text">
            {plan.message_subject && <b>{plan.message_subject}</b>}
            <span>{plan.message_template}</span>
          </div>
          <button className="button button-secondary" onClick={onCopy}>
            Скопировать письмо
          </button>
        </div>
      )}
    </section>
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
  const [editingCustomer, setEditingCustomer] = useState(false);
  const [editingServiceId, setEditingServiceId] = useState(null);

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

  async function copyActionMessage() {
    const plan = customer.action_plan;
    if (!plan?.message_template) return;
    const message = plan.message_subject
      ? `Тема: ${plan.message_subject}\n\n${plan.message_template}`
      : plan.message_template;
    try {
      await navigator.clipboard.writeText(message);
      onToast({ kind: "success", message: "Письмо скопировано" });
    } catch {
      onToast({ kind: "error", message: "Не удалось скопировать письмо" });
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
            {customer.loyalty_score != null && (
              <span title="Обратная шкала риска: 100 минус риск клиента">
                {" "}· лояльность {100 - Math.round(customer.risk_score)} из 100
              </span>
            )}
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
          <button className="button button-secondary" onClick={() => setEditingCustomer((value) => !value)}>
            {editingCustomer ? "Закрыть редактор" : "Изменить данные"}
          </button>
        </div>
      </div>

      {editingCustomer && (
        <CustomerEditor
          customer={customer}
          onClose={() => setEditingCustomer(false)}
          onSaved={setCustomer}
          onToast={onToast}
        />
      )}

      <section className="strip" aria-label="Деньги клиента">
        <div>
          <span>Баланс</span>
          <b className="number">{money(customer.balance_minor)}</b>
        </div>
        <div>
          <span>Бонусы</span>
          <b className="number">{money(customer.bonus_balance_minor)}</b>
          <small>
            {customer.bonus_spend_enabled
              ? "можно тратить"
              : "тратить нельзя"}
          </small>
        </div>
        <div>
          <span>Реферальный</span>
          <b className="number">{money(customer.withdraw_balance_minor)}</b>
        </div>
        <div>
          <span>Пополнено всего</span>
          <b className="number">{money(customer.total_replenished_minor)}</b>
        </div>
        <div>
          <span>Продления за {horizon} дней</span>
          <b className="number">{money(customer.due_revenue_minor)}</b>
        </div>
      </section>

      <section className="card ltv-card" aria-label="LTV клиента">
        <CardHead
          icon="wallet"
          title="LTV клиента"
        />
        <div className="ltv-grid">
          <div><span>Текущий MRR</span><b>{money(customer.ltv?.current_mrr_minor)}</b></div>
          <div><span>Ожидаемый срок</span><b>{customer.ltv?.expected_lifetime_months || 0} мес.</b></div>
          <div><span>LTV</span><b>{money(customer.ltv?.gross_ltv_minor)}</b></div>
          <div><span>Под риском</span><b>{money(customer.ltv?.at_risk_ltv_minor)}</b></div>
        </div>
        <p className="small muted">
          Уверенность {Math.round((customer.ltv?.confidence || 0) * 100)}% · успешных платежей: {customer.ltv?.payment_success_rate == null ? "нет истории" : `${Math.round(customer.ltv.payment_success_rate * 100)}%`}.
        </p>
      </section>

      {customer.action_plan && (
        <ActionPlanCard plan={customer.action_plan} onCopy={copyActionMessage} />
      )}

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
                ? "Нет активных услуг или даты окончания"
                : undefined
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
                <b>Риск клиента</b>
                <span className="muted">
                  {reasons.map((reason) => points(reason.points)).join(" + ")}{" "}
                  = {points(customer.risk_score)}
                </span>
              </div>
              {customer.unscored_services_count > 0 && customer.data_coverage >= 0.7 && (
                <p className="small muted">
                  Оценка построена по {Math.round(customer.data_coverage * 100)}% услуг. Ещё {customer.unscored_services_count} усл. требуют проверки данных.
                </p>
              )}
              {indexed.length > 1 && (
                <p className="small muted">
                  Оценки по услугам: {indexed.slice(0, 6).map((service) => points(service.risk_score)).join(", ")}
                  {indexed.length > 6 && "…"}
                </p>
              )}
              {customer.service_count > 3 && customer.risky_service_count > 0 && (
                <p className="small muted">
                  В портфеле {customer.service_count} услуг, риск есть у {customer.risky_service_count}
                  ({Math.round((customer.service_risk_share || 0) * 100)}%). Поправка за размер портфеля:{" "}
                  {points(customer.service_count_adjustment ?? 1)}×.
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
          />
          <div>
            <div className="calc-line">
              <i />
              <span>Максимум по услугам с риском</span>
              <b>{scored ? money(customer.near_term_loss_minor) : "—"}</b>
            </div>
            <div className="calc-line">
              <i>×</i>
              <span>С учётом риска каждой услуги</span>
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
                Нет оценки
              </span>
            )}
            {scored && !customer.near_term_loss_minor && (
              <span className="small muted">
                {staleWaits
                  ? "Ожидание оплаты длится дольше 5 дней. Проверьте статус услуги в источнике."
                  : "В ближайших продлениях нет риска"}
              </span>
            )}
          </div>
          <div className="calc-line">
            <i />
            <span>Из неё не хватает на балансе</span>
            <b>{scored ? money(customer.potential_loss_minor) : "—"}</b>
          </div>
          <p className="small muted">
            {calc.uncovered_revenue_minor > 0
              ? `Продления за ${horizon} дн. ${money(calc.due_revenue_minor)} против доступного баланса ${money(calc.available_balance_minor)}: не покрыто ${money(calc.uncovered_revenue_minor)}. `
              : `Баланс покрывает продления за ${horizon} дн.: ${money(calc.due_revenue_minor)} против ${money(calc.available_balance_minor)}. `}
          </p>
        </section>
      </div>

      <section className="card flush">
        <CardHead
          icon="clock"
          title={`Услуги · ${customer.services.length}`}
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
                  <th />
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
                    <td>
                      <button className="link" onClick={() => setEditingServiceId(editingServiceId === service.id ? null : service.id)}>
                        {editingServiceId === service.id ? "Закрыть" : "Изменить"}
                      </button>
                    </td>
                  </tr>
                  <tr className="service-detail-row">
                    <td colSpan={showServiceRisk ? 8 : 7}>
                      {editingServiceId === service.id ? (
                        <ServiceEditor
                          customerId={customer.id}
                          service={service}
                          onClose={() => setEditingServiceId(null)}
                          onSaved={setCustomer}
                          onToast={onToast}
                        />
                      ) : (
                        <ServiceDetail service={service} />
                      )}
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
