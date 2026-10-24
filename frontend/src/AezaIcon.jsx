// Иконки Aéza из макета: сплошной глиф на плитке-клавише. Класс .g — сам глиф,
// .c — вырезы, они красятся цветом плитки, поэтому иконка работает в любой теме.
const glyphs = {
  wallet: (
    <>
      <path
        className="g"
        fillRule="evenodd"
        d="M5.5 5H18.5A2.5 2.5 0 0 1 21 7.5V9H16.5A3.5 3.5 0 0 0 16.5 16H21V17.5A2.5 2.5 0 0 1 18.5 20H5.5A2.5 2.5 0 0 1 3 17.5V7.5A2.5 2.5 0 0 1 5.5 5ZM16.5 10.5H21V14.5H16.5A2 2 0 0 1 16.5 10.5Z"
      />
      <circle className="g" cx="16.8" cy="12.5" r="1.1" />
      <path className="g" d="M6 4.3L14.9 2.2A1.7 1.7 0 0 1 17 3.85V4.3Z" />
    </>
  ),
  clock: (
    <>
      <circle className="g" cx="12" cy="12" r="9.5" />
      <path className="c" d="M12 7V12L15.2 14" />
    </>
  ),
  euro: (
    <>
      <circle className="g" cx="12" cy="12" r="9.5" />
      <path
        className="c"
        d="M16 8.4A4.9 4.9 0 1 0 16 15.6M7.6 10.8H13M7.6 13.2H13"
      />
    </>
  ),
  dollar: (
    <>
      <circle className="g" cx="12" cy="12" r="9.5" />
      <path
        className="c"
        d="M14.7 9.1C14.3 8 13.3 7.4 12 7.4C10.4 7.4 9.4 8.2 9.4 9.4C9.4 12.2 14.8 11.3 14.8 14.4C14.8 15.7 13.7 16.6 12 16.6C10.5 16.6 9.5 15.9 9.1 14.9M12 5.9V7.4M12 16.6V18.1"
      />
    </>
  ),
  ruble: (
    <>
      <circle className="g" cx="12" cy="12" r="9.5" />
      <path
        className="c"
        d="M10.3 17V7H13.3A2.8 2.8 0 0 1 13.3 12.6H8.6M8.6 15H13.6"
      />
    </>
  ),
  info: (
    <>
      <circle className="g" cx="12" cy="12" r="9.5" />
      <circle className="c-fill" cx="12" cy="7.9" r="1.3" />
      <path className="c" d="M12 11V16.4" />
    </>
  ),
  error: (
    <>
      <path
        className="g"
        d="M10.27 3.5A2 2 0 0 1 13.73 3.5L21.73 17.36A2 2 0 0 1 20 20.36H4A2 2 0 0 1 2.27 17.36Z"
      />
      <path className="c" d="M12 8.8V13.4" />
      <circle className="c-fill" cx="12" cy="16.6" r="1.25" />
    </>
  ),
};

export const reasonIcon = {
  prolong_wait: "clock",
  autoprolong_disabled: "clock",
  manual_renewal: "clock",
  renewal_urgency: "clock",
  insufficient_balance: "wallet",
  payment_distress: "wallet",
  failed_prolong_payment: "error",
  grace_period_progress: "error",
};

export function AezaIcon({ name, size = 40, variant = "key", label }) {
  const glyph = (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      {glyphs[name] || glyphs.info}
    </svg>
  );
  const classes = {
    key: "aicon-key",
    keyBlue: "aicon-key aicon-blue",
    flat: "aicon-flat",
    light: "aicon-light",
  };
  return (
    <span
      className={`aicon ${classes[variant] || classes.key}`}
      style={{ "--size": `${size}px` }}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      {variant.startsWith("key") ? (
        <span className="aicon-face">{glyph}</span>
      ) : (
        glyph
      )}
    </span>
  );
}
