import { riskClass, riskText } from "./format.js";

export function Icon({ name, size = 18 }) {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true,
  };
  const paths = {
    grid: (
      <>
        <rect x="3.5" y="3.5" width="7" height="7" rx="1.8" />
        <rect x="13.5" y="3.5" width="7" height="7" rx="1.8" />
        <rect x="3.5" y="13.5" width="7" height="7" rx="1.8" />
        <rect x="13.5" y="13.5" width="7" height="7" rx="1.8" />
      </>
    ),
    users: (
      <>
        <path d="M16 20v-1.7a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4V20" />
        <circle cx="9.5" cy="7.5" r="3.5" />
        <path d="M20.5 20v-1.7a4 4 0 0 0-3-3.87M15.5 4.2a3.5 3.5 0 0 1 0 6.6" />
      </>
    ),
    sliders: (
      <>
        <path d="M4 7h8m4 0h4M4 17h3m4 0h9" />
        <circle cx="14" cy="7" r="2" />
        <circle cx="9" cy="17" r="2" />
      </>
    ),
    search: (
      <>
        <circle cx="10.8" cy="10.8" r="6.3" />
        <path d="m16 16 4.2 4.2" />
      </>
    ),
    download: (
      <>
        <path d="M12 3v11m0 0 4-4m-4 4-4-4" />
        <path d="M5 16v4h14v-4" />
      </>
    ),
    arrow: (
      <>
        <path d="M5 12h14m-6-6 6 6-6 6" />
      </>
    ),
    close: (
      <>
        <path d="m6 6 12 12M18 6 6 18" />
      </>
    ),
    chevron: <path d="m7 10 5 5 5-5" />,
    logout: (
      <>
        <path d="M10 17l5-5-5-5M15 12H3" />
        <path d="M12 3h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-6" />
      </>
    ),
    server: (
      <>
        <rect x="3" y="4" width="18" height="7" rx="2" />
        <rect x="3" y="13" width="18" height="7" rx="2" />
        <path d="M7 7.5h.01M7 16.5h.01M11 7.5h6M11 16.5h6" />
      </>
    ),
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    wallet: (
      <>
        <path d="M4 6.5A2.5 2.5 0 0 1 6.5 4H19v16H5a2 2 0 0 1-2-2V6.5Z" />
        <path d="M3.5 7H19v5h-4a2 2 0 0 0 0 4h4" />
        <path d="M15 14.5h.01" />
      </>
    ),
    pulse: (
      <>
        <path d="M3 12h4l2-6 4 12 2-6h6" />
      </>
    ),
    check: <path d="m5 12 4 4L19 6" />,
    info: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 11v5m0-8h.01" />
      </>
    ),
    refresh: (
      <>
        <path d="M20 7v5h-5M4 17v-5h5" />
        <path d="M5.6 9a7 7 0 0 1 11.9-2L20 12M4 12l2.5 5a7 7 0 0 0 11.9-2" />
      </>
    ),
    right: <path d="m9 18 6-6-6-6" />,
    sortNone: <path d="M8 10l4-4 4 4M8 14l4 4 4-4" />,
    sortAsc: <path d="M12 18V6M7 11l5-5 5 5" />,
    sortDesc: <path d="M12 6v12M7 13l5 5 5-5" />,
    upload: <path d="M12 16V8M8.5 11.5 12 8l3.5 3.5M5 20h14" />,
    menu: <path d="M4 7h16M4 12h16M4 17h16" />,
    sun: (
      <>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </>
    ),
    moon: <path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z" />,
  };
  return <svg {...common}>{paths[name] || paths.info}</svg>;
}

export function Brand({ inverse = false }) {
  return (
    <span
      className={`brand${inverse ? " brand-inverse" : ""}`}
      role="img"
      aria-label="aéza"
      translate="no"
    >
      {["a", "é", "z", "a"].map((letter, index) => (
        <span key={index} aria-hidden="true">
          {letter}
        </span>
      ))}
    </span>
  );
}

export function RiskKey({ level, score, large = false }) {
  const value = riskClass(level);
  return (
    <span
      className={`key key-${value}${large ? " key-large" : ""}`}
      title={riskText[value]}
      role="img"
      aria-label={
        score == null
          ? "Нет оценки"
          : `${riskText[value]} риск, ${Math.round(score)} из 100`
      }
    >
      {score == null ? "—" : Math.round(score)}
    </span>
  );
}

export function RiskBadge({ level, label }) {
  const value = riskClass(level);
  return (
    <span className={`badge badge-${value}`}>{label || riskText[value]}</span>
  );
}
