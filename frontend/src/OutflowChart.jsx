import { useMemo } from "react";
import { Icon } from "./Icons.jsx";

const WIDTH = 720;
const HEIGHT = 260;
const PAD = { top: 22, right: 12, bottom: 30, left: 44 };
// By the rules of the case a service waits for payment this many days and is then deleted.
const GRACE_DAYS = 5;

function addDays(isoDate, days) {
  const date = new Date(`${isoDate}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function dayRange(from, to) {
  const days = [];
  for (let day = from; day <= to; day = addDays(day, 1)) days.push(day);
  return days;
}

function shortDate(isoDate) {
  const [, month, day] = isoDate.split("-");
  return `${day}.${month}`;
}

const number = (value) =>
  new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(value);

const PERIODS = [
  { days: 30, label: "30 дней" },
  { days: 90, label: "90 дней" },
  { days: 365, label: "Год" },
];

// A count of services is a whole number, so the axis uses whole steps and never repeats a tick.
function scale(peak) {
  const step =
    [1, 2, 5, 10, 20, 50, 100, 200, 500].find((candidate) => peak / candidate <= 4) ?? 1000;
  const top = Math.ceil(peak / step) * step;
  const ticks = [];
  for (let value = 0; value <= top; value += step) ticks.push(value);
  return { top, ticks };
}

export function OutflowChart({ outflow, days = 30, onDays }) {
  const facts = outflow?.facts;
  const forecast = outflow?.forecast;

  const model = useMemo(() => {
    if (!facts || !forecast) return null;
    const dates = dayRange(facts.from_date, addDays(forecast.from_date, forecast.horizon_days));
    const factByDay = new Map(facts.days.map((day) => [day.date, day]));
    const forecastByDay = new Map(forecast.buckets.map((bucket) => [bucket.date, bucket]));
    const bars = dates.map((date) => {
      const fact = factByDay.get(date);
      const bucket = forecastByDay.get(date);
      return {
        date,
        gone: fact ? fact.deleted + fact.removed + fact.blocked : 0,
        deleted: fact?.deleted ?? 0,
        removed: fact?.removed ?? 0,
        blocked: fact?.blocked ?? 0,
        due: bucket?.services_due ?? 0,
        waiting: bucket?.services_waiting ?? 0,
        atRisk: bucket?.services_at_risk ?? 0,
        expected: bucket?.expected_non_renewals ?? 0,
      };
    });
    const peak = Math.max(1, ...bars.map((bar) => Math.max(bar.gone, bar.atRisk, bar.expected)));
    return { today: facts.to_date, dates, bars, ...scale(peak) };
  }, [facts, forecast]);

  if (!model) {
    return <div className="chart-empty">Данные оттока ещё загружаются.</div>;
  }

  const plotWidth = WIDTH - PAD.left - PAD.right;
  const plotHeight = HEIGHT - PAD.top - PAD.bottom;
  const step = plotWidth / model.dates.length;
  const barWidth = Math.max(2, step * 0.62);
  const yFor = (value) => PAD.top + plotHeight * (1 - value / model.top);
  const xFor = (index) => PAD.left + index * step;
  const todayIndex = model.dates.indexOf(model.today);
  const todayX = todayIndex >= 0 ? xFor(todayIndex) + step / 2 : null;
  // Keep about eight date labels on the axis whatever the period is.
  const labelStep = Math.max(7, Math.ceil(model.dates.length / 8));
  const factTotal = facts.totals.deleted + facts.totals.removed + facts.totals.blocked;
  const atRiskTotal = forecast.totals.services_at_risk;
  const dueTotal = forecast.totals.services_due;
  const expected = forecast.totals.expected_non_renewals;
  const waiting = forecast.waiting_now;
  const hasFacts = facts.snapshots_observed > 0 || factTotal > 0;
  const estimated = Boolean(facts.estimated);
  const middle = PAD.top + plotHeight / 2;

  const label = `Ушло ${factTotal} услуг за ${facts.days.length - 1} дн. В ближайшие ${forecast.horizon_days} дн. под риском ${atRiskTotal} из ${dueTotal} услуг со сроком, ожидаемых непродлений около ${number(expected)}.`;

  return (
    <div className="outflow">
      <div className="outflow-periods" role="group" aria-label="Период фактов">
        {PERIODS.map((period) => (
          <button
            key={period.days}
            type="button"
            className={`outflow-period${days === period.days ? " outflow-period-active" : ""}`}
            aria-pressed={days === period.days}
            onClick={() => onDays?.(period.days)}
          >
            {period.label}
          </button>
        ))}
      </div>
      <div className="outflow-summary">
        <div className="outflow-chip outflow-chip-fact">
          <span>Ушло за период{estimated ? " (оценка)" : ""}</span>
          <b>{factTotal}</b>
          <small>
            {estimated
              ? "по текущему снимку, датой считаем окончание срока"
              : `удалено ${facts.totals.deleted}, пропало ${facts.totals.removed}, блок ${facts.totals.blocked}`}
          </small>
        </div>
        <div className="outflow-chip outflow-chip-forecast">
          <span>Под риском в ближайшие {forecast.horizon_days} дн.</span>
          <b>{atRiskTotal}</b>
          <small>
            из {dueTotal} со сроком · ожидаемые непродления: ≈ {number(expected)}
          </small>
        </div>
        <div className="outflow-chip">
          <span>Ждут оплаты</span>
          <b>{waiting.services}</b>
          <small>в grace-периоде до {GRACE_DAYS} дней, потом удаляются</small>
          {waiting.beyond_grace_services > 0 && (
            <small className="outflow-warn">
              ещё {waiting.beyond_grace_services} просрочены сверх {GRACE_DAYS} дней: проверьте статус в источнике
            </small>
          )}
        </div>
      </div>
      <svg
        className="outflow-svg"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={label}
      >
        <defs>
          <pattern
            id="outflow-hatch"
            width="6"
            height="6"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <rect className="outflow-hatch-bg" width="6" height="6" />
            <line className="outflow-hatch-line" x1="0" y1="0" x2="0" y2="6" strokeWidth="2" />
          </pattern>
        </defs>
        <text className="outflow-tick" x={4} y={PAD.top - 8}>
          услуг
        </text>
        {model.ticks.map((value) => (
          <g key={value}>
            <line
              className="outflow-grid"
              x1={PAD.left}
              x2={WIDTH - PAD.right}
              y1={yFor(value)}
              y2={yFor(value)}
            />
            <text className="outflow-tick" x={PAD.left - 8} y={yFor(value) + 4} textAnchor="end">
              {value}
            </text>
          </g>
        ))}
        {model.bars.map((bar, index) => {
          const x = xFor(index) + (step - barWidth) / 2;
          const base = yFor(0);
          return (
            <g key={bar.date}>
              {bar.gone > 0 && (
                <rect
                  className="outflow-bar-fact"
                  x={x}
                  y={yFor(bar.gone)}
                  width={barWidth}
                  height={base - yFor(bar.gone)}
                >
                  <title>{`${shortDate(bar.date)} · ушло: ${bar.gone} (удалено ${bar.deleted}, пропало ${bar.removed}, блок ${bar.blocked})`}</title>
                </rect>
              )}
              {bar.atRisk > 0 && (
                <rect
                  className="outflow-bar-forecast"
                  x={x}
                  y={yFor(bar.atRisk)}
                  width={barWidth}
                  height={base - yFor(bar.atRisk)}
                  fill="url(#outflow-hatch)"
                >
                  <title>{`${shortDate(bar.date)} · под риском: ${bar.atRisk} из ${bar.due} со сроком${bar.waiting ? `, ждут оплаты: ${bar.waiting}` : ""}`}</title>
                </rect>
              )}
              {bar.expected > 0 && (
                <circle
                  className="outflow-dot"
                  cx={xFor(index) + step / 2}
                  cy={yFor(bar.expected)}
                  r={3.5}
                >
                  <title>{`${shortDate(bar.date)} · ожидаемые непродления ≈ ${number(bar.expected)}`}</title>
                </circle>
              )}
            </g>
          );
        })}
        {factTotal === 0 && todayX !== null && (
          <text className="outflow-note" x={(PAD.left + todayX) / 2} y={middle} textAnchor="middle">
            Удалений за период нет
          </text>
        )}
        {atRiskTotal === 0 && todayX !== null && (
          <text
            className="outflow-note"
            x={(todayX + WIDTH - PAD.right) / 2}
            y={middle}
            textAnchor="middle"
          >
            Услуг под риском в горизонте нет
          </text>
        )}
        {todayX !== null && (
          <g>
            <line
              className="outflow-today"
              x1={todayX}
              x2={todayX}
              y1={PAD.top - 4}
              y2={PAD.top + plotHeight}
            />
            <text className="outflow-tick" x={todayX} y={PAD.top - 8} textAnchor="middle">
              сегодня
            </text>
          </g>
        )}
        {model.dates.map((date, index) =>
          index % labelStep === 0 ? (
            <text
              key={date}
              className="outflow-tick"
              x={xFor(index) + step / 2}
              y={HEIGHT - 8}
              textAnchor="middle"
            >
              {shortDate(date)}
            </text>
          ) : null,
        )}
      </svg>
      <div className="outflow-legend">
        <span>
          <i className="legend-fact" />
          {estimated ? "Ушло (оценка): удалено, по дате окончания" : "Ушло: удалено, пропало, заблокировано"}
        </span>
        <span>
          <i className="legend-forecast" />
          Под риском: услуги, срок которых наступает в этот день (ожидающие оплаты, в день удаления)
        </span>
        <span>
          <i className="legend-dot" />
          Ожидаемые непродления
        </span>
      </div>
      {(!hasFacts || estimated) && (
        <div className="calculation-note">
          <Icon name="info" size={15} />
          <span>
            {estimated
              ? "Факты оценены по статусам текущего снимка: удалённую услугу относим к дате окончания срока. Журнал переходов заполнится, когда загрузится следующий снимок."
              : "Журнал переходов пуст: он заполняется, когда загружается следующий снимок, и показывает, какие услуги продлились, удалились или заблокировались. Сейчас показан только прогноз."}
          </span>
        </div>
      )}
    </div>
  );
}
