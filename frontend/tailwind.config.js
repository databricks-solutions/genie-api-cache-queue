/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
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
          bg: 'var(--dbx-bg)',
          sidebar: 'var(--dbx-sidebar)',
          text: 'var(--dbx-text)',
          'text-secondary': 'var(--dbx-text-secondary)',
          'text-link': 'var(--dbx-text-link)',
          blue: 'var(--dbx-blue)',
          'blue-dark': 'var(--dbx-blue-dark)',
          'blue-hover': 'var(--dbx-blue-hover)',
          border: 'var(--dbx-border)',
          'border-input': 'var(--dbx-border-input)',
          'status-green-bg': 'var(--dbx-status-green-bg)',
          'code-bg': 'var(--dbx-code-bg)',
          'new-btn': 'var(--dbx-new-btn)',
          'neutral-hover': 'var(--dbx-neutral-hover)',
          'text-danger': 'var(--dbx-text-danger)',
          'status-red-bg': 'var(--dbx-status-red-bg)',
          'danger-border': 'var(--dbx-danger-border)',
          disabled: 'var(--dbx-disabled)',
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
