import type { Metadata } from 'next'
import { Inter, JetBrains_Mono } from 'next/font/google'
import './globals.css'
import { SiteJsonLd } from '@/components/JsonLd'
import { SITE_URL, SITE_NAME, SITE_TITLE, SITE_DESCRIPTION, AUTHOR, SOCIAL } from '@/lib/site'

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
  // No global canonical. Declaring one here made every per-route page inherit
  // the homepage as canonical, which silently deindexes the whole ticker tree.
  // Each route that has one declares its own.
  alternates: { canonical: './' },
  title: {
    default: SITE_TITLE,
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
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
    url: SITE_URL,
    locale: 'en_US',
  },
  twitter: {
    card: 'summary_large_image',
    title: SITE_TITLE,
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
        <SiteJsonLd />
        {children}
      </body>
    </html>
  )
}
