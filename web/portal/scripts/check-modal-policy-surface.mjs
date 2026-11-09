import { access, readFile } from 'node:fs/promises';
import path from 'node:path';

const portalRoot = path.resolve(new URL('..', import.meta.url).pathname);
const repoRoot = path.resolve(portalRoot, '../..');

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

async function exists(relativePath) {
  try {
    await access(path.join(repoRoot, relativePath));
    return true;
  } catch {
    return false;
  }
}

async function readPortal(relativePath) {
  return readFile(path.join(portalRoot, relativePath), 'utf8');
}

async function readRepo(relativePath) {
  return readFile(path.join(repoRoot, relativePath), 'utf8');
}

const designContract = await readRepo('docs/design/PORTAL_DESIGN_SYSTEM_2026.md');
const firstTraverse = await readRepo('docs/design/FIRST_TRAVERSE_PUBLIC_PREVIEW_ARCHITECTURE.md');
const packageJson = JSON.parse(await readPortal('package.json'));
const authenticatedApp = await readPortal('src/AuthenticatedApp.tsx');
const authSurface = await readPortal('src/components/auth/AuthSurface.tsx');
const setupSurface = await readPortal('src/components/auth/SetupModal.tsx');
const sessionRecovery = await readPortal('src/components/auth/SessionRecoveryScreen.tsx');
const uploadPage = await readPortal('src/pages/Upload.tsx');
const uploadSurface = await readPortal('src/components/upload/UploadActivitySurface.tsx');
const portalSpine = await readPortal('src/styles/portal-spine.css');
const authSpec = await readPortal('e2e/auth-entry.spec.ts');
const uploadSpec = await readPortal('e2e/upload-entry.spec.ts');

for (const needle of [
  '## Modal Policy',
  '### Modal Classification Inventory',
  '| App entry, login, invite, and waitlist | Delete as modal path |',
  '| First-run onboarding setup | Demote |',
  '| Missing FTP/weight reprompt | Demote |',
  '| Session expired or offline recovery | Demote |',
  "| Upload ride | Keep as sheet | The Search sheet's geometry, opened over the current room; /upload opens it over returnTo. |",
  '| Search | Keep |',
  '| Settings delete account, disconnect wallet, revoke sessions | Keep |',
  '| Vault creation and vault creation success | Keep for now |',
  '| Share, achievement, edit activity, invite friend, climb detail, store confirm components | Delete if still unused |',
  '`boulderroller-v2-l93b`',
]) {
  assertContains(designContract, needle, '2026 portal design contract modal policy');
}

assertContains(firstTraverse, '**Hardening bead:** `boulderroller-v2-p0x3`', 'first traverse modal slice');
check(
  packageJson.scripts?.['qa:modal-policy'] === 'node scripts/check-modal-policy-surface.mjs',
  'package.json must expose qa:modal-policy',
);
check(
  Boolean(packageJson.scripts?.['perf:release']?.includes('npm run qa:modal-policy')),
  'package.json perf:release must run qa:modal-policy',
);

assertContains(authenticatedApp, 'SessionRecoveryScreen', 'AuthenticatedApp recovery flow');
assertContains(authenticatedApp, 'authenticated-app-inline-setup', 'AuthenticatedApp setup reprompt');
assertNotContains(authenticatedApp, '<SetupModal', 'AuthenticatedApp setup reprompt');
assertNotContains(authenticatedApp, 'SessionExpiredModal', 'AuthenticatedApp recovery flow');

assertNotContains(authSurface, 'AuthBackdrop', 'AuthSurface');
assertNotContains(authSurface, 'AuthModalFrame', 'AuthSurface');

assertContains(setupSurface, 'first-run-onboarding', 'Setup surface');
assertContains(setupSurface, 'access-entry-page--app-threshold', 'Setup surface');
assertNotContains(setupSurface, 'auth-setup-takeover', 'Setup surface');
assertNotContains(setupSurface, 'AuthBackdrop', 'Setup surface');
assertNotContains(setupSurface, 'AuthModalFrame', 'Setup surface');
assertNotContains(setupSurface, 'role="dialog"', 'Setup surface');
assertNotContains(setupSurface, "variant?: 'modal'", 'Setup surface');

check(
  !(await exists('web/portal/src/components/auth/SessionExpiredModal.tsx')),
  'SessionExpiredModal.tsx must stay removed in favor of SessionRecoveryScreen.tsx',
);
const failureSpecies = await readPortal('src/components/portal/FailureSpecies.tsx');
const loadingCss = await readPortal('src/styles/loading-system.css');
assertContains(sessionRecovery, '<SignInDoor', 'Session expired sign-in door');
assertContains(sessionRecovery, 'Session has expired. Please sign in again.', 'Existing session help line');
assertNotContains(sessionRecovery, 'invite-gate access-gate session-recovery-screen', 'Retired full-page recovery wrapper');
assertContains(failureSpecies, 'data-offline={offline}', 'Retained offline page');
assertContains(failureSpecies, 'offline-pinned-row', 'One pinned offline row');
assertContains(failureSpecies, 'No connection. Try again.', 'Offline row');
assertContains(loadingCss, '.shell-live-rule[data-offline="true"]', 'Dead rule');
assertContains(loadingCss, 'opacity: .55', 'Retained page stale opacity');
assertContains(failureSpecies, 'failure-sheet', 'One failure sheet');
assertContains(failureSpecies, 'portal-shell__header', 'Failure shell');
assertContains(failureSpecies, '<AccessPanel', 'Platform sign-in door');
assertContains(failureSpecies, '<Dialog.Content', 'Accessible sign-in door');
assertNotContains(sessionRecovery, 'AuthModalFrame', 'SessionRecoveryScreen');
assertNotContains(sessionRecovery, 'document.body.style.overflow', 'SessionRecoveryScreen');

check(
  !(await exists('web/portal/src/components/modals/UploadActivityModal.tsx')),
  'UploadActivityModal.tsx must stay removed in favor of UploadActivitySurface.tsx',
);
assertContains(uploadPage, '../components/upload/UploadActivitySurface', 'Upload route');
assertNotContains(uploadPage, 'UploadActivityModal', 'Upload route');
assertNotContains(uploadPage, 'variant="page"', 'Upload route');
assertContains(uploadSurface, 'function UploadActivitySurface', 'UploadActivitySurface');
assertContains(uploadSurface, "from '../ui/responsive-modal'", 'UploadActivitySurface shared sheet');
assertContains(uploadSurface, '<ResponsiveModal open={true}', 'UploadActivitySurface shared sheet');
assertContains(uploadSurface, '<ResponsiveModalBody className="portal-sheet upload-sheet">', 'UploadActivitySurface shared sheet body');
const uploadResponsiveModal = await readPortal('src/components/ui/responsive-modal.tsx');
assertContains(uploadResponsiveModal, '<Drawer open={open}', 'Upload shared drawer');
assertContains(uploadResponsiveModal, '<DrawerContent className="portal-responsive-modal__drawer-content"', 'Upload shared drawer body');
assertContains(uploadResponsiveModal, '<DialogContent', 'Upload shared desktop dialog');
assertNotContains(uploadSurface, "variant?: 'modal'", 'UploadActivitySurface');
assertNotContains(uploadSurface, "variant === 'page'", 'UploadActivitySurface');
assertContains(uploadSpec, "const uploadSurface = page.getByRole('dialog', { name: 'Upload ride', exact: true });", 'Upload named dialog regression');

for (const staleCss of [
  'auth-surface-backdrop',
  'auth-surface-modal-frame',
  'auth-setup-modal__panel-body',
  'session-expired-modal',
]) {
  assertNotContains(portalSpine, staleCss, 'portal-spine.css');
}

for (const regressionSpec of [
  "await expect(page.getByRole('dialog')).toHaveCount(0);",
  "await expect(uploadSurface.locator('.portal-sheet.upload-sheet')).toBeVisible();",
]) {
  assertContains(`${authSpec}\n${uploadSpec}`, regressionSpec, 'modal regression specs');
}

if (failures.length > 0) {
  console.error('Modal policy surface gate failed:');
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log('Modal policy surface gate passed.');
