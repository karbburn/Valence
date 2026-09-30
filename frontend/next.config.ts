import type { NextConfig } from 'next'

/**
 * Where the browser gets its data from.
 *
 * This was a bare ternary with a hardcoded deployment hostname as its fallback,
 * which made the target of a build implicit and unstated. A fresh clone, a CI
 * runner and a Vercel build have no `frontend/.env.local` — that file is
 * gitignored — so all three silently read a backend chosen by a string literal in
 * this file rather than by anything the operator stated. It is how a local
 * verification can be green against a backend nobody is looking at: Larsen &
 * Toubro's page served 3,766.40 as of 2026-09-28 while the local model held
 * 3,756.10 as of 2026-09-29, and every status check passed.
 *
 * So the choice is now stated, in this order, and always printed at build time:
 *
 *   1. `NEXT_PUBLIC_API_URL`, whatever the operator set.
 *   2. The deployed host, for a production build that set nothing. Kept working
 *      on purpose — failing the build here would break a launch-day deploy over a
 *      missing variable — but announced, because silently guessing is the part
 *      that was wrong.
 *   3. The local backend, for a development build.
 */
const DEPLOYED_API = 'https://valence-backend-wu85.onrender.com'
const LOCAL_API = 'http://127.0.0.1:8111'

function resolveApiOrigin(): string {
  const configured = process.env.NEXT_PUBLIC_API_URL?.trim()
  if (configured) {
    console.log(`[valence] API origin: ${configured} (from NEXT_PUBLIC_API_URL)`)
    return configured.replace(/\/$/, '')
  }
  if (process.env.NODE_ENV === 'production') {
    console.warn(
      '[valence] NEXT_PUBLIC_API_URL is not set. Falling back to the deployed ' +
        `backend at ${DEPLOYED_API}. Set it explicitly if this build is meant to ` +
        'read a different backend — a build that guesses silently is a build ' +
        'nobody can audit.',
    )
    return DEPLOYED_API
  }
  console.log(`[valence] API origin: ${LOCAL_API} (development default)`)
  return LOCAL_API
}

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${resolveApiOrigin()}/api/:path*`,
      },
    ]
  },
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          {
            key: 'Content-Security-Policy',
            // Allow only the known portfolio and production hosts to embed the app.
            value:
              "frame-ancestors 'self' https://www.sourabhpradhan.in https://sourabhpradhan.in https://valence.sourabhpradhan.in",
          },
        ],
      },
    ]
  },
}

export default nextConfig
