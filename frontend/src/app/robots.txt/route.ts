import { SITE_URL } from '@/lib/site'

export const revalidate = 86400

/**
 * Crawler policy, served as a custom route so the robots.txt file can carry a
 * Content-Signal directive alongside each group. The standard metadata route
 * cannot emit one.
 *
 * Training is allowed because the engine's method is the point of the product,
 * and there is no protected content. Search and user-triggered fetches are
 * named explicitly so they can be distinguished from training fetches in a log.
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

export async function GET() {
  const signal = 'Content-Signal: search=yes, ai-input=yes, ai-train=yes'
  const lines: string[] = []
  lines.push('User-agent: *')
  lines.push('Allow: /')
  lines.push('Disallow: /api/')
  lines.push(signal)
  lines.push('')
  lines.push(`User-agent: ${ANSWER_CRAWLERS.join(', ')}`)
  lines.push('Allow: /')
  lines.push(signal)
  lines.push('')
  lines.push(`Sitemap: ${SITE_URL}/sitemap.xml`)
  lines.push(`Host: ${SITE_URL}`)
  return new Response(lines.join('\n') + '\n', {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  })
}