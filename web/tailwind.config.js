/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Surfaces — warm whites
        cream: "#fafaf9",        // body bg (stone-50)
        paper: "#ffffff",        // pure white card surface
        // Text
        ink: "#18181b",          // zinc-900
        muted: "#71717a",        // zinc-500
        faint: "#a1a1aa",        // zinc-400
        // Borders — barely visible
        hairline: "#e4e4e7",     // zinc-200
        // Primary accent
        accent: {
          DEFAULT: "#2563eb",    // blue-600
          light: "#3b82f6",      // blue-500
          soft: "#eff6ff",       // blue-50
        },
        // Secondary accent
        amber: {
          DEFAULT: "#f59e0b",    // amber-500
          soft: "#fffbeb",       // amber-50
          mid: "#fef3c7",        // amber-100
        },
        // Semantic
        success: {
          DEFAULT: "#16a34a",    // green-600
          soft: "#f0fdf4",       // green-50
        },
        warning: "#b45309",
        danger: {
          DEFAULT: "#dc2626",    // red-600
          soft: "#fef2f2",       // red-50
        },
        // Pastel tints for bento cards
        tint: {
          blue: "#eff6ff",       // blue-50
          amber: "#fffbeb",      // amber-50
          rose: "#fef2f2",       // red-50
          mint: "#ecfdf5",       // green-50
          stone: "#f5f5f4",      // stone-100
          violet: "#f5f3ff",     // violet-50
        },
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
        "display-2xl": ["56px", { lineHeight: "1.05", letterSpacing: "-0.03em" }],
        "display-xl": ["40px", { lineHeight: "1.1", letterSpacing: "-0.025em" }],
        "display-lg": ["28px", { lineHeight: "1.2", letterSpacing: "-0.02em" }],
        "display-md": ["20px", { lineHeight: "1.25", letterSpacing: "-0.01em" }],
        headline: ["17px", { lineHeight: "1.35" }],
        subhead: ["14px", { lineHeight: "1.4" }],
        body: ["14px", { lineHeight: "1.55" }],
        caption: ["11px", { lineHeight: "1.4", letterSpacing: "0.04em" }],
        "data-xl": ["44px", { lineHeight: "1.0", letterSpacing: "-0.03em" }],
        "data-lg": ["28px", { lineHeight: "1.15", letterSpacing: "-0.015em" }],
        "data-md": ["18px", { lineHeight: "1.25", letterSpacing: "-0.005em" }],
        data: ["13px", { lineHeight: "1.4" }],
        "data-xs": ["11px", { lineHeight: "1.3" }],
      },
      letterSpacing: {
        caps: "0.04em",
      },
      borderRadius: {
        "2xl": "16px",
        "3xl": "24px",
      },
      boxShadow: {
        bento: "0 1px 2px rgba(24, 24, 27, 0.04), 0 4px 12px rgba(24, 24, 27, 0.04)",
        "bento-hover":
          "0 2px 4px rgba(24, 24, 27, 0.06), 0 8px 24px rgba(24, 24, 27, 0.08)",
      },
      borderColor: {
        DEFAULT: "#e4e4e7",
      },
    },
  },
  plugins: [],
};
