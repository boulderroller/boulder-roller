#!/usr/bin/env node

import { access, readFile } from 'node:fs/promises';
import path from 'node:path';

const portalRoot = path.resolve(new URL('..', import.meta.url).pathname);
const repoRoot = path.resolve(portalRoot, '../..');

const failures = [];

function fail(message) {
  failures.push(message);
}

function check(condition, message) {
  if (!condition) fail(message);
}

async function exists(relativePath) {
  try {
    await access(path.join(repoRoot, relativePath));
    return true;
  } catch {
    return false;
  }
}

async function readRepo(relativePath) {
  return readFile(path.join(repoRoot, relativePath), 'utf8');
}

function assertContains(content, needle, label) {
  check(content.includes(needle), `${label} must contain ${needle}`);
}

function assertNotContains(content, needle, label) {
  check(!content.includes(needle), `${label} must not contain ${needle}`);
}

function assertRegex(content, pattern, label, message) {
  check(pattern.test(content), `${label} ${message}`);
}

function publicRoutesOnlyBlock(appContent) {
  const start = appContent.indexOf('if (publicRoutesOnly)');
  const fallbackRoute = 'path="*"';
  const fallbackIndex = appContent.indexOf(fallbackRoute, start + 1);
  const end = fallbackIndex >= 0 ? fallbackIndex + fallbackRoute.length : -1;
  check(start >= 0 && end > start, 'AuthenticatedApp must keep a publicRoutesOnly route block');
  return start >= 0 && end > start ? appContent.slice(start, end) : appContent;
}

async function checkPublicRoot() {
  const hero = `${await readRepo('web/org/src/components/Hero.tsx')}\n${await readRepo('web/org/src/components/ClimbExplorer.tsx')}`;
  const header = await readRepo('web/org/src/components/Header.tsx');
  const layout = await readRepo('web/org/src/app/layout.tsx');
  const proxy = await readRepo('web/org/src/proxy.ts');

  assertContains(hero, 'Boulder Roller', 'public root hero');
  assertNotContains(header, 'https://app.boulderroller.xyz', 'public root header');
  assertNotContains(hero, 'https://app.boulderroller.xyz', 'public root hero');
  assertNotContains(header, 'Log in', 'public root header');
  assertNotContains(header, 'h-2.5 w-2.5', 'public root header');
  assertContains(hero, 'className="terrain-frame"', 'public root hero');
  assertContains(hero, 'type="image/avif"', 'public root terrain');
  assertContains(hero, 'type="image/webp"', 'public root terrain');
  assertContains(hero, 'srcSet={terrainSet(', 'public root terrain');
  assertContains(hero, 'alt=""', 'public root decorative terrain');
  assertContains(hero, 'fetchPriority="high"', 'public root terrain');
  assertContains(hero, '<figure', 'public root recorded ride inset');
  assertContains(hero, 'Wises Mill Road', 'public root recorded ride inset');
  assertContains(hero, '128.7 kilometer ride', 'public root whole-ride profile');
  assertContains(hero, 'Gaps in the recording remain gaps.', 'public root whole-ride profile');
  assertContains(hero, 'https://carto.com/attribution/', 'public root map attribution');
  assertContains(hero, 'https://www.openstreetmap.org/copyright', 'public root map attribution');
  assertRegex(
    hero,
    /<span className="coming-soon" role="status">[\s\S]*?Coming soon\s*<\/span>/,
    'public root release status',
    'must expose Coming soon as status rather than an invented action',
  );
  for (const forbidden of [
    '<button',
    'maplibre',
    '@react-three',
    '<Canvas',
    'Ride workshop preview',
    'Terrain illustration',
  ]) {
    assertNotContains(hero, forbidden, 'public root hero');
  }
  assertContains(
    hero.replace(/\s+/g, ' '),
    'A cycling app with leaderboards that pay riders in DUNG.',
    'public root hero',
  );
  assertNotContains(hero, 'After the ride', 'public root hero');
  assertNotContains(hero, 'On each climb', 'public root hero');
  assertNotContains(hero, 'Local Legend', 'public root hero');
  assertNotContains(hero, 'Vault deposits', 'public root hero');
  assertNotContains(hero, 'Example ride', 'public root hero');
  assertNotContains(hero, 'leaderboard-strip', 'public root hero');
  assertNotContains(hero, 'M. Reyes', 'public root hero');
  assertNotContains(hero, '42.8 km', 'public root hero');
  assertNotContains(hero, 'Counted CAL', 'public root hero');
  assertNotContains(hero, 'Ride record', 'public root hero');
  assertNotContains(hero, 'EST RIDE 0000001', 'public root hero');
  assertNotContains(hero, 'Why Boulder Roller', 'public root hero');
  assertNotContains(hero, 'uppercase', 'public root hero');
  // Ratified browser-tab grammar (2026-09-13): the org root's tab reads 'Boulder Roller', not a title with an explainer.
  assertContains(layout, "title: 'Boulder Roller'", 'public root metadata');
  assertNotContains(layout, 'Boulder Roller — Rides, climbs, and leaderboards', 'public root metadata');
  assertContains(
    layout,
    'A cycling app with leaderboards that pay riders in DUNG.',
    'public root metadata',
  );
  assertNotContains(layout, 'counted results', 'public root metadata');
  assertContains(hero, 'href="https://docs.boulderroller.xyz/"', 'public root docs destination');
  assertContains(hero, 'Read the docs', 'public root docs action');
  assertNotContains(header, 'https://docs.boulderroller.xyz', 'public root header');
  assertNotContains(hero, 'https://scan.boulderroller.xyz', 'public root hero');
  assertNotContains(header, 'https://scan.boulderroller.xyz', 'public root header');
  assertNotContains(hero, 'BoulderScan', 'public root hero');
  assertNotContains(header, 'BoulderScan', 'public root header');
  assertNotContains(header, 'Read docs', 'public root header');
  assertNotContains(hero, 'boulderroller.org', 'public root hero');
  assertNotContains(header, 'boulderroller.org', 'public root header');
  assertContains(proxy, 'boulderroller.com', 'public root redirect proxy');
  assertContains(proxy, 'boulderroller.org', 'public root redirect proxy');
}

async function checkAppEntry() {
  const app = await readRepo('web/portal/src/App.tsx');
  const appBootScreen = await readRepo('web/portal/src/components/loading/AppBootScreen.tsx');
  const inviteGate = await readRepo('web/portal/src/components/auth/InviteGate.tsx');
  const accessPanel = await readRepo('web/portal/src/components/auth/AccessPanel.tsx');
  const authRuntime = await readRepo('web/portal/src/contexts/AuthRuntimeContext.tsx');
  const authSpec = await readRepo('web/portal/e2e/auth-entry.spec.ts');
  const portalIndex = await readRepo('web/portal/index.html');
  const portalSpine = await readRepo('web/portal/src/styles/portal-spine.css');
  const authSurface = await readRepo('web/portal/src/components/auth/AuthSurface.tsx');
  const oldBackdropExists = await exists('web/portal/src/components/auth/AccessPreviewBackdrop.tsx');

  check(!oldBackdropExists, 'AccessPreviewBackdrop must stay removed from app entry');
  assertNotContains(inviteGate, 'AccessPreviewBackdrop', 'InviteGate');
  assertContains(inviteGate, 'data-public-meta-shape="app-entry"', 'InviteGate');
  assertContains(inviteGate, 'access-entry-page--app-threshold', 'InviteGate');
  assertNotContains(inviteGate, 'RouteField', 'InviteGate');
  assertNotContains(inviteGate, 'access-entry-page__visual', 'InviteGate');
  assertNotContains(inviteGate, 'access-entry-page__brand-mark', 'InviteGate');
  assertNotContains(inviteGate, 'access-entry-route', 'InviteGate');
  assertNotContains(inviteGate, 'access-entry-board', 'InviteGate');
  assertNotContains(inviteGate, '87 more riders after sign-in', 'InviteGate');
  assertNotContains(inviteGate, 'Counted CAL', 'InviteGate');
  assertNotContains(inviteGate, 'Ride record', 'InviteGate');
  assertNotContains(inviteGate, 'Manayunk Wall', 'InviteGate');
  assertNotContains(inviteGate, 'Record rides. Match climbs. See what counted.', 'InviteGate');
  assertContains(accessPanel, 'header={<AuthHeading title={pageHeading}', 'AccessPanel');
  assertContains(inviteGate, '<AuthHeader />', 'InviteGate');
  assertContains(accessPanel, "stage === 'invite_entry' || showsAcceptedInvite", 'AccessPanel');
  assertContains(authSurface, 'https://boulderroller.xyz', 'AuthHeader');
  assertNotContains(inviteGate, 'access-entry-page__nav', 'InviteGate');
  assertNotContains(inviteGate, 'Public site', 'InviteGate');
  assertNotContains(inviteGate, 'BoulderScan', 'InviteGate');
  assertNotContains(inviteGate, 'APP ENTRY', 'InviteGate');
  assertNotContains(inviteGate, 'Alpha access', 'InviteGate');
  assertNotContains(inviteGate, 'Recent public rides', 'InviteGate');
  assertNotContains(accessPanel, 'Continue with email', 'AccessPanel');
  assertContains(accessPanel, 'Send code', 'AccessPanel');
  assertContains(accessPanel, 'Use your wallet', 'AccessPanel');
  assertContains(accessPanel, 'Request invite', 'AccessPanel');
  assertContains(accessPanel, 'I have an invite', 'AccessPanel');
  assertContains(accessPanel, 'Enter invite code</AuthNavigation>', 'AccessPanel');
  assertContains(accessPanel, 'Enter invite code', 'AccessPanel');
  assertContains(accessPanel, 'Start your account', 'AccessPanel');
  assertContains(accessPanel, "We'll send a sign-in code.", 'AccessPanel');
  assertContains(accessPanel, 'For riders who signed up with a wallet.', 'AccessPanel');
  assertNotContains(accessPanel, 'HOW_IT_WORKS_ITEMS', 'AccessPanel');
  assertNotContains(accessPanel, 'FAQ_ITEMS', 'AccessPanel');
  assertNotContains(accessPanel, 'Start with an invite', 'AccessPanel');
  assertNotContains(accessPanel, 'Use connected wallet', 'AccessPanel');
  assertNotContains(accessPanel, 'Connect wallet', 'AccessPanel');
  assertNotContains(accessPanel, 'Signs a login message only', 'AccessPanel');
  assertNotContains(accessPanel, 'transaction signature', 'AccessPanel');
  assertNotContains(accessPanel, 'explorer link', 'AccessPanel');
  assertNotContains(accessPanel, 'custody', 'AccessPanel');
  assertContains(portalSpine, '--access-paper: var(--br-paper);', 'app entry CSS');
  assertContains(portalSpine, '--access-ink: var(--br-ink);', 'app entry CSS');
  assertContains(portalSpine, '--access-terrain: var(--br-cal);', 'app entry CSS');
  assertContains(portalSpine, 'font-family: var(--br-font-sans);', 'app entry CSS');
  assertContains(portalSpine, 'font-family: var(--br-font-mono);', 'app entry CSS');
  assertContains(portalSpine, '.access-entry-page--app-threshold', 'app entry CSS');
  assertContains(portalSpine, '.access-entry-page__header', 'app entry CSS');
  assertContains(portalSpine, '.access-panel__wallet-divider', 'app entry CSS');
  assertNotContains(authRuntime, 'fallback={<AppBootScreen />}', 'AuthRuntimeContext');
  assertContains(portalIndex, 'family=Geist', 'portal font preload');
  assertContains(portalIndex, 'family=Geist+Mono', 'portal font preload');
  assertContains(authSpec, 'access-entry-page--app-threshold', 'auth-entry Playwright smoke');
  assertContains(authSpec, 'same quiet shell', 'auth-entry Playwright smoke');
  assertContains(authSpec, 'app-boot-screen', 'auth-entry Playwright smoke');
  assertContains(authSpec, 'BoulderScan', 'auth-entry Playwright smoke');
  assertContains(authSpec, 'Request access', 'auth-entry Playwright smoke');
  assertContains(authSpec, 'access gate should not request feed-backed media previews', 'auth-entry Playwright smoke');
  assertContains(app, 'status: authRuntimeStatus', 'App authenticated runtime recovery');
  assertContains(app, 'error: authRuntimeError', 'App authenticated runtime recovery');
  assertContains(app, 'retryRuntime', 'App authenticated runtime recovery');
  assertContains(app, "authRuntimeStatus === 'failed'", 'App authenticated runtime recovery');
  assertContains(app, 'onRetry={retryRuntime}', 'App authenticated runtime recovery');
  assertContains(appBootScreen, 'onRetry?: () => void', 'AppBootScreen recovery contract');
  assertContains(appBootScreen, 'app-boot-screen__retry', 'AppBootScreen recovery control');
  assertContains(appBootScreen, 'role={onRetry ? \'alert\' : \'status\'}', 'AppBootScreen recovery semantics');
  assertContains(portalSpine, '.app-boot-screen__retry', 'app boot recovery CSS');
  assertContains(authRuntime, 'class AuthRuntimeModuleError', 'AuthRuntimeContext module recovery');
  assertContains(authRuntime, 'lastRuntimeErrorRef.current instanceof AuthRuntimeModuleError', 'AuthRuntimeContext module recovery');
  assertContains(authRuntime, 'window.location.reload()', 'AuthRuntimeContext module recovery');
  assertContains(authSpec, 'recovers from an authenticated Privy runtime module failure', 'auth-entry Playwright smoke');
}

async function checkPublicPreview() {
  const routes = await readRepo('web/portal/src/lib/publicPreviewRoutes.ts');
  const app = await readRepo('web/portal/src/AuthenticatedApp.tsx');
  const publicRoutes = publicRoutesOnlyBlock(app);
  const [previewObjectPage, publicPageShell, authHandoff] = await Promise.all([
    'web/portal/src/pages/PublicPreview.tsx',
    'web/portal/src/components/auth/PublicPageShell.tsx',
    'web/portal/src/lib/authHandoff.ts',
  ].map(readRepo));
  const previewPage = [previewObjectPage, publicPageShell, authHandoff].join('\n');
  const appEntry = await readRepo('web/portal/src/App.tsx');
  const inviteGate = await readRepo('web/portal/src/components/auth/InviteGate.tsx');
  const contracts = await readRepo('backend/app/public_preview_contracts.py');
  const previewRoutes = await readRepo('backend/app/routes/public_previews.py');

  for (const route of ['/rides/', '/climbs/', '/riders/']) {
    assertContains(routes, route, 'public preview route parser');
    assertContains(publicRoutes, `path="${route}:`, 'public preview route mount');
  }

  assertContains(routes, "prefix === 'activities'", 'public preview route parser');
  assertContains(routes, "prefix === 'segments'", 'public preview route parser');
  assertContains(routes, "prefix === 'athletes'", 'public preview route parser');
  assertNotContains(routes, 'leaderboards', 'public preview route parser');
  assertNotContains(publicRoutes, 'path="/leaderboards', 'public route mount');
  assertNotContains(publicRoutes, 'path="/leaderboard', 'public route mount');
  assertContains(previewPage, 'portal-shell__header', 'PublicPreview shared shell');
  assertContains(previewPage, 'ClimbLeaderboard', 'PublicPreview shared leaderboard');
  assertContains(publicPageShell, 'const navigate = useNavigate()', 'PublicPreview entry navigation');
  assertRegex(publicPageShell, /navigate\(\s*['"]\/['"]\s*[,)]/, 'PublicPreview entry navigation', 'must navigate to the existing app entry at /');
  assertContains(appEntry, 'if (!publicPreviewPath && (isLoading || !isAuthenticated))', 'full-page app entry boundary');
  assertContains(appEntry, '<InviteGate', 'full-page app entry boundary');
  assertContains(inviteGate, '<main className="invite-gate access-gate">', 'full-page app entry');
  assertContains(inviteGate, "import AccessPanel from './AccessPanel'", 'full-page app entry');
  assertContains(inviteGate, '<AccessPanel', 'full-page app entry');
  for (const overlay of ['@radix-ui/react-dialog', '<Dialog.', '<dialog', 'role="dialog"', "role='dialog'", 'sign-in-dialog-overlay', 'sign-in-dialog']) {
    assertNotContains(previewPage, overlay, 'PublicPreview must leave entry to the full page');
  }
  assertContains(publicPageShell, "import { storeReturnIntent } from '../../lib/authHandoff'", 'PublicPreview return writer');
  assertRegex(publicPageShell, /storeReturnIntent\(\s*`\$\{location\.pathname\}\$\{location\.search\}\$\{location\.hash\}`/, 'PublicPreview return writer', 'must preserve the object path, query and fragment');
  assertRegex(authHandoff, /export function storeReturnIntent\(destination: string\)\s*\{[\s\S]*?sessionStorage\.setItem\(['"]br_return_url['"]/, 'authHandoff return writer', 'must retain the return-intent storage write');
  assertNotContains(previewObjectPage + publicPageShell, 'sessionStorage.setItem', 'PublicPreview shared handoff writer');
  assertContains(previewPage, 'RidePageIdentity', 'PublicPreview shared ride identity');
  assertContains(previewPage, 'RidePageGeography', 'PublicPreview shared ride geography');
  assertContains(previewPage, 'br_return_url', 'PublicPreview return destination');
  assertNotContains(previewPage, 'MetricTile', 'retired preview grid');
  assertContains(contracts, 'PUBLIC_PREVIEW_FIXTURE_TEXT_RE', 'public preview contracts');
  assertContains(contracts, 'public_route_unavailable_preview', 'public preview contracts');
  assertContains(contracts, 'public_preview_media_items', 'public preview contracts');
  assertNotContains(contracts, 'rideHashHex', 'public preview contracts');
  assertContains(previewRoutes, 'is_public_preview_fixture_like', 'public preview routes');
}

async function checkDocsAndScripts() {
  const packageJson = JSON.parse(await readRepo('web/portal/package.json'));
  const firstTraverse = await readRepo('docs/design/FIRST_TRAVERSE_PUBLIC_PREVIEW_ARCHITECTURE.md');
  const designReadme = await readRepo('docs/design/README.md');
  const designContract = await readRepo('docs/design/PORTAL_DESIGN_SYSTEM_2026.md');

  check(
    packageJson.scripts?.['qa:first-traverse'] === 'node scripts/check-first-traverse-surface.mjs',
    'package.json must expose qa:first-traverse',
  );
  check(
    Boolean(packageJson.scripts?.['perf:release']?.includes('npm run qa:first-traverse')),
    'package.json perf:release must run qa:first-traverse',
  );
  assertContains(firstTraverse, 'Public brand root | `boulderroller.xyz`', 'first traverse architecture');
  assertContains(firstTraverse, 'App | `app.boulderroller.xyz`', 'first traverse architecture');
  assertContains(firstTraverse, 'Docs | `docs.boulderroller.xyz`', 'first traverse architecture');
  assertContains(firstTraverse, 'BoulderScan | `scan.boulderroller.xyz`', 'first traverse architecture');
  assertContains(firstTraverse, 'API | `api.boulderroller.xyz`', 'first traverse architecture');
  assertContains(firstTraverse, 'Request access is email-based', 'first traverse architecture');
  assertContains(firstTraverse, 'No top-level `/leaderboards/:id` public object', 'first traverse architecture');
  assertContains(designContract, 'one public-facing meta-shape with three states', '2026 portal design contract');
  assertContains(designContract, 'App entry should be the clearest proof of this rule', '2026 portal design contract');
  assertRegex(
    designReadme,
    /PORTAL_DESIGN_SYSTEM_2026\.md/,
    'design README',
    'must link the 2026 portal design system',
  );
}

await checkPublicRoot();
await checkAppEntry();
await checkPublicPreview();
await checkDocsAndScripts();

if (failures.length > 0) {
  console.error('First-traverse surface gate failed:');
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log('First-traverse surface gate passed.');
