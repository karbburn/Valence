import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: process.env.NEXT_PUBLIC_API_URL
          ? `${process.env.NEXT_PUBLIC_API_URL}/api/:path*`
          : 'https://valence-backend-wu85.onrender.com/api/:path*',
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
