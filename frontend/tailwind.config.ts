import type { Config } from "tailwindcss";

// Every colour is a semantic token defined as RGB channels in app/globals.css,
// so light and dark themes are designed separately but share one vocabulary.
const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        paper: token("paper"), surface: token("surface"), sunken: token("sunken"),
        ink: token("ink"), "ink-2": token("ink-2"), "ink-3": token("ink-3"),
        line: token("line"), "line-strong": token("line-strong"), control: token("control"),
        accent: token("accent"), "accent-ink": token("accent-ink"), "accent-soft": token("accent-soft"),
        signal: token("signal"), "signal-soft": token("signal-soft"),
        caution: token("caution"), "caution-soft": token("caution-soft"),
        positive: token("positive"), "positive-soft": token("positive-soft"),
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        serif: ["var(--font-serif)", "ui-serif", "Georgia", "serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      fontSize: {
        // A restrained scale: 12 / 13 / 14 / 16 / 20 / 28 / 36
        "2xs": ["0.75rem", { lineHeight: "1rem" }],
        xs: ["0.8125rem", { lineHeight: "1.125rem" }],
        sm: ["0.875rem", { lineHeight: "1.375rem" }],
        base: ["1rem", { lineHeight: "1.625rem" }],
        lg: ["1.25rem", { lineHeight: "1.75rem" }],
        xl: ["1.75rem", { lineHeight: "2.125rem", letterSpacing: "-0.01em" }],
        "2xl": ["2.25rem", { lineHeight: "2.5rem", letterSpacing: "-0.015em" }],
      },
      borderRadius: { DEFAULT: "4px", md: "6px", lg: "8px" },
      boxShadow: {
        overlay: "0 1px 0 rgb(var(--shadow) / .04), 0 12px 32px -8px rgb(var(--shadow) / .22)",
        pop: "0 1px 2px rgb(var(--shadow) / .08), 0 6px 16px -6px rgb(var(--shadow) / .18)",
      },
      transitionTimingFunction: { out: "cubic-bezier(.2,.8,.2,1)" },
      transitionDuration: { fast: "120ms", base: "180ms" },
      keyframes: {
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "rise-in": { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "none" } },
        "slide-in": { from: { opacity: "0", transform: "translateX(16px)" }, to: { opacity: "1", transform: "none" } },
        "sheet-in": { from: { transform: "translateY(24px)", opacity: "0" }, to: { transform: "none", opacity: "1" } },
        breathe: { "0%,100%": { opacity: ".45" }, "50%": { opacity: ".9" } },
      },
      animation: {
        "fade-in": "fade-in 160ms cubic-bezier(.2,.8,.2,1)",
        "rise-in": "rise-in 200ms cubic-bezier(.2,.8,.2,1)",
        "slide-in": "slide-in 220ms cubic-bezier(.2,.8,.2,1)",
        "sheet-in": "sheet-in 240ms cubic-bezier(.2,.8,.2,1)",
        breathe: "breathe 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
