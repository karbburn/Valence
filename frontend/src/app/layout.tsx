import type { Metadata } from 'next'
import { Inter, JetBrains_Mono } from 'next/font/google'
import './globals.css'
import { JsonLd } from '@/components/JsonLd'
import { SITE_URL, SITE_NAME, SITE_DESCRIPTION, AUTHOR, SOCIAL } from '@/lib/site'

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
})

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
  display: 'swap',
})

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  alternates: {
    canonical: SITE_URL,
  },
  title: {
    default: `${SITE_NAME} — Equity Valuation & Financial Modeling Workbench`,
    template: `%s · ${SITE_NAME}`,
  },
  description: SITE_DESCRIPTION,
  applicationName: SITE_NAME,
  category: 'finance',
  keywords: [
    'equity valuation',
    'DCF valuation',
    'WACC',
    'financial modeling',
    'three statement model',
    'trading comps',
    'football field valuation',
    'intrinsic value',
    'stock valuation',
    'India equities',
    'US equities',
    'NSE',
    'BSE',
    'NASDAQ',
    'NYSE',
    'Excel financial model',
    'reverse DCF',
    'PE returns',
    'IRR',
    'financial modeling tool',
  ],
  authors: [{ name: AUTHOR.name, url: AUTHOR.url }],
  creator: AUTHOR.name,
  publisher: SITE_NAME,
  openGraph: {
    type: 'website',
    siteName: SITE_NAME,
    title: `${SITE_NAME} — Equity Valuation & Financial Modeling Workbench`,
    description: SITE_DESCRIPTION,
    url: SITE_URL,
    locale: 'en_US',
  },
  twitter: {
    card: 'summary_large_image',
    title: `${SITE_NAME} — Equity Valuation & Financial Modeling Workbench`,
    description: SITE_DESCRIPTION,
    creator: SOCIAL.twitter,
  },
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      'max-image-preview': 'large',
      'max-snippet': -1,
    },
  },
  manifest: '/manifest.webmanifest',
  icons: {
    icon: '/icon.png',
    shortcut: '/icon.png',
    apple: '/icon.png',
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col bg-canvas text-[var(--c-text)] antialiased">
        <JsonLd />
        {children}
      </body>
    </html>
  )
}
