import { barFill, overagePercent, severity, type Severity } from "../format";

const TICKS = 40;

/**
 * The signature element: a ladder of 40 ticks (2.5% each). Drawing is clamped
 * at 100%; an overage adds a flag past the end notch. The numbers beside the
 * meter are always the exact reported values, never derived from this drawing.
 */
export function Meter({
  value,
  tone,
  muted = false,
  label,
}: {
  value: string | null;
  tone?: Severity | "share";
  muted?: boolean;
  label: string;
}) {
  if (value === null) {
    return (
      <div className="meter meter--unknown" role="img" aria-label={`${label}：未知`}>
        <span className="meter__hatch" />
      </div>
    );
  }
  const fill = barFill(value);
  const lit = Math.floor((fill / 100) * TICKS + 1e-9);
  const over = overagePercent(value) !== null;
  const resolved = tone ?? severity(value);
  return (
    <div
      className={`meter meter--${resolved}${muted ? " meter--muted" : ""}${over ? " meter--over" : ""}`}
      role="img"
      aria-label={`${label}：已用 ${value}%`}
    >
      <span className="meter__ticks">
        {Array.from({ length: TICKS }, (_, i) => (
          <i key={i} className={i < lit ? "on" : undefined} />
        ))}
      </span>
      <span className="meter__notch" />
      {over ? <span className="meter__flag" /> : null}
    </div>
  );
}
