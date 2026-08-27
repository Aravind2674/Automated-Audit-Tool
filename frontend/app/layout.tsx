import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "IT Systems Audit Tool",
  description: "Agentless compliance auditing for Linux servers and AWS accounts",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-slate-100 text-slate-900 antialiased">{children}</body>
    </html>
  );
}
