import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

/**
 * ScrollToTop Component
 * Automatically scrolls to top when route changes (Strava-style PWA behavior)
 */
export default function ScrollToTop() {
  const { pathname, search } = useLocation();
  const profileTab = pathname === '/profile'
    ? new URLSearchParams(search).get('tab')
    : null;

  useEffect(() => {
    // Find the main scroll container
    const mainElement = document.querySelector('main');
    if (mainElement) {
      mainElement.scrollTo({
        top: 0,
        behavior: 'instant' // Instant on route change for snappy feel
      });
    }
    window.scrollTo({
      top: 0,
      behavior: 'instant',
    });
  }, [pathname, profileTab]);

  return null;
}
