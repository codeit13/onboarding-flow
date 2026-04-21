import type { Config } from "tailwindcss";

// SINGLE SOURCE OF TRUTH for all Axis Bank brand tokens.
// Aligned with the official axis.bank.in website (2026-04).
// Primary brand color: #97144D (Axis Bank burgundy/maroon).
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        axis: {
          burgundy: {
            DEFAULT: "#97144D",
            dark: "#7A1040",
            light: "#B91C5C",
          },
          magenta: {
            DEFAULT: "#AE275F",
            hover: "#93204F",
          },
          pink: {
            soft: "#FDF2F8",
            banner: "#F4C9D9",
            "banner-end": "#E89FB8",
            50: "#FFF1F5",
          },
          teal: {
            DEFAULT: "#2E9E8E",
            dark: "#1F7A6E",
          },
          cream: {
            DEFAULT: "#FFF8E1",
            border: "#F0E3A8",
          },
          amber: "#E8B923",
          ink: {
            DEFAULT: "#1C1C1C",
            soft: "#404040",
          },
          muted: {
            DEFAULT: "#6B7280",
            light: "#9CA3AF",
          },
          divider: "#E5E7EB",
          surface: "#F9FAFB",
          canvas: "#FFFFFF",
          // Dark footer/header backgrounds matching axis.bank.in
          dark: {
            DEFAULT: "#1C1C2E",
            footer: "#1A1A2E",
            nav: "#2D2D44",
          },
          // Accent strip at top of header (gradient)
          accent: {
            pink: "#E91E63",
            orange: "#FF6F00",
            gold: "#FFB300",
          },
        },
      },
      fontFamily: {
        sans: ['"Inter"', '"Segoe UI"', "system-ui", "-apple-system", "sans-serif"],
        display: ['"Fraunces"', '"Playfair Display"', "Georgia", "serif"],
      },
      boxShadow: {
        card: "0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04)",
        "card-hover":
          "0 4px 16px rgba(0,0,0,0.1), 0 2px 4px rgba(0,0,0,0.06)",
        header: "0 2px 8px rgba(0,0,0,0.06)",
        nav: "0 1px 4px rgba(0,0,0,0.04)",
      },
      borderRadius: {
        card: "12px",
        btn: "8px",
      },
    },
  },
  plugins: [],
};

export default config;
