import { useEffect, useState } from "react";
import { AezaIcon, reasonIcon } from "./AezaIcon.jsx";
import { Icon } from "./Icons.jsx";
import { CardHead, PageHead } from "./Shared.jsx";
import { featureCodes, money, riskText, timeLabel } from "./format.js";

const featureHints = {
  prolong_wait: "Срок прошёл, услуга ждёт оплаты 5 дней до удаления",
  autoprolong_disabled: "Автопродление выключено, срок в ближайшие 7 дней",
  insufficient_balance: "На балансе меньше, чем стоят ближайшие продления",
  renewal_urgency: "Срок в ближайшие 7 дней, вклад растёт к сроку",
};

// Уровни индекса аккаунта, который 0..100, как индекс услуги. Уровни услуг —
// главные пороги выше. Диапазоны совпадают с валидацией бэкенда.
const extraSettings = {
  account_medium_risk_min: {
    label: "Средний риск аккаунта от",
    min: 0,
    max: 99,
  },
  account_high_risk_min: {
    label: "Высокий риск аккаунта от",
    min: 1,
    max: 100,
  },
};

// Тело PATCH принимает ровно эти ключи; всё остальное в черновике (version,
// revision, normalizer, features, timestamps) — read-only и отправлять нельзя.
const EDITABLE_SETTINGS = [
  "prediction_horizon_days",
  "high_risk_min",
  "medium_risk_min",
  "account_high_risk_min",
  "account_medium_risk_min",
];

function toPayload(draft) {
  const payload = { weights: draft.weights };
  EDITABLE_SETTINGS.forEach((key) => {
    payload[key] = draft[key];
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
  const dirty =
    Boolean(draft) && JSON.stringify(draft) !== JSON.stringify(settings);
  useEffect(() => {
    if (!dirty) return undefined;
    const warn = (event) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (!draft)
    return (
      <section className="card">
        <span className="skeleton" style={{ width: 240 }} />
        <span className="skeleton" />
        <span className="skeleton" />
      </section>
    );

  const codes = featureCodes(settings);
  // Подписи берутся из списка features, который возвращает бэкенд: по объекту на фактор.
  const featureTitle = (code) =>
    settings.features?.find((feature) => feature.code === code)?.title || code;
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
          `«${featureTitle(code)}» ${settings.weights[code]} → ${draft.weights[code]}`,
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
              icon="info"
              title="Признаки и баллы"
            />
          </div>
          {codes.map((code) => (
            <div className="coef" key={code}>
              <AezaIcon name={reasonIcon[code] || "info"} size={40} />
              <div className="coef-text">
                <b>{featureTitle(code)}</b>
                <small>{featureHints[code] || code}</small>
              </div>
              <input
                className="range"
                type="range"
                min="0"
                max="100"
                value={draft.weights[code]}
                onChange={(event) => setWeight(code, event.target.value)}
                aria-label={`Баллы: ${featureTitle(code)}`}
              />
              <input
                className="num-input"
                type="number"
                min="0"
                max="100"
                value={draft.weights[code]}
                onChange={(event) => setWeight(code, event.target.value)}
                aria-label={`Баллы числом: ${featureTitle(code)}`}
              />
            </div>
          ))}
          <div className="save-bar">
            <span>
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
          {!lastChange && (
            <section className="impact">
              <span>Что изменится</span>
              <b>Поменяйте балл и сохраните</b>
            </section>
          )}
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
                <span>Ожидаемая потеря</span>
                <Delta
                  before={lastChange.before?.revenue_at_risk_minor}
                  after={summary.revenue_at_risk_minor}
                  format={money}
                />
              </div>
              <small>{lastChange.label}</small>
            </section>
          )}

          <section className="card">
            <CardHead
              icon="error"
              title="Пороги уровней"
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
                <span>Средний от</span>
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
                <span>Высокий от</span>
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
              icon="info"
              title="Контрольные случаи"
              description="Пересчитаны текущими весами"
            />
            <div className="control-table">
              {(settings.control_cases || []).map((item) => (
                <div className="control-row" key={item.key}>
                  <b>{item.key}</b>
                  <span>{item.title}</span>
                  <span className="num">
                    {item.risk_score == null
                      ? "—"
                      : item.risk_score.toFixed(1).replace(".", ",")}
                  </span>
                  <span>
                    {riskText[item.risk_level] || "—"}
                    {!item.matches &&
                      ` (ожидалось: ${riskText[item.expected_level]})`}
                  </span>
                </div>
              ))}
            </div>
          </section>

          <section className="card">
            <CardHead
              icon="euro"
              title="Денежная оценка"
            />
            <div className="formula">
              <b>Ожидаемо = Σ цена услуги × индекс услуги / 100</b>
              <b>Максимум = Σ цена тех же услуг</b>
              <b>
                Из ожидаемого: не хватает средств = Σ недостаток × индекс услуги
                / 100
              </b>
              <b>Выборка = услуги с индексом больше 0, решение по которым впереди</b>
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
