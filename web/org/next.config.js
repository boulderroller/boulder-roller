/** @type {import('next').NextConfig} */
const nextConfig = {
  turbopack: { root: __dirname },
  async headers() {
    return [
      {
        source: '/terrain/wises-69415757-:asset',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=31536000, immutable',
          },
        ],
      },
    ]
  },
}
module.exports = nextConfig
