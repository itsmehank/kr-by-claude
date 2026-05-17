/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Surfaces
        cream: "#ffffff",        // body background
        paper: "#f8fafc",        // elevated / sub-surface (slate-50)
        // Text
        ink: "#0f172a",          // primary (slate-900)
        muted: "#64748b",        // secondary (slate-500)
        faint: "#94a3b8",        // tertiary (slate-400)
        // Borders
        hairline: "#e2e8f0",     // slate-200
        // Accents
        accent: {
          DEFAULT: "#1e3a8a",    // navy (blue-900)
          light: "#3b82f6",      // blue-500
          soft: "#dbeafe",       // blue-100
        },
        // Semantic
        success: "#15803d",      // green-700
        warning: "#b45309",      // amber-700
        danger: "#b91c1c",       // red-700
      },
      fontFamily: {
        display: [
          '"Pretendard Variable"',
          "Pretendard",
          "-apple-system",
          "BlinkMacSystemFont",
          "system-ui",
          "sans-serif",
        ],
        sans: [
          '"Pretendard Variable"',
          "Pretendard",
          "-apple-system",
          "BlinkMacSystemFont",
          "system-ui",
          "sans-serif",
        ],
        mono: [
          '"JetBrains Mono"',
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
      },
      fontSize: {
        "display-2xl": ["64px", { lineHeight: "1.05", letterSpacing: "-0.025em" }],
        "display-xl": ["44px", { lineHeight: "1.1", letterSpacing: "-0.02em" }],
        "display-lg": ["32px", { lineHeight: "1.15", letterSpacing: "-0.015em" }],
        "display-md": ["22px", { lineHeight: "1.2", letterSpacing: "-0.01em" }],
        headline: ["18px", { lineHeight: "1.35", letterSpacing: "-0.005em" }],
        subhead: ["14px", { lineHeight: "1.4" }],
        body: ["14px", { lineHeight: "1.55" }],
        caption: ["11px", { lineHeight: "1.4", letterSpacing: "0.06em" }],
        "data-xl": ["32px", { lineHeight: "1.05", letterSpacing: "-0.02em" }],
        "data-lg": ["20px", { lineHeight: "1.15", letterSpacing: "-0.01em" }],
        "data-md": ["15px", { lineHeight: "1.25" }],
        data: ["13px", { lineHeight: "1.4" }],
        "data-xs": ["11px", { lineHeight: "1.3" }],
      },
      letterSpacing: {
        caps: "0.1em",
      },
      borderColor: {
        DEFAULT: "#e2e8f0",
      },
    },
  },
  plugins: [],
};
