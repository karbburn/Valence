import type { MetadataRoute } from 'next'
import { SITE_NAME, SITE_DESCRIPTION } from '@/lib/site'

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: `${SITE_NAME}: Equity Valuation & Financial Modeling Workbench`,
    short_name: SITE_NAME,
    description: SITE_DESCRIPTION,
    start_url: '/',
    display: 'standalone',
    background_color: '#080c14',
    theme_color: '#080c14',
    // The document head gets its icons from the file convention in this segment
    // (favicon.ico, icon.png, apple-touch-icon.png). The manifest needs its own
    // entries, and an install prompt asks for a square PNG at a declared size, so
    // it cannot reuse the multi-size .ico.
    icons: [
      { src: '/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: '/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
    ],
  }
}
