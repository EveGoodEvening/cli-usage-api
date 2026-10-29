import type { ReactNode } from "react";

export interface Fact {
  label: string;
  value: ReactNode;
  /** Spans both columns (long text, nested raw JSON). */
  wide?: boolean;
}

export function Facts({ items, className, id }: { items: Fact[]; className?: string; id?: string }) {
  return (
    <dl className={`facts${className ? ` ${className}` : ""}`} id={id}>
      {items.map((item) => (
        <div key={item.label} className={item.wide ? "facts__wide" : undefined}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A zoned local time with the raw UTC string beneath it. */
export function ZonedTime({ local, raw }: { local: string; raw: string | null }) {
  return (
    <>
      <span>{local}</span>
      {raw ? <span className="facts__utc">UTC {raw}</span> : null}
    </>
  );
}
