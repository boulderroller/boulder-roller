import { access, readFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const portalRoot = path.resolve(new URL('..', import.meta.url).pathname);
const failures = [];

function check(condition, message) {
  if (!condition) failures.push(message);
}

function assertNotContains(content, needle, label) {
  check(!content.includes(needle), `${label} must not contain ${needle}`);
}

async function readPortal(relativePath) {
  return readFile(path.join(portalRoot, relativePath), 'utf8');
}

async function assertMissing(relativePath) {
  try {
    await access(path.join(portalRoot, relativePath));
    failures.push(`${relativePath} must be deleted`);
  } catch {
    // Expected: ratified surfaces are removed, not parked in the bundle.
  }
}

await Promise.all([
  'src/pages/Achievements.tsx',
  'src/pages/Leaderboard.tsx',
  'src/pages/StravaCallback.tsx',
  'src/pages/AnalyzeView.tsx',
  'src/components/ride/AnalyzeChartsColumn.tsx',
  'src/components/ride/ClimbsTable.tsx',
  'src/components/modals/ShareModal.tsx',
  'src/components/beetle/BeetleAvatar.tsx',
  'src/components/beetle/BeetleCard.tsx',
  'src/components/leaderboard/LeaderboardRow.tsx',
  'src/components/modals/AchievementUnlockModal.tsx',
  'src/hooks/useBeetleCards.ts',
].map(assertMissing));

const app = await readPortal('src/App.tsx');
const authenticatedApp = await readPortal('src/AuthenticatedApp.tsx');
const dashboardLayout = await readPortal('src/components/layout/DashboardLayout.tsx');
const loadingSystem = await readPortal('src/components/loading/LoadingSystem.tsx');
const feed = await readPortal('src/components/feed/ActivityFeedCore.tsx');
const feedQueries = await readPortal('src/hooks/queries/useFeed.ts');
const queryExports = await readPortal('src/hooks/queries/index.ts');
const routePrefetch = await readPortal('src/lib/routePrefetch.ts');
const rideTelemetry = await readPortal('src/lib/rideTelemetry.ts');
const docs = await readPortal('src/pages/Docs.tsx');
const notFound = await readPortal('src/pages/NotFound.tsx');
const notifications = await readPortal('src/pages/Notifications.tsx');
const profile = await readPortal('src/pages/Profile.tsx');
const settings = await readPortal('src/pages/Settings.tsx');
const indexCss = await readPortal('src/index.css');
const globalsCss = await readPortal('src/styles/globals.css');
const surfacePolishCss = await readPortal('src/styles/portal-surface-polish.css');
const spineCss = await readPortal('src/styles/portal-spine.css');
const bundleBudget = await readPortal('perf/bundle-budget.json');
const packageJson = JSON.parse(await readPortal('package.json'));

for (const needle of [
  "import('./pages/Achievements')",
  "import('./pages/Leaderboard')",
  "import('./pages/StravaCallback')",
  'path="/achievements"',
  'path="/records"',
  'path="/leaderboard"',
  'path="/strava/callback"',
  'path="/activities/:activityId/analyze"',
  "import('./pages/AnalyzeView')",
]) {
  assertNotContains(authenticatedApp, needle, 'AuthenticatedApp routes');
}

assertNotContains(app, "currentPath !== '/strava/callback'", 'App return URL handling');

for (const needle of ["'/achievements'", "'/leaderboard'", "pages/Achievements", "pages/Leaderboard", "pages/AnalyzeView"]) {
  assertNotContains(routePrefetch, needle, 'route prefetch map');
}

for (const needle of ['closestStreamIndexByTimestamp', 'streamIndexForGpsIndex', 'streamValueForGpsIndex']) {
  assertNotContains(rideTelemetry, needle, 'retired Analyze telemetry helpers');
}

for (const needle of ['riderType', 'Rider type', 'BeetleCard', 'Beetle cards', 'Strava', 'strava']) {
  assertNotContains(settings, needle, 'Settings');
}

for (const needle of [
  'riderType',
  'BeetleCard',
  'useBeetleCards',
  "label: 'Cards'",
  'Recent milestones',
  'getMyAchievements',
]) {
  assertNotContains(profile, needle, 'Profile');
}

for (const needle of ['useFeedAchievements', 'recentAchievements', 'Recent Achievements', 'feed-rail-achievement']) {
  assertNotContains(feed, needle, 'Feed');
}
assertNotContains(feedQueries, 'useFeedAchievements', 'feed query hooks');
assertNotContains(queryExports, 'useFeedAchievements', 'query hook exports');

for (const needle of ["title: 'Rankings'", "id: 'achievements'", "title: 'Milestones'", 'milestones can count']) {
  assertNotContains(docs, needle, 'Guide');
}

// The store route left with the marketplace freeze (24xry.14, 2026-09-03).
assertNotContains(authenticatedApp, "path=\"/item/:itemId\"", 'Store route');
assertNotContains(notFound, "navigate('/leaderboard')", 'Not found quick links');
assertNotContains(notifications, "label: 'Rankings'", 'Notification filters');

for (const needle of ["pathname === '/leaderboard'", "pathname === '/records'", "pathname === '/achievements'"]) {
  assertNotContains(dashboardLayout, needle, 'Dashboard route labels');
}
assertNotContains(loadingSystem, "pathname === '/leaderboard'", 'Route loading fallback');
assertNotContains(bundleBudget, '"name": "Leaderboard"', 'bundle budget');

for (const needle of [
  '.achievements-',
  '.achievement-row',
  '.achievement-progress',
  '.leaderboard-',
  '.profile-v2-achievement',
  '.profile-v2-beetle',
  '.portal-beetle-card',
  '.portal-beetle-avatar',
  '.settings-v2-beetle',
  '.settings-v2-strava',
  '.settings-v2-connection-card__icon--strava',
  '.settings-v2-import-',
  '.strava-callback',
  '.achievement-unlock',
  '.feed-rail-achievement',
]) {
  assertNotContains(spineCss, needle, 'portal-spine.css');
}
assertNotContains(spineCss, '--portal-strava', 'portal-spine.css');

assertNotContains(indexCss, '.beetle-card', 'index.css');
assertNotContains(globalsCss, '.beetle-card', 'globals.css');
for (const needle of [
  '.settings-v2-beetle',
  '.achievement-row',
  '.leaderboard-',
]) {
  assertNotContains(surfacePolishCss, needle, 'portal-surface-polish.css');
}

check(
  packageJson.scripts?.['qa:ratified-removals'] === 'node scripts/check-ratified-removals.mjs',
  'package.json must expose qa:ratified-removals',
);
check(
  Boolean(packageJson.scripts?.['perf:release']?.includes('npm run qa:ratified-removals')),
  'package.json perf:release must run the ratified-removals gate',
);

if (failures.length > 0) {
  console.error('Portal ratified-removals gate failed:');
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log('Portal ratified-removals gate passed.');
