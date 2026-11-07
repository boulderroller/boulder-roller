import type { Metadata } from 'next'
import localFont from 'next/font/local'
import './globals.css'

const bodyFont = localFont({
  src: [{ path: './fonts/Geist-Variable.woff2', weight: '100 900' }],
  variable: '--font-body',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'Boulder Roller',
  description:
    'A cycling app with leaderboards that pay riders in DUNG.',
  metadataBase: new URL('https://boulderroller.xyz'),
  alternates: {
    canonical: 'https://boulderroller.xyz',
  },
  openGraph: {
    title: 'Boulder Roller',
    description:
      'A cycling app with leaderboards that pay riders in DUNG.',
    url: 'https://boulderroller.xyz',
    siteName: 'Boulder Roller',
    type: 'website',
    locale: 'en_US',
    images: [
      {
        url: '/share/boulder-roller-b.jpg',
        width: 1200,
        height: 630,
        type: 'image/jpeg',
        alt: 'Boulder Roller over the measured Wises Mill Road ridge, with the recorded climb highlighted in blue.',
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Boulder Roller',
    description:
      'A cycling app with leaderboards that pay riders in DUNG.',
    images: [
      {
        url: '/share/boulder-roller-b.jpg',
        alt: 'Boulder Roller over the measured Wises Mill Road ridge, with the recorded climb highlighted in blue.',
      },
    ],
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className={bodyFont.variable}>
      <body className="antialiased">{children}</body>
    </html>
  )
}
