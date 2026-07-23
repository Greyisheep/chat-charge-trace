/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#2563EB",
          hover: "#1C3BC7",
        },
        ink: {
          DEFAULT: "#101928",
          body: "#344054",
          muted: "#667085",
        },
        line: {
          DEFAULT: "#E4E7EC",
          strong: "#D0D5DD",
        },
        surface: {
          DEFAULT: "#F9FAFB",
          alt: "#F2F4F7",
        },
        success: "#12B76A",
        danger: "#D92D20",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
