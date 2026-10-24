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
  };
  return <svg {...common}>{paths[name] || paths.info}</svg>;
}

export function Brand({ compact = false }) {
  return (
    <div
      className={`brand${compact ? " brand-compact" : ""}`}
      aria-label="AEZA аналитика удержания"
    >
      <div className="brand-mark">
        A<span className="brand-cut" />
      </div>
      {!compact && (
        <div className="brand-copy">
          <span className="brand-name">aéza</span>
          <span className="brand-caption">аналитика удержания</span>
        </div>
      )}
    </div>
  );
}

export function RiskBadge({ level, label }) {
  const value = level || "unscored";
  return (
    <span className={`risk-badge risk-${riskClass(value)}`}>
      <span className="risk-dot" />
      {label || riskText[value]}
    </span>
  );
}
