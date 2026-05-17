/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        cream: "#f8f4e8",
        paper: "#f0eadc",
        ink: "#1a1a1a",
        muted: "#5a5a5a",
        faint: "#9a9a9a",
        hairline: "#d4cdb8",
        accent: {
          DEFAULT: "#8b0000",
          light: "#c97171",
          soft: "#e8c4c4",
        },
        success: "#2d5016",
        warning: "#8b6914",
        danger: "#8b0000",
      },
      fontFamily: {
        display: ['"Cormorant Garamond"', "Georgia", "serif"],
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
        "display-2xl": ["80px", { lineHeight: "0.95", letterSpacing: "-0.02em" }],
        "display-xl": ["56px", { lineHeight: "1.0", letterSpacing: "-0.015em" }],
        "display-lg": ["40px", { lineHeight: "1.05", letterSpacing: "-0.01em" }],
        "display-md": ["28px", { lineHeight: "1.15", letterSpacing: "-0.005em" }],
        headline: ["20px", { lineHeight: "1.3" }],
        subhead: ["15px", { lineHeight: "1.4", letterSpacing: "0.01em" }],
        body: ["14px", { lineHeight: "1.55" }],
        caption: ["11px", { lineHeight: "1.4", letterSpacing: "0.08em" }],
        "data-xl": ["36px", { lineHeight: "1.0", letterSpacing: "-0.02em" }],
        "data-lg": ["24px", { lineHeight: "1.1", letterSpacing: "-0.01em" }],
        "data-md": ["16px", { lineHeight: "1.2" }],
        data: ["13px", { lineHeight: "1.4" }],
        "data-xs": ["11px", { lineHeight: "1.3" }],
      },
      letterSpacing: {
        caps: "0.14em",
      },
      borderColor: {
        DEFAULT: "#d4cdb8",
      },
    },
  },
  plugins: [],
};
