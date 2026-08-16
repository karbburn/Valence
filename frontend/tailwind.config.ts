import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        canvas: 'var(--c-canvas)',
        surface: {
          DEFAULT: 'var(--c-surface)',
          2: 'var(--c-surface-2)',
          3: 'var(--c-surface-3)',
        },
        border: {
          DEFAULT: 'var(--c-border)',
          interactive: 'var(--c-border-interactive)',
          strong: 'var(--c-border-strong)',
        },
        accent: {
          DEFAULT: 'var(--c-accent)',
          hover: 'var(--c-accent-hover)',
          subtle: 'var(--c-accent-subtle)',
          border: 'var(--c-accent-border)',
        },
        positive: { DEFAULT: 'var(--c-positive)', subtle: 'var(--c-positive-subtle)' },
        negative: { DEFAULT: 'var(--c-negative)', subtle: 'var(--c-negative-subtle)' },
        warning: { DEFAULT: 'var(--c-warning)', subtle: 'var(--c-warning-subtle)' },
        destructive: { DEFAULT: 'var(--c-destructive)', subtle: 'var(--c-destructive-subtle)' },
        excel: {
          bg: 'var(--c-excel-bg)',
          text: 'var(--c-excel-text)',
          border: 'var(--c-excel-border)',
        },
      },
      fontFamily: {
        sans: ['var(--font-inter)', 'Inter', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
        mono: ['var(--font-mono)', 'JetBrains Mono', 'Fira Code', 'monospace'],
      },
      borderRadius: {
        sm: '4px',
        md: '6px',
        lg: '8px',
      },
    },
  },
  plugins: [],
}

export default config
