/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL
    if (!apiUrl) return []
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/v2/:path*`,
      },
    ]
  },
}

module.exports = nextConfig
