import { useEffect, useState } from "react";
import { Icon, RiskBadge } from "./Icons.jsx";
import { PageHeader } from "./Shared.jsx";
import { featureOrder } from "./format.js";

export function ModelPage({ settings, onSave, saving }) {
  const [draft, setDraft] = useState(settings);
  const [saveError, setSaveError] = useState("");
  useEffect(() => setDraft(settings), [settings]);
  if (!draft)
    return (
      <div className="panel loading-card">Загружаем настройки модели…</div>
    );

  const changed = JSON.stringify(draft) !== JSON.stringify(settings);
  const updateWeight = (code, value) =>
    setDraft((current) => ({
      ...current,
      weights: {
        ...current.weights,
        [code]: Math.max(0, Math.min(100, Number(value) || 0)),
      },
    }));
  async function save() {
    if (draft.high_risk_min <= draft.medium_risk_min || draft.customer_high_risk_min <= draft.customer_medium_risk_min) {
      setSaveError("Порог высокого риска должен быть выше среднего и для услуги, и для аккаунта.");
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
        eyebrow="ПРАВИЛА ОЦЕНКИ"
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
              <span className="section-index">01 / ПЕРИОД ПРОГНОЗА</span>
              <h2>Когда искать риск</h2>
              <p>Считаем регулярные продления и степень приближения срока.</p>
            </div>
            <span className="heading-icon">
              <Icon name="clock" />
            </span>
          </div>
          <div className="threshold-grid">
            <label className="threshold-field"><span>Окно срочности</span><div className="threshold-input"><input type="number" min="1" max="30" value={draft.urgency_days} onChange={(e) => setDraft({...draft, urgency_days: Number(e.target.value)})}/><span>дней</span></div></label>
            <label className="threshold-field"><span>Льготный период prolong_wait</span><div className="threshold-input"><input type="number" min="1" max="14" value={draft.grace_days} onChange={(e) => setDraft({...draft, grace_days: Number(e.target.value)})}/><span>дней</span></div></label>
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
              <span className="section-index">02 / СИЛА ПРИЗНАКОВ</span>
              <h2>Что влияет на оценку</h2>
              <p>Вес задаёт относительный вклад признака; оценка каждой услуги нормируется в диапазон 0–100.</p>
            </div>
          </div>
          <div className="weight-list">
            {featureOrder.map((code) => (
              <div className="weight-row" key={code}>
                <span className={`reason-marker reason-marker-${code}`}>
                  <Icon
                    name={
                      code === "payment_distress"
                        ? "wallet"
                        : code === "grace_period_progress"
                          ? "clock"
                          : "pulse"
                    }
                    size={16}
                  />
                </span>
                <span className="weight-copy">
                  <b>{settings.features?.[code] || code}</b>
                  <small>{({
                    payment_distress: "Доля платежа, которую общий доступный баланс не покрывает, с поправкой на срочность.",
                    manual_renewal: "Автопродление выключено; вклад растёт при приближении срока.",
                    renewal_urgency: "Срок близок и требует ручного действия или денег на балансе не хватает.",
                    grace_period_progress: "Доля настроенного срока ожидания оплаты, которая уже прошла.",
                  })[code]}</small>
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
                <span className="section-index">03 / УРОВНИ РИСКА</span>
                <h2>Границы оценки</h2>
                <p>Пороги услуги и аккаунта настраиваются отдельно. Риск аккаунта — сумма оценок его услуг.</p>
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
            <h3>Пороги аккаунта (сумма оценок услуг)</h3>
            <div className="threshold-grid">
              <label className="threshold-field"><span><i className="threshold-dot threshold-dot-medium" />Средний риск с</span><div className="threshold-input"><input type="number" min="0" max="19999" value={draft.customer_medium_risk_min} onChange={(e) => setDraft({...draft, customer_medium_risk_min: Number(e.target.value)})}/><span>баллов</span></div></label>
              <label className="threshold-field"><span><i className="threshold-dot threshold-dot-high" />Высокий риск с</span><div className="threshold-input"><input type="number" min="1" max="20000" value={draft.customer_high_risk_min} onChange={(e) => setDraft({...draft, customer_high_risk_min: Number(e.target.value)})}/><span>баллов</span></div></label>
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
              <span className="section-index">ПОНЯТНЫЙ РАСЧЁТ</span>
              <h3>Что означает оценка</h3>
            </div>
          </div>
          <p>
            Оценка — это сумма баллов за признаки, которые нашли в данных
            клиента. Она помогает расставить приоритеты и не заменяет решение
            специалиста.
          </p>
          <div className="example-score">
            <span>Пример клиента</span>
            <b>
              <strong>55</strong> / 100 за услугу
            </b>
            <div className="example-meter">
              <i />
            </div>
            <RiskBadge level="medium" />
          </div>
          <div className="formula-card">
            <b>Сценарная денежная оценка</b>
            <span>Плановые продления × индекс риска услуги</span>
            <code>€100 × 55% = €55</code>
          </div>
          <div className="model-disclaimer">
            <Icon name="info" size={15} />
            <span>
              Это экспертный индекс, не обученная вероятность ухода. Нет подходящих услуг или корректной даты — услуга не оценивается.
            </span>
          </div>
        </aside>
      </div>
    </>
  );
}
