/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          900: "var(--ink-900)",
          800: "var(--ink-800)",
          700: "var(--ink-700)",
        },
        line: "var(--line)",
        text: "var(--text)",
        dim: "var(--text-dim)",
        accent: "var(--accent)",
        sev: {
          low: "var(--sev-low)",
          med: "var(--sev-med)",
          high: "var(--sev-high)",
          crit: "var(--sev-crit)",
        },
      },
      fontFamily: {
        sans: ["Geist", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      transitionDuration: { DEFAULT: "120ms" },
    },
  },
  plugins: [],
};
