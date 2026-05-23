/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: ["./src/**/*.{js,jsx,ts,tsx}", "./public/index.html"],
  theme: {
    extend: {
      colors: {
        midnight: "#050709",
        steel: "#0B0F14",
        cyan: { DEFAULT: "#00D9FF" },
        orange: { DEFAULT: "#FF6A1A" },
        viridian: { DEFAULT: "#1F8F6B" },
        alloy: { DEFAULT: "#7D8597" },
        gridwhite: { DEFAULT: "#E7ECF5" },
      },
      fontFamily: {
        display: ["Exo 2", "sans-serif"],
        sans: ["IBM Plex Sans", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      borderRadius: {
        sm: "2px",
        DEFAULT: "3px",
        md: "4px",
        lg: "6px",
      },
    },
  },
  plugins: [],
};
