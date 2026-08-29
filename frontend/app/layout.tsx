import "./globals.css";
import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

// Real Next.js font loading (self-hosted at build time, no render-blocking request)
// rather than the Google Fonts <link> tag the mockups used -- same two typefaces
// specified in the design system: Inter for UI text, JetBrains Mono for IDs/data/
// run numbers.
const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const jetbrainsMono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains-mono" });

export const metadata: Metadata = {
  title: "AuditTool",
  description: "Agentless compliance auditing for Linux servers and AWS accounts",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <head>
        {/* Material Symbols: the icon set used throughout the design system
            (nav glyphs, severity/outcome icons, action icons). A real external
            font request is fine here -- this is a real served Next.js app, not a
            sandboxed artifact. */}
        <link
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="bg-surface font-sans text-body-md text-on-surface antialiased">
        {children}
      </body>
    </html>
  );
}
