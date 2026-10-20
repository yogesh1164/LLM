import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgentFlow AI | Workspace",
  description: "Coordinate specialized AI agents in one workspace.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><head><meta charSet="utf-8" /></head><body>{children}</body></html>;
}

