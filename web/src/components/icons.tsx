import type { ReactNode } from "react";

function Icon({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
    >
      {title ? <title>{title}</title> : null}
      {children}
    </svg>
  );
}

export const GaugeIcon = () => (
  <Icon>
    <path d="M4 16a8 8 0 1 1 16 0" />
    <path d="M12 16l4.5-5" />
    <path d="M4 20h16" />
  </Icon>
);

export const AccountsIcon = () => (
  <Icon>
    <rect x="3.5" y="4" width="17" height="6" rx="1.5" />
    <rect x="3.5" y="14" width="17" height="6" rx="1.5" />
    <path d="M7 7h.01M7 17h.01" />
  </Icon>
);

export const PulseIcon = () => (
  <Icon>
    <path d="M3 12h4l2.5-6 5 12 2.5-6h4" />
  </Icon>
);

export const SlidersIcon = () => (
  <Icon>
    <path d="M5 4v16M12 4v16M19 4v16" />
    <rect x="3" y="13" width="4" height="3" rx="1" />
    <rect x="10" y="7" width="4" height="3" rx="1" />
    <rect x="17" y="15" width="4" height="3" rx="1" />
  </Icon>
);

export const MenuIcon = () => (
  <Icon>
    <path d="M4 7h16M4 12h16M4 17h10" />
  </Icon>
);

export const RefreshIcon = () => (
  <Icon>
    <path d="M20 11a8 8 0 1 0-2.3 5.7" />
    <path d="M20 5v6h-6" />
  </Icon>
);

export const SunIcon = () => (
  <Icon>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4" />
  </Icon>
);

export const MoonIcon = () => (
  <Icon>
    <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" />
  </Icon>
);

export const CloseIcon = () => (
  <Icon>
    <path d="M6 6l12 12M18 6 6 18" />
  </Icon>
);
