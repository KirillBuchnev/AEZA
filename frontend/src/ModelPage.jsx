import { useEffect, useState } from "react";
import { Icon, RiskBadge } from "./Icons.jsx";
import { PageHeader } from "./Shared.jsx";
import { featureOrder, money, riskText } from "./format.js";

export function ModelPage({ settings, onSave, saving }) {
  const [draft, setDraft] = useState(settings);
  const [saveError, setSaveError] = useState("");
  useEffect(() => setDraft(settings), [settings]);
  if (!draft)
    return (
      <div className="panel loading-card">Загружаем настройки модели…</div>
    );

  const changed = JSON.stringify(draft) !== JSON.stringify(settings);
  const formula = settings.formula || {
    normalizer: 110,
    urgency_weight: 20,
    action_horizon_days: 7,
  };
  const exampleUrgency = Math.max(
    0,
    Math.min(1, 1 - 3 / (formula.action_horizon_days * 24)),
  );
  const exampleScore = Math.round(
    Math.min(
      100,
      ((draft.weights.autoprolong_disabled + formula.urgency_weight) *
        exampleUrgency *
        100) /
        formula.normalizer,
    ),
  );
  const exampleLevel =
    exampleScore >= draft.high_risk_min
      ? "high"
      : exampleScore >= draft.medium_risk_min
        ? "medium"
        : "low";
  const updateWeight = (code, value) =>
    setDraft((current) => ({
      ...current,
      weights: {
        ...current.weights,
        [code]: Math.max(0, Math.min(100, Number(value) || 0)),
      },
    }));
  async function save() {
    if (draft.high_risk_min <= draft.medium_risk_min) {
      setSaveError("Высокий порог должен быть выше среднего.");
      return;
    }
    setSaveError("");
    try {
      await onSave(draft);
    } catch (error) {
      setSaveError(error.message);
    }
  }

  return (
    <>
      <PageHeader
        title="Модель риска"
        description="Настройте, как сигналы влияют на оценку непродления."
        action={
          <span className="model-status">
            <span className="status-indicator" />
            Модель активна
          </span>
        }
      />
      <div className="model-layout">
        <section className="panel model-main-panel">
          <div className="panel-heading">
            <div>
              <h2>Когда искать риск</h2>
              <p>Учитываем услуги, срок которых скоро заканчивается.</p>
            </div>
            <span className="heading-icon">
              <Icon name="clock" />
            </span>
          </div>
          <div className="horizon-control">
            <div>
              <b>Горизонт оценки</b>
              <small>На сколько дней вперёд смотреть продления</small>
            </div>
            <div className="number-control">
              <button
                aria-label="Уменьшить горизонт"
                onClick={() =>
                  setDraft({
                    ...draft,
                    prediction_horizon_days: Math.max(
                      1,
                      draft.prediction_horizon_days - 1,
                    ),
                  })
                }
              >
                −
              </button>
              <input
                type="number"
                min="1"
                max="365"
                value={draft.prediction_horizon_days}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    prediction_horizon_days: Number(event.target.value),
                  })
                }
                aria-label="Горизонт в днях"
              />
              <span>дней</span>
              <button
                aria-label="Увеличить горизонт"
                onClick={() =>
                  setDraft({
                    ...draft,
                    prediction_horizon_days: Math.min(
                      365,
                      draft.prediction_horizon_days + 1,
                    ),
                  })
                }
              >
                +
              </button>
            </div>
          </div>
          <div className="section-divider" />
          <div className="panel-heading weights-heading">
            <div>
              <h2>Что влияет на оценку</h2>
              <p>
                Вклад причин меняется вместе со срочностью и дефицитом, максимум
                — 100.
              </p>
            </div>
          </div>
          <div className="weight-list">
            {featureOrder.map((code) => (
              <div className="weight-row" key={code}>
                <span className={`reason-marker reason-marker-${code}`}>
                  <Icon
                    name={
                      code === "insufficient_balance"
                        ? "wallet"
                        : code === "prolong_wait"
                          ? "hourglass"
                          : "pulse"
                    }
                    size={16}
                  />
                </span>
                <span className="weight-copy">
                  <b>{settings.features?.[code] || code}</b>
                  <small>
                    {code === "prolong_wait"
                      ? "Услуга уже ждёт оплаты после окончания срока."
                      : code === "autoprolong_disabled"
                        ? "Скорое продление без автоматического списания."
                        : code === "insufficient_balance"
                          ? "На ближайшие продления может не хватить средств."
                          : "В снимке есть отклонённый платёж за продление."}
                  </small>
                </span>
                <input
                  className="weight-range"
                  type="range"
                  min="0"
                  max="100"
                  value={draft.weights[code]}
                  onChange={(event) => updateWeight(code, event.target.value)}
                  aria-label={`Вес: ${settings.features?.[code] || code}`}
                />
                <input
                  className="weight-number"
                  type="number"
                  min="0"
                  max="100"
                  value={draft.weights[code]}
                  onChange={(event) => updateWeight(code, event.target.value)}
                  aria-label={`Баллы: ${settings.features?.[code] || code}`}
                />
                <span className="weight-unit">баллов</span>
              </div>
            ))}
          </div>
          <div className="section-divider" />
          <div className="threshold-area">
            <div className="panel-heading">
              <div>
                <h2>Границы оценки</h2>
                <p>Отметки определяют цвет и уровень клиента.</p>
              </div>
            </div>
            <div className="threshold-grid">
              <label className="threshold-field">
                <span>
                  <i className="threshold-dot threshold-dot-medium" />
                  Средний риск начинается с
                </span>
                <div className="threshold-input">
                  <input
                    type="number"
                    min="0"
                    max="99"
                    value={draft.medium_risk_min}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        medium_risk_min: Number(event.target.value),
                      })
                    }
                  />
                  <span>баллов</span>
                </div>
              </label>
              <label className="threshold-field">
                <span>
                  <i className="threshold-dot threshold-dot-high" />
                  Высокий риск начинается с
                </span>
                <div className="threshold-input">
                  <input
                    type="number"
                    min="1"
                    max="100"
                    value={draft.high_risk_min}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        high_risk_min: Number(event.target.value),
                      })
                    }
                  />
                  <span>баллов</span>
                </div>
              </label>
            </div>
            <div className="threshold-preview">
              <span className="threshold-scale">
                <i style={{ width: `${draft.medium_risk_min}%` }} />
                <i
                  style={{
                    left: `${draft.medium_risk_min}%`,
                    width: `${Math.max(0, draft.high_risk_min - draft.medium_risk_min)}%`,
                  }}
                />
                <i
                  style={{
                    left: `${draft.high_risk_min}%`,
                    width: `${100 - draft.high_risk_min}%`,
                  }}
                />
              </span>
              <div className="threshold-legend">
                <span>
                  <i className="threshold-dot threshold-dot-low" />
                  0–{draft.medium_risk_min - 1} низкий
                </span>
                <span>
                  <i className="threshold-dot threshold-dot-medium" />
                  {draft.medium_risk_min}–{draft.high_risk_min - 1} средний
                </span>
                <span>
                  <i className="threshold-dot threshold-dot-high" />
                  {draft.high_risk_min}–100 высокий
                </span>
              </div>
            </div>
          </div>
          <div className="model-save-row">
            {saveError && (
              <span className="inline-error" role="alert">
                {saveError}
              </span>
            )}
            <span className="save-caption">
              После сохранения оценки клиентов пересчитаются автоматически.
            </span>
            <button
              className="button button-primary"
              onClick={save}
              disabled={!changed || saving}
            >
              {saving ? (
                "Пересчитываем…"
              ) : (
                <>
                  <Icon name="check" size={16} />
                  Сохранить настройки
                </>
              )}
            </button>
          </div>
        </section>
        <aside className="panel model-aside">
          <div className="aside-top">
            <span className="aside-icon">
              <Icon name="info" size={20} />
            </span>
            <div>
              <h3>Что означает оценка</h3>
            </div>
          </div>
          <p>
            Оценка — это сумма баллов за признаки, которые нашли в данных
            клиента. Она помогает расставить приоритеты и не заменяет решение
            специалиста.
          </p>
          <div className="example-score">
            <span>Пример: срок через 3 часа, ручное продление</span>
            <b>
              <strong>{exampleScore}</strong> / 100
            </b>
            <div className="example-meter">
              <i style={{ width: `${exampleScore}%` }} />
            </div>
            <RiskBadge level={exampleLevel} label={riskText[exampleLevel]} />
          </div>
          <div className="formula-card">
            <b>Потенциальная потеря</b>
            <span>Недостаток на продления × индекс риска</span>
            <code>
              {money(10000)} × {exampleScore} / 100 ={" "}
              {money((10000 * exampleScore) / 100)}
            </code>
          </div>
          <div className="model-disclaimer">
            <Icon name="info" size={15} />
            <span>
              Нет активных услуг или дат окончания — клиент останется без
              оценки.
            </span>
          </div>
        </aside>
      </div>
    </>
  );
}
