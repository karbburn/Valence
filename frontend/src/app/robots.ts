import type { MetadataRoute } from 'next'
import { SITE_URL } from '@/lib/site'

/**
 * Crawler policy.
 *
 * The site is a reference tool, and being cited is how a reference tool earns its
 * traffic from AI search. Nothing here is behind a login, nothing is user data,
 * and every figure on a page is reproducible from public filings, so the crawlers
 * that assemble answers are allowed the same view a visitor gets.
 *
 * The distinction that matters is between the tokens a vendor uses to fetch for
 * training and the tokens it uses to fetch for a search result or on a user's
 * behalf. Those are separate agents with separate names, and a policy that names
 * only the training one either blocks the search surface by accident or blocks
 * training while claiming to. The search and user-triggered tokens are named
 * explicitly below, which is also the only way to see in a log that the citation
 * path is being used.
 *
 * GPTBot trains and is allowed, because the engine's method is the point and
 * there is nothing to protect. OAI-SearchBot and ChatGPT-User are the search and
 * user-triggered fetches. ClaudeBot trains, Claude-SearchBot searches, and
 * Claude-User is a user-initiated fetch. PerplexityBot searches and
 * Perplexity-User is user-initiated. Google-Extended governs Gemini training and
 * grounding, and Googlebot is the ordinary search index. Apple-Extended covers
 * Apple Intelligence, and CCBot is Common Crawl, which many corpora are built on.
 */
const ANSWER_CRAWLERS = [
  'OAI-SearchBot',
  'ChatGPT-User',
  'Claude-SearchBot',
  'Claude-User',
  'PerplexityBot',
  'Perplexity-User',
  'Google-Extended',
  'Apple-Extended',
  'CCBot',
  'GPTBot',
  'ClaudeBot',
  'Googlebot',
  'Bingbot',
]

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: '*',
        allow: '/',
        // The API is a machine surface for this app and nothing else. It is not
        // indexed and not crawled: crawling it buys a crawler nothing and spends
        // a build slot on every URL it walks.
        disallow: ['/api/'],
      },
      {
        userAgent: ANSWER_CRAWLERS,
        allow: '/',
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  }
}
