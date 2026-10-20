import type { ReactNode, SVGProps } from "react";

export type IconName =
  | "overview" | "workspace" | "agents" | "workflow" | "tasks"
  | "knowledge" | "reports" | "settings" | "menu" | "sun" | "moon"
  | "sparkles" | "plus" | "arrow" | "check" | "clock" | "warning" | "close";

const paths: Record<IconName, ReactNode> = {
  overview: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
  workspace: <><path d="M12 3 4.5 7.2v9.6L12 21l7.5-4.2V7.2L12 3Z"/><path d="m8.5 12 2.3 2.3 4.8-5"/></>,
  agents: <><circle cx="9" cy="8" r="3.5"/><path d="M3 20c.5-3.3 2.6-5 6-5s5.5 1.7 6 5"/><path d="M16 5.2a3.5 3.5 0 0 1 0 6.6M18 15c1.8.7 2.8 2.3 3 5"/></>,
  workflow: <><rect x="3" y="4" width="6" height="5" rx="1"/><rect x="15" y="15" width="6" height="5" rx="1"/><path d="M9 6.5h3a3 3 0 0 1 3 3v5.5M15 17.5h-3a3 3 0 0 1-3-3V9"/></>,
  tasks: <><path d="M8 6h13M8 12h13M8 18h13"/><path d="m3 6 1 1 2-2M3 12l1 1 2-2M3 18l1 1 2-2"/></>,
  knowledge: <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21V5.5Z"/><path d="M4 17a2.5 2.5 0 0 1 2.5-2.5H20M8 7h8"/></>,
  reports: <><path d="M6 3h9l4 4v14H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"/><path d="M14 3v5h5M8 12h8M8 16h8"/></>,
  settings: <><circle cx="12" cy="12" r="3"/><path d="m19.4 15 .1.1 1.1.9-1.5 2.6-1.4-.5a7.8 7.8 0 0 1-1.6.9l-.3 1.5h-3l-.3-1.5a7.8 7.8 0 0 1-1.6-.9l-1.4.5L8 16l1.1-.9a7.5 7.5 0 0 1 0-1.8L8 12.4l1.5-2.6 1.4.5a7.8 7.8 0 0 1 1.6-.9l.3-1.5h3l.3 1.5a7.8 7.8 0 0 1 1.6.9l1.4-.5 1.5 2.6-1.1.9a7.5 7.5 0 0 1-.1 1.7Z"/></>,
  menu: <><path d="M4 6h16M4 12h16M4 18h16"/></>,
  sun: <><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></>,
  moon: <path d="M20.5 15.2A8.5 8.5 0 0 1 8.8 3.5 8.5 8.5 0 1 0 20.5 15.2Z"/>,
  sparkles: <><path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3Z"/><path d="m19 15 .9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15ZM5 2l.6 1.4L7 4l-1.4.6L5 6l-.6-1.4L3 4l1.4-.6L5 2Z"/></>,
  plus: <path d="M12 5v14M5 12h14"/>,
  arrow: <><path d="M7 17 17 7M8 7h9v9"/></>,
  check: <path d="m5 12 4 4L19 6"/>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  warning: <><path d="m12 3 10 18H2L12 3Z"/><path d="M12 9v5m0 3h.01"/></>,
  close: <path d="m6 6 12 12M18 6 6 18"/>,
};

export function AppIcon({ name, ...props }: SVGProps<SVGSVGElement> & { name: IconName }) {
  return <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" {...props}>{paths[name]}</svg>;
}
