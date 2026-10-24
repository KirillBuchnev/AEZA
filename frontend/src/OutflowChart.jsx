import { useMemo } from "react";
import { Icon } from "./Icons.jsx";

const WIDTH = 720;
const HEIGHT = 240;
const PAD = { top: 14, right: 12, bottom: 30, left: 40 };

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

export function OutflowChart({ outflow }) {
  const facts = outflow?.facts;
  const forecast = outflow?.forecast;

  const model = useMemo(() => {
    if (!facts || !forecast) return null;
    const today = facts.to_date;
    const end = addDays(forecast.from_date, forecast.horizon_days);
    const days = dayRange(facts.from_date, end);
    const factByDay = new Map(facts.days.map((day) => [day.date, day]));
    const forecastByDay = new Map(
      forecast.buckets.map((bucket) => [bucket.date, bucket]),
    );
    const bars = days.map((date) => {
      const fact = factByDay.get(date);
      const predicted = forecastByDay.get(date);
      return {
        date,
        fact: fact ? fact.deleted + fact.removed + fact.blocked : 0,
        forecast: predicted ? predicted.expected_non_renewals : 0,
        services: predicted ? predicted.services_due : 0,
        atRisk: predicted ? predicted.services_at_risk : 0,
      };
    });
    const top = Math.max(
      1,
      Math.ceil(Math.max(...bars.map((bar) => Math.max(bar.fact, bar.forecast)))),
    );
    return { today, days, bars, top, end };
  }, [facts, forecast]);

  if (!model) {
    return <div className="chart-empty">Данные оттока ещё загружаются.</div>;
  }

  const plotWidth = WIDTH - PAD.left - PAD.right;
  const plotHeight = HEIGHT - PAD.top - PAD.bottom;
  const step = plotWidth / model.days.length;
  const barWidth = Math.max(2, step * 0.62);
  const yFor = (value) => PAD.top + plotHeight * (1 - value / model.top);
  const xFor = (index) => PAD.left + index * step;
  const todayIndex = model.days.indexOf(model.today);
  const factTotal = facts.totals.deleted + facts.totals.removed + facts.totals.blocked;
  const expected = forecast.totals.expected_non_renewals;
  const hasFacts = facts.snapshots_observed > 0 || factTotal > 0;

  const label = `Факт: ${factTotal} услуг удалено, пропало или заблокировано за ${facts.days.length - 1} дн. Прогноз: ${expected} ожидаемых непродлений в ближайшие ${forecast.horizon_days} дн. Услуг в риске: ${forecast.totals.services_at_risk}.`;

  return (
    <div className="outflow">
      <div className="outflow-summary">
        <div className="outflow-chip outflow-chip-fact">
          <span>Факт за период</span>
          <b>{factTotal}</b>
          <small>
            удалено {facts.totals.deleted}, пропало {facts.totals.removed}, блок {facts.totals.blocked}
          </small>
        </div>
        <div className="outflow-chip outflow-chip-forecast">
          <span>Прогноз на {forecast.horizon_days} дн.</span>
          <b>{expected}</b>
          <small>ожидаемых непродлений (индекс / 100)</small>
        </div>
        <div className="outflow-chip">
          <span>Ждут оплаты сейчас</span>
          <b>{forecast.waiting_now.services}</b>
          <small>услуг в grace-периоде</small>
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
            <rect width="6" height="6" fill="var(--surface)" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--ink)" strokeWidth="2" />
          </pattern>
        </defs>
        {[0, 0.5, 1].map((fraction) => {
          const value = Math.round(model.top * fraction);
          const y = yFor(value);
          return (
            <g key={fraction}>
              <line className="outflow-grid" x1={PAD.left} x2={WIDTH - PAD.right} y1={y} y2={y} />
              <text className="outflow-tick" x={PAD.left - 8} y={y + 4} textAnchor="end">
                {value}
              </text>
            </g>
          );
        })}
        {model.bars.map((bar, index) => {
          const x = xFor(index) + (step - barWidth) / 2;
          return (
            <g key={bar.date}>
              {bar.fact > 0 && (
                <rect
                  className="outflow-bar-fact"
                  x={x}
                  y={yFor(bar.fact)}
                  width={barWidth}
                  height={yFor(0) - yFor(bar.fact)}
                >
                  <title>{`${shortDate(bar.date)} · факт: ${bar.fact}`}</title>
                </rect>
              )}
              {bar.forecast > 0 && (
                <rect
                  className="outflow-bar-forecast"
                  x={x}
                  y={yFor(bar.forecast)}
                  width={barWidth}
                  height={yFor(0) - yFor(bar.forecast)}
                  fill="url(#outflow-hatch)"
                >
                  <title>{`${shortDate(bar.date)} · прогноз: ${bar.forecast.toFixed(2)} (услуг: ${bar.services}, в риске: ${bar.atRisk})`}</title>
                </rect>
              )}
            </g>
          );
        })}
        {todayIndex >= 0 && (
          <g>
            <line
              className="outflow-today"
              x1={xFor(todayIndex) + step / 2}
              x2={xFor(todayIndex) + step / 2}
              y1={PAD.top - 4}
              y2={PAD.top + plotHeight}
            />
            <text className="outflow-tick" x={xFor(todayIndex) + step / 2} y={PAD.top - 6} textAnchor="middle">
              сегодня
            </text>
          </g>
        )}
        {model.days.map((date, index) =>
          index % 7 === 0 ? (
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
          Факт: удалено, пропало или заблокировано, по дате снимка
        </span>
        <span>
          <i className="legend-forecast" />
          Прогноз: ожидаемые непродления, по дате окончания
        </span>
      </div>
      {!hasFacts && (
        <div className="calculation-note">
          <Icon name="info" size={15} />
          <span>
            Журнал фактов пуст. Он заполняется, когда загружается следующий
            снимок: тогда видно, какие услуги продлились, удалились или
            заблокировались. Сейчас показан только прогноз.
          </span>
        </div>
      )}
    </div>
  );
}
