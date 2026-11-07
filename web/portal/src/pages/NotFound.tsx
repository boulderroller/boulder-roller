import { useBrowserTitle } from '../contexts/BrowserTitleContext';
import { FailureSheet } from '../components/portal/FailureSpecies';
export default function NotFound() {
  useBrowserTitle('Not found');
  return <FailureSheet title="Route not found" description="This page does not exist or has moved." doors={[{ label: 'Feed', href: '/' }, { label: 'Map', href: '/climbs' }, { label: 'Rides', href: '/profile?tab=rides' }]} />;
}
