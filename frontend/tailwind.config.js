/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        db: {
          navy: '#0B2026',
          lava: '#FF3621',
          bg: '#F9F7F4',
          oat: '#EEEDE9',
          gray: '#5A6F77',
          green: '#095A35',
          yellow: '#7D5319',
          gold: '#F7B73C',
        },
        // Override default gray palette to warm brand-aligned tones
        gray: {
          50: '#FAFAF8',
          100: '#F9F7F4',
          200: '#EEEDE9',
          300: '#E0DFDB',
          400: '#B5B3AE',
          500: '#5A6F77',
          600: '#44575F',
          700: '#2E3F44',
          800: '#1C2F35',
          900: '#0B2026',
          950: '#071519',
        },
      },
      fontFamily: {
        sans: ['"DM Sans"', 'Arial', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
