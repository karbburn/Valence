import type { MetadataRoute } from 'next'
import { SITE_NAME, SITE_DESCRIPTION } from '@/lib/site'

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: `${SITE_NAME} — Equity Valuation & Financial Modeling Workbench`,
    short_name: SITE_NAME,
    description: SITE_DESCRIPTION,
    start_url: '/',
    display: 'standalone',
    background_color: '#080c14',
    theme_color: '#080c14',
    icons: [{ src: '/icon.png', sizes: 'any', type: 'image/png', purpose: 'any' }],
  }
}
