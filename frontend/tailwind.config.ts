import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: { extend: { colors: {
    ink: "#17212d", muted: "#667487", line: "#e5e9ed", canvas: "#f5f7f8",
    brand: "#176c63", pale: "#e9f4f1"
  }, boxShadow: { panel: "0 10px 30px rgba(20,36,47,.035)" } } },
  plugins: []
} satisfies Config;
