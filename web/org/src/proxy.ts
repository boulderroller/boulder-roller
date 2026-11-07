import { NextResponse, type NextRequest } from 'next/server'

const CANONICAL_PUBLIC_HOST = 'boulderroller.xyz'
const REDIRECT_HOSTS = new Set([
  'boulderroller.com',
  'www.boulderroller.com',
  'boulderroller.org',
  'www.boulderroller.org',
])

export function proxy(request: NextRequest) {
  const host = request.headers.get('host')?.split(':')[0]?.toLowerCase()

  if (!host || !REDIRECT_HOSTS.has(host)) {
    return NextResponse.next()
  }

  const url = request.nextUrl.clone()
  url.protocol = 'https'
  url.hostname = CANONICAL_PUBLIC_HOST
  url.port = ''

  return NextResponse.redirect(url, 308)
}

export const config = {
  matcher: '/:path*',
}
