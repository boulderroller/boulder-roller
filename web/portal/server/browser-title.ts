/** Ratified browser-tab grammar; visible shell headings are a separate contract. */
export function composeBrowserTitle(object: string | null, page: string, brand = 'Boulder Roller'): string {
  return [object?.trim() || null, page, brand].filter(Boolean).join(' · ');
}

export function browserPageName(pathname: string, search = ''): string {
  if (pathname === '/' || pathname === '/dashboard') return 'Feed';
  if (pathname === '/climbs' || pathname === '/map') return 'Map';
  if (pathname === '/profile') {
    const tab = new URLSearchParams(search).get('tab');
    return tab === 'rides' ? 'Rides' : tab === 'training' ? 'Training' : tab === 'portfolio' ? 'Portfolio' : 'Profile';
  }
  if (/^\/(activities|rides|ride)\/[^/]+(?:\/(?:climbs\/[^/]+\/)?analysis)?\/?$/.test(pathname)) {
    return pathname.replace(/\/$/, '').endsWith('/analysis') ? 'Ride analysis' : 'Ride';
  }
  if (/^\/activities\/[^/]+\/(log|analyze)$/.test(pathname)) return 'Ride';
  if (/^\/(climbs|climb|segments)\/[^/]+(?:\/(leaderboard|local-legend|create-vault))?\/?$/.test(pathname)) return 'Climb';
  if (/^\/(rider|riders|athletes)\/[^/]+\/?$/.test(pathname)) return 'Rider';
  if (pathname === '/notifications') return 'Notifications';
  if (pathname === '/settings') return 'Settings';
  if (pathname === '/docs') return 'Guide';
  if (pathname === '/admin') return 'Admin';
  return 'Not found';
}
