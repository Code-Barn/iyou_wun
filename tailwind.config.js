/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './templates/**/*.html',
    './apps/**/templates/**/*.html',
    './static/**/*.js',
    './docs/ecosystem_shared/**/*.html',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      screens: {
        xs: '360px',
      },
      colors: {
        onyx: {
          950: '#0B0F19',
          900: '#131826',
          800: '#1E2538',
        },
      },
    },
  },
  plugins: [],
};
