import { useEffect, useState } from "react";

const TILES = ["a", "é", "z", "a"];

// Brand mark: four rounded tiles, the é stays in place and the others slide into it.
export function BrandLogo({ inverse = false, folded = false, className = "" }) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setOpen(true), 180);
    return () => window.clearTimeout(timer);
  }, []);

  const classes = [
    "brand-logo",
    inverse ? "brand-logo-inverse" : "",
    open && !folded ? "is-open" : "",
    folded ? "is-folded" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <span className={classes} role="img" aria-label="aéza">
      {TILES.map((letter, index) => (
        <span key={index} className={`brand-tile brand-tile-${index}`} aria-hidden="true">
          {letter}
        </span>
      ))}
    </span>
  );
}

// Guidebook pattern: three parallel straight lines and one accent line that turns with a rounded corner.
export function BrandPattern({ tone = "light", className = "" }) {
  const line = tone === "light" ? "#0a0a0a" : "#4cc6f1";
  const accent = tone === "light" ? "#4cc6f1" : "#ffffff";
  return (
    <svg
      className={`brand-pattern ${className}`}
      viewBox="0 0 400 240"
      preserveAspectRatio="xMaxYMax slice"
      aria-hidden="true"
    >
      <path d="M0 196H400M0 210H400M0 224H400" stroke={line} strokeWidth="5" fill="none" />
      <path d="M344 0V150Q344 170 364 170H400" stroke={accent} strokeWidth="9" fill="none" />
    </svg>
  );
}
