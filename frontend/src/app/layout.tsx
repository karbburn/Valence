import type { Metadata } from 'next'
import { Inter, JetBrains_Mono } from 'next/font/google'
import './globals.css'
import { SiteJsonLd } from '@/components/JsonLd'
import { SITE_URL, SITE_NAME, SITE_TITLE, SITE_DESCRIPTION, AUTHOR, SOCIAL, OG_IMAGE } from '@/lib/site'

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
    // The safety net for any route that does not declare its own openGraph. A
    // route that DOES declare one replaces this whole object rather than merging
    // with it, which is why every such route has to repeat `images: [OG_IMAGE]`
    // beside its own title. See the note on OG_IMAGE.
    images: [OG_IMAGE],
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
