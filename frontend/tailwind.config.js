/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  // Night mode is opt-in via a `dark` class on <html>, set by ThemeContext, so
  // the user's own choice wins over the OS setting once they have made one.
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["Tajawal", "sans-serif"],
      },
    },
  },
  plugins: [],
};
