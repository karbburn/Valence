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
            // allow embedding only on your portfolio + self (modern browsers use this, not X-Frame-Options)
            value:
              "frame-ancestors 'self' https://www.sourabhpradhan.in https://sourabhpradhan.in https://*.sourabhpradhan.in https://*.vercel.app",
          },
        ],
      },
    ]
  },
}

export default nextConfig
