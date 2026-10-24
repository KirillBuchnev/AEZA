import { useEffect, useState } from "react";
import { Icon } from "./Icons.jsx";
import { CardHead, PageHead } from "./Shared.jsx";
import { featureCodes, money, timeLabel } from "./format.js";

const featureHints = {
  prolong_wait: "status = prolong_wait: услуга уже ждёт оплаты после expiresAt",
  autoprolong_disabled:
    "autoprolong = false, а продление попадает в горизонт прогноза",
  insufficient_balance:
    "Доступного баланса меньше, чем стоимость продлений в горизонте",
  failed_prolong_payment:
    "В снимке есть транзакция продления со статусом not_performed",
};

const extraSettings = {
  urgency_days: { label: "Срочное продление, дней", min: 1, max: 30 },
  grace_days: { label: "Ожидание оплаты, дней", min: 1, max: 14 },
  customer_medium_risk_min: {
    label: "Средний риск клиента — от",
    min: 0,
    max: 19999,
  },
  customer_high_risk_min: {
    label: "Высокий риск клиента — от",
    min: 1,
    max: 20000,
  },
};

const ignored = new Set(["weights", "features", "recalculated", "changed_at"]);

function toPayload(draft) {
  const payload = { weights: draft.weights };
  Object.entries(draft).forEach(([key, value]) => {
    if (!ignored.has(key) && typeof value === "number") payload[key] = value;
  });
  return payload;
}

function Delta({ before, after, format = (value) => value }) {
  const diff = (after ?? 0) - (before ?? 0);
  return (
    <>
      <span className="from">{format(before)} →</span>
      <b>{format(after)}</b>
      {diff !== 0 && (
        <span className="delta">
          {diff > 0 ? "+" : "−"}
          {format(Math.abs(diff))}
        </span>
      )}
    </>
  );
}

export function ModelPage({ settings, summary, onSave, saving }) {
  const [draft, setDraft] = useState(settings);
  const [saveError, setSaveError] = useState("");
  const [lastChange, setLastChange] = useState(null);
  useEffect(() => setDraft(settings), [settings]);

  if (!draft)
    return (
      <section className="card">
        <span className="skeleton" style={{ width: 240 }} />
        <span className="skeleton" />
        <span className="skeleton" />
      </section>
    );

  const codes = featureCodes(settings);
  const changed = JSON.stringify(draft) !== JSON.stringify(settings);
  const thresholdError =
    draft.high_risk_min <= draft.medium_risk_min
      ? "Высокий порог должен быть больше среднего"
      : "";
  const extraKeys = Object.keys(extraSettings).filter(
    (key) => typeof draft[key] === "number",
  );

  const setNumber = (key, value, min, max) =>
    setDraft((current) => ({
      ...current,
      [key]: Math.max(min, Math.min(max, Number(value) || 0)),
    }));
  const setWeight = (code, value) =>
    setDraft((current) => ({
      ...current,
      weights: {
        ...current.weights,
        [code]: Math.max(0, Math.min(100, Number(value) || 0)),
      },
    }));

  async function save() {
    if (thresholdError) return;
    setSaveError("");
    const changedNames = codes
      .filter((code) => draft.weights[code] !== settings.weights[code])
      .map(
        (code) =>
          `«${settings.features?.[code] || code}» ${settings.weights[code]} → ${draft.weights[code]}`,
      );
    const before = summary;
    try {
      await onSave(toPayload(draft));
      setLastChange({
        before,
        label: changedNames.length
          ? `Изменено: ${changedNames.join(", ")}`
          : "Изменены пороги или горизонт",
      });
    } catch (error) {
      setSaveError(error.message);
    }
  }

  const medium = draft.medium_risk_min;
  const high = draft.high_risk_min;

  return (
    <>
      <PageHead
        title="Модель риска"
        description="Каждое изменение пересчитывает рейтинг и деньги без перезагрузки и сохраняется после перезапуска"
      >
        <span className="saved">
          {changed ? (
            "Есть несохранённые изменения"
          ) : (
            <>
              <Icon name="check" size={16} />
              Сохранено
              {settings.changed_at && ` · ${timeLabel(settings.changed_at)}`}
            </>
          )}
        </span>
        <button
          className="button button-secondary"
          disabled={!changed}
          onClick={() => setDraft(settings)}
        >
          Отменить изменения
        </button>
      </PageHead>

      <div className="row-split" style={{ alignItems: "start" }}>
        <section className="table-card">
          <div className="table-card-head">
            <CardHead
              title="Признаки и баллы"
              description="Risk-score клиента = сумма баллов сработавших признаков, от 0 до 100."
            />
          </div>
          {codes.map((code) => (
            <div className="coef" key={code}>
              <div className="coef-text">
                <b>{settings.features?.[code] || code}</b>
                <small>{featureHints[code] || code}</small>
              </div>
              <input
                className="range"
                type="range"
                min="0"
                max="100"
                value={draft.weights[code]}
                onChange={(event) => setWeight(code, event.target.value)}
                aria-label={`Баллы: ${settings.features?.[code] || code}`}
              />
              <input
                className="num-input"
                type="number"
                min="0"
                max="100"
                value={draft.weights[code]}
                onChange={(event) => setWeight(code, event.target.value)}
                aria-label={`Баллы числом: ${settings.features?.[code] || code}`}
              />
            </div>
          ))}
          <div className="save-bar">
            <span>
              Новый признак добавляется в бэкенде одной записью — здесь он
              появится сам.
            </span>
            {saveError && (
              <span className="inline-error" role="alert">
                {saveError}
              </span>
            )}
            <button
              className="button button-primary"
              disabled={!changed || saving || Boolean(thresholdError)}
              onClick={save}
            >
              {saving ? "Пересчитываем…" : "Сохранить и пересчитать"}
            </button>
          </div>
        </section>

        <div className="stack">
          {lastChange && summary && (
            <section className="impact" aria-live="polite">
              <span>После последнего изменения</span>
              <div className="impact-row">
                <span>Высокий риск</span>
                <Delta
                  before={lastChange.before?.risk_counts?.high}
                  after={summary.risk_counts?.high}
                />
              </div>
              <div className="impact-row">
                <span>Средний риск</span>
                <Delta
                  before={lastChange.before?.risk_counts?.medium}
                  after={summary.risk_counts?.medium}
                />
              </div>
              <div className="impact-row">
                <span>Потери</span>
                <Delta
                  before={lastChange.before?.potential_loss_minor}
                  after={summary.potential_loss_minor}
                  format={money}
                />
              </div>
              <small>{lastChange.label}</small>
            </section>
          )}

          <section className="card">
            <CardHead
              title="Пороги уровней"
              description="Где заканчивается низкий риск и начинается высокий"
            />
            <div className="scale" aria-hidden="true">
              <div className="scale-track">
                <i
                  style={{
                    left: 0,
                    width: `${medium}%`,
                    background: "var(--risk-low)",
                  }}
                />
                <i
                  style={{
                    left: `${medium}%`,
                    width: `${Math.max(0, high - medium)}%`,
                    background: "var(--risk-medium)",
                  }}
                />
                <i
                  style={{
                    left: `${high}%`,
                    right: 0,
                    background: "var(--risk-high)",
                  }}
                />
              </div>
              <span className="scale-knob" style={{ left: `${medium}%` }} />
              <span className="scale-knob" style={{ left: `${high}%` }} />
              {[0, medium, high, 100].map((value, index) => (
                <span
                  key={index}
                  className="scale-label"
                  style={{ left: `${value}%` }}
                >
                  {value}
                </span>
              ))}
            </div>
            <div className="fields">
              <label className="field">
                <span>Средний — от</span>
                <input
                  type="number"
                  min="0"
                  max="99"
                  value={medium}
                  onChange={(event) =>
                    setNumber("medium_risk_min", event.target.value, 0, 99)
                  }
                />
              </label>
              <label className={`field${thresholdError ? " field-error" : ""}`}>
                <span>Высокий — от</span>
                <input
                  type="number"
                  min="1"
                  max="100"
                  value={high}
                  onChange={(event) =>
                    setNumber("high_risk_min", event.target.value, 1, 100)
                  }
                />
                {thresholdError && <small role="alert">{thresholdError}</small>}
              </label>
            </div>
          </section>

          <section className="card">
            <CardHead
              title="Денежная оценка"
              description="Сколько потеряем, если клиент не продлит услуги"
            />
            <div className="formula">
              <b>
                Потери = max(продления в горизонте − баланс, 0) × score / 100
              </b>
              <small>
                Считаем по каждому клиенту и складываем. Если баланс покрывает
                продления, потери 0.
              </small>
            </div>
            <label className="field">
              <span>Горизонт прогноза, дней</span>
              <input
                type="number"
                min="1"
                max="365"
                value={draft.prediction_horizon_days}
                onChange={(event) =>
                  setNumber(
                    "prediction_horizon_days",
                    event.target.value,
                    1,
                    365,
                  )
                }
              />
            </label>
            {extraKeys.map((key) => (
              <label className="field" key={key}>
                <span>{extraSettings[key].label}</span>
                <input
                  type="number"
                  min={extraSettings[key].min}
                  max={extraSettings[key].max}
                  value={draft[key]}
                  onChange={(event) =>
                    setNumber(
                      key,
                      event.target.value,
                      extraSettings[key].min,
                      extraSettings[key].max,
                    )
                  }
                />
              </label>
            ))}
          </section>
        </div>
      </div>
    </>
  );
}
