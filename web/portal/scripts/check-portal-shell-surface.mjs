import { readFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const portalRoot = path.resolve(new URL('..', import.meta.url).pathname);

const failures = [];

function check(condition, message) {
  if (!condition) failures.push(message);
}

function assertContains(haystack, needle, label) {
  check(haystack.includes(needle), `${label} must contain ${needle}`);
}

function assertNotContains(haystack, needle, label) {
  check(!haystack.includes(needle), `${label} must not contain ${needle}`);
}

async function readPortal(relativePath) {
  return readFile(path.join(portalRoot, relativePath), 'utf8');
}

const portalShell = await readPortal('src/components/portal/PortalShell.tsx');
const authenticatedApp = await readPortal('src/AuthenticatedApp.tsx');
const dashboardLayout = await readPortal('src/components/layout/DashboardLayout.tsx');
const profile = await readPortal('src/pages/Profile.tsx');
const searchModal = await readPortal('src/components/modals/SearchModal.tsx');
const loadingSystem = await readPortal('src/components/loading/LoadingSystem.tsx');
const surfacesCss = await readPortal('src/styles/portal-surfaces.css');
const routeSpec = await readPortal('e2e/portal-v2-routes.spec.ts');
const packageJson = JSON.parse(await readPortal('package.json'));

for (const label of ['Feed', 'Map']) {
  assertContains(portalShell, `title: '${label}'`, 'PortalShell primary nav');
}
for (const label of ['Climbs', 'Rides', 'Portfolio']) {
  assertNotContains(portalShell, `title: '${label}'`, 'PortalShell primary nav');
}
assertContains(portalShell, 'to="/profile?tab=portfolio"', 'PortalShell account menu');
assertContains(authenticatedApp, 'function LegacyMapRedirect()', 'AuthenticatedApp legacy map route');
assertContains(authenticatedApp, '<Navigate to={`/climbs${location.search}${location.hash}`} replace />', 'AuthenticatedApp legacy map route');
assertContains(authenticatedApp, '<Route path="/map" element={<LegacyMapRedirect />} />', 'AuthenticatedApp legacy map route');

for (const [legacyRoute, tab] of [
  ['/training', 'rides'],
  ['/my-activities', 'rides'],
  ['/data', 'training'],
  ['/portfolio', 'portfolio'],
]) {
  assertContains(
    authenticatedApp,
    `<Route path="${legacyRoute}" element={<LegacyProfileTabRedirect tab="${tab}" />} />`,
    'AuthenticatedApp profile-tab redirects',
  );
}
assertContains(authenticatedApp, '<Route path="/find-friends" element={<LegacyFindRidersRedirect />} />', 'AuthenticatedApp rider-search redirect');

for (const [tab, label] of [
  ['overview', 'Overview'],
  ['rides', 'Rides'],
  ['training', 'Training'],
  ['portfolio', 'Portfolio'],
]) {
  assertContains(profile, `id: '${tab}', label: '${label}'`, 'Profile self-only tabs');
}
for (const surface of ['<MyActivities />', '<Data />', '<Portfolio />']) {
  assertContains(profile, surface, 'Profile reused tab surfaces');
}
assertContains(profile, 'const tabs = isOwnProfile', 'Profile self-only tab boundary');
assertContains(searchModal, "'riders'", 'Top-bar search rider category');

for (const label of ['Boulder Roller', 'Upload ride', 'Signed in', 'Portfolio', 'Sign out']) {
  assertContains(portalShell, label, 'PortalShell rider shell copy');
}

for (const staleLabel of ['BOULDERROLLER', 'Wallet / Economy', '${walletSummary} connected', '>Disconnect<']) {
  assertNotContains(portalShell, staleLabel, 'PortalShell rider shell copy');
}

for (const routeTitle of [
  "profileTab === 'rides') return 'My rides'",
  "profileTab === 'training') return 'Training'",
  "profileTab === 'portfolio') return 'Portfolio'",
  "pathname.startsWith('/activities/')",
  ") return 'Ride'",
]) {
  assertContains(dashboardLayout, routeTitle, 'DashboardLayout route title mapping');
}

assertContains(portalShell, 'portal-shell__title', 'PortalShell current-route label');
assertContains(portalShell, 'portal-shell__upload-label', 'PortalShell desktop upload label');
const slot = await readPortal('src/components/loading/Slot.tsx');
const loadingCss = await readPortal('src/styles/loading-system.css');
assertContains(slot, 'export function Slot', 'Shared loading species');
for (const variant of ['text', 'number', 'avatar', 'glyph']) {
  assertContains(slot, `'${variant}'`, 'Slot variants');
}
assertContains(portalShell, '<BackgroundFetchIndicator', 'Shell live rule placement');
assertContains(loadingSystem, 'useIsFetching()', 'Live rule counts all fetching queries');
assertContains(loadingSystem, 'useIsMutating()', 'Live rule counts mutations');
assertContains(loadingSystem, 'delayMs = 160, minVisibleMs = 420', 'Live rule visibility timing');
assertContains(loadingSystem, 'shell-live-rule', 'Shell live rule');
for (const declaration of ['height: 2px', 'bottom: 0', 'background: var(--br-terrain)', '.shell-live-rule']) {
  assertContains(loadingCss, declaration, 'Static cobalt live rule');
}
for (const retired of ['route-transition-skeleton__route-figure', 'route-transition-skeleton__elevation-strip', 'route-transition-skeleton__route-svg']) {
  assertNotContains(loadingSystem, retired, 'Retired loading shape');
  assertNotContains(surfacesCss, retired, 'Retired loading selector');
}

for (const token of [
  '--portal-public-paper: #0F0E0C;',
  '--portal-public-paper-soft: var(--br-paper-soft, #1B1A17);',
  '--portal-public-ink: #F1EEE8;',
  '--portal-public-ink-soft: var(--br-ink-soft, #9A9488);',
  '--portal-public-ink-muted: var(--br-ink-soft, #9A9488);',
  '--portal-public-ink-faint: var(--br-ink-faint, #4E4B46);',
  '--portal-public-terrain: #5592E2;',
  // Ledger: money is a number that matters — ink at weight (Tim-ratified 2026-09-01).
  '--portal-public-cal: #F1EEE8;',
  '--portal-public-dung: #F1EEE8;',
  '.portal-shell__upload-label',
]) {
  assertContains(surfacesCss, token, 'portal-surfaces.css');
}

assertContains(routeSpec, "await expect(accountMenu).toContainText('Portfolio');", 'portal route smoke');
assertContains(routeSpec, "await expect(accountMenu).not.toContainText('Wallet / Economy');", 'portal route smoke');

check(packageJson.scripts?.['qa:portal-shell'] === 'node scripts/check-portal-shell-surface.mjs', 'package.json must expose qa:portal-shell');
check(
  Boolean(packageJson.scripts?.['perf:release']?.includes('npm run qa:portal-shell')),
  'package.json perf:release must run portal-shell surface checks',
);

if (failures.length > 0) {
  console.error('Portal shell surface gate failed:');
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log('Portal shell surface gate passed.');
