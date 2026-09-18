import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#070B16",
          900: "#0B1222",
          800: "#121B2F",
          700: "#1B2740",
        },
        brand: {
          400: "#5EEAD4",
          500: "#22D3AE",
          600: "#12B394",
        },
      },
      boxShadow: {
        card: "0 1px 2px rgba(0,0,0,.35), 0 12px 30px -18px rgba(0,0,0,.9)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
