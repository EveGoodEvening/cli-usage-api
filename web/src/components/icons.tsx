import type { ReactNode } from "react";

function Icon({ children, size = 18 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export const RefreshIcon = () => (
  <Icon>
    <path d="M20 11a8 8 0 1 0-2.3 5.7" />
    <path d="M20 5v6h-6" />
  </Icon>
);

export const MoreIcon = () => (
  <Icon>
    <circle cx="5.5" cy="12" r="1.1" fill="currentColor" stroke="none" />
    <circle cx="12" cy="12" r="1.1" fill="currentColor" stroke="none" />
    <circle cx="18.5" cy="12" r="1.1" fill="currentColor" stroke="none" />
  </Icon>
);

export const ChevronIcon = () => (
  <Icon size={14}>
    <path d="M6 9l6 6 6-6" />
  </Icon>
);

/** Two people, hand-drawn on the 24 grid: account management. */
export const AccountsIcon = () => (
  <Icon>
    <circle cx="9" cy="8.5" r="3.2" />
    <path d="M3.5 19.5c.6-3.2 2.8-5 5.5-5s4.9 1.8 5.5 5" />
    <path d="M15.2 5.6a3.2 3.2 0 0 1 0 5.8" />
    <path d="M17.4 14.8c1.6.7 2.7 2.4 3.1 4.7" />
  </Icon>
);

/** Six dots: a drag handle. */
export const GripIcon = () => (
  <Icon size={16}>
    {[7, 12, 17].flatMap((y) =>
      [9, 15].map((x) => <circle key={`${x}-${y}`} cx={x} cy={y} r="1.2" fill="currentColor" stroke="none" />),
    )}
  </Icon>
);
