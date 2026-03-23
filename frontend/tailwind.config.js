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
        dbx: {
          bg: '#FFFFFF',
          sidebar: '#F7F7F7',
          text: '#161616',
          'text-secondary': '#6F6F6F',
          'text-link': '#0E538B',
          blue: '#2272B4',
          'blue-hover': 'rgba(34,114,180,0.08)',
          border: '#EBEBEB',
          'border-input': '#CBCBCB',
          'status-green-bg': '#F3FCF6',
          'code-bg': '#F7F7F7',
          'new-btn': 'rgba(255,73,73,0.08)',
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
        sans: ['"DM Sans"', '-apple-system', 'system-ui', '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'Arial', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
