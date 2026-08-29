/**
 * Design system, extracted from the Stitch mockups (5-page HTML prototype) and
 * adopted verbatim as our real token set. Every page in the mockup set rendered
 * with `class="light"` -- light mode is the canonical, intended theme, not just
 * one of two options -- so only the light values are carried over.
 *
 * Token names are kept identical to the mockups' own (surface, on-surface,
 * error-container, ...) so a component class list here reads the same as it did
 * in the prototype. That is a deliberate fidelity choice, not an accident.
 *
 * @type {import('tailwindcss').Config}
 */
module.exports = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        "surface-container-highest": "#e4e2e4",
        "surface-container-lowest": "#ffffff",
        surface: "#fcf8fa",
        "on-error-container": "#93000a",
        "surface-bright": "#fcf8fa",
        "on-tertiary": "#ffffff",
        "on-secondary-container": "#54647a",
        "on-primary": "#ffffff",
        "on-primary-fixed-variant": "#3f465c",
        "on-tertiary-container": "#98805d",
        "secondary-fixed": "#d3e4fe",
        "on-surface-variant": "#45464d",
        "inverse-on-surface": "#f3f0f2",
        "surface-tint": "#565e74",
        "tertiary-fixed-dim": "#dec29a",
        "on-tertiary-fixed": "#271901",
        "primary-fixed-dim": "#bec6e0",
        secondary: "#505f76",
        "on-secondary-fixed-variant": "#38485d",
        "on-primary-container": "#7c839b",
        "surface-container": "#f0edef",
        "on-error": "#ffffff",
        "surface-dim": "#dcd9db",
        "surface-container-high": "#eae7e9",
        error: "#ba1a1a",
        background: "#fcf8fa",
        "inverse-primary": "#bec6e0",
        "primary-fixed": "#dae2fd",
        "on-tertiary-fixed-variant": "#574425",
        "tertiary-container": "#271901",
        "on-secondary-fixed": "#0b1c30",
        "secondary-fixed-dim": "#b7c8e1",
        outline: "#76777d",
        "on-background": "#1b1b1d",
        "on-surface": "#1b1b1d",
        "primary-container": "#131b2e",
        "on-primary-fixed": "#131b2e",
        tertiary: "#000000",
        "error-container": "#ffdad6",
        "tertiary-fixed": "#fcdeb5",
        "outline-variant": "#c6c6cd",
        "inverse-surface": "#303032",
        "secondary-container": "#d0e1fb",
        "surface-variant": "#e4e2e4",
        primary: "#000000",
        "surface-container-low": "#f6f3f5",
        "on-secondary": "#ffffff",

        // --- Status/severity semantics NOT present as named tokens in the Stitch
        // theme, but needed for real data (our backend has 4 severities and 4
        // outcome states; the mockups used ad hoc inline hex for these, differently
        // on every page -- see the reconciliation note in components/badges.tsx).
        // Pulled from the ONE pairing that was actually consistent across two of
        // the five mockups (History's and Runs' "Completed"/"Active" pills), so
        // this is still an extraction, not an invention.
        success: "#166534",
        "success-container": "#dcfce7",
      },
      borderRadius: {
        DEFAULT: "0.125rem",
        lg: "0.25rem",
        xl: "0.5rem",
        full: "0.75rem",
      },
      spacing: {
        base: "4px",
        xl: "32px",
        xs: "4px",
        md: "16px",
        gutter: "16px",
        sm: "8px",
        margin: "24px",
        lg: "24px",
      },
      fontFamily: {
        // Wired to next/font/google CSS variables in app/layout.tsx, not the
        // Google Fonts <link> the mockups used -- same typefaces, proper Next.js
        // font loading (self-hosted, no render-blocking request).
        sans: ["var(--font-inter)"],
        mono: ["var(--font-jetbrains-mono)"],
        "display-md": ["var(--font-inter)"],
        "headline-sm": ["var(--font-inter)"],
        "label-caps": ["var(--font-inter)"],
        "display-lg": ["var(--font-inter)"],
        "data-mono": ["var(--font-jetbrains-mono)"],
        "body-sm": ["var(--font-inter)"],
        "body-md": ["var(--font-inter)"],
      },
      fontSize: {
        "display-md": ["24px", { lineHeight: "32px", letterSpacing: "-0.01em", fontWeight: "600" }],
        "headline-sm": ["18px", { lineHeight: "24px", fontWeight: "600" }],
        "label-caps": ["11px", { lineHeight: "16px", letterSpacing: "0.05em", fontWeight: "600" }],
        "display-lg": ["32px", { lineHeight: "40px", letterSpacing: "-0.02em", fontWeight: "600" }],
        "data-mono": ["13px", { lineHeight: "20px", fontWeight: "450" }],
        "body-sm": ["13px", { lineHeight: "18px", fontWeight: "400" }],
        "body-md": ["14px", { lineHeight: "20px", fontWeight: "400" }],
      },
    },
  },
  plugins: [],
};
