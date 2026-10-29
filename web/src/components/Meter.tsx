import { barFill, overagePercent, severity, type Severity } from "../format";

/**
 * A thin track with one fill. Drawing is clamped at 100%; an overage adds a cap
 * past the end. The numbers beside the meter are always the exact reported
 * values, never derived from this drawing.
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
    return <div className="meter meter--unknown" role="img" aria-label={`${label}：未知`} />;
  }
  const over = overagePercent(value) !== null;
  const resolved = tone ?? severity(value);
  return (
    <div
      className={`meter meter--${resolved}${muted ? " meter--muted" : ""}${over ? " meter--over" : ""}`}
      role="img"
      aria-label={`${label}：已用 ${value}%`}
    >
      <span className="meter__fill" style={{ width: `${barFill(value)}%` }} />
    </div>
  );
}
