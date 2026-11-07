import { readFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

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

async function readPortal(relativePath) {
  return readFile(path.join(portalRoot, relativePath), 'utf8');
}

async function readRepo(relativePath) {
  return readFile(path.join(repoRoot, relativePath), 'utf8');
}

const rideView = (await readPortal('src/pages/RideViewCore.tsx'))
  + (await readPortal('src/components/ride/RideRoom.tsx')); // Shared room composition retains the same object grammar.
const climbView = await readPortal('src/pages/ClimbView.tsx');
const climbIdentity = await readPortal('src/components/climb/ClimbIdentity.tsx');
const climbGeography = await readPortal('src/components/climb/ClimbGeography.tsx');
const climbBoard = await readPortal('src/components/climb/ClimbLeaderboard.tsx');
const climbLegend = await readPortal('src/components/climb/ClimbLegend.tsx');
const climbsView = await readPortal('src/pages/Climbs.tsx');
const vaultView = await readPortal('src/pages/VaultView.tsx');
const authenticatedApp = await readPortal('src/AuthenticatedApp.tsx');
const createVaultView = await readPortal('src/pages/CreateVaultView.tsx');
const vaultCreationForm = await readPortal('src/components/vault/CanonVaultCreationForm.tsx');
const vaultCreationModal = await readPortal('src/components/vault/CanonVaultCreationModal.tsx');
const vaultCreationHook = await readPortal('src/components/vault/useCanonVaultCreation.ts');
const apiClient = await readPortal('src/lib/api.ts');
const profile = await readPortal('src/pages/Profile.tsx');
const polishCss = await readPortal('src/styles/portal-surface-polish.css');
const spineCss = await readPortal('src/styles/portal-spine.css');
const routeSpec = await readPortal('e2e/portal-v2-routes.spec.ts');
const packageJson = JSON.parse(await readPortal('package.json'));
const designContract = await readRepo('docs/design/PORTAL_DESIGN_SYSTEM_2026.md');
const dataInteractionContract = await readRepo('docs/design/PORTAL_DATA_INTERACTION_CONTRACT.md');

for (const needle of [
  'Ride Pages',
  'Climb Pages',
  'Rider Pages',
  'the athletic object first',
  'Place BR consequence second',
]) {
  assertContains(designContract, needle, '2026 portal design contract');
}

for (const needle of [
  'data-object-page="ride"',
  'portal-object-page--ride',
  'data-object-layer="ride-identity"',
  'data-object-layer="ride-route-map"',
  'data-object-layer="ride-stats"',
  'data-object-layer="ride-elevation-climbs"',
  'data-object-layer="ride-record-proof"',
]) {
  assertContains(rideView, needle, 'RideView object grammar');
}

for (const needle of [
  'data-object-page="climb"',
  'portal-object-page--climb',
  'data-object-layer="climb-economy"',
  'All climbs',
  'Leaderboard',
  'Vault',
  'Create Vault',
  'ClimbVaultSection',
  'vaultId={vaultId}',
  '<ClimbIdentity',
  '<ClimbGeography',
  '<ClimbLeaderboard',
  '<ClimbLegend',
  'LegacyVaultDetailRedirect',
  'useVaultLeaderboard',
  'to="/climbs?hasVault=true"',
]) {
  assertContains(climbView, needle, 'ClimbView object grammar');
}

for (const stale of [
  'Back to records',
  'All records',
  'Climb Leaderboard',
  'No leaderboard entries yet',
  'to={`/vaults/${attachedVaultId}`}',
  'navigate(`/vaults/${vaultId}`)',
]) {
  assertNotContains(climbView, stale, 'ClimbView object grammar');
}

// The approved Climb composition is shared by public and signed-in views.
assertContains(climbIdentity, 'data-object-layer="climb-identity"', 'Climb identity');
assertContains(climbGeography, 'data-object-layer="climb-route-elevation"', 'Climb geography');
assertContains(climbBoard, 'data-object-layer="climb-record-board"', 'Climb board');
assertContains(climbBoard, 'type="radio"', 'native metric picker');
assertContains(climbLegend, 'aria-label="Local Legend"', 'one Local Legend');
assertNotContains(vaultView, '<h2>Leaderboard', 'one board');
assertNotContains(vaultView, 'Local Legend', 'one Local Legend');

// One record board per climb (idm63, 2026-09-01): the Leaderboard lives on
// ClimbView only; the embedded Vault section no longer carries its own.
for (const needle of [
  'id="climb-vault"',
  'aria-label="Vault"',
  '<h3>Your position</h3>',
  '<h3>Your position</h3>',
]) {
  assertContains(vaultView, needle, 'embedded climb Vault section');
}

for (const stale of [
  'useParams',
  '<PortalPage',
  '<PortalFrame',
  'Back to vaults',
  'to={`/vaults/${vault.id}`}',
]) {
  assertNotContains(vaultView, stale, 'embedded climb Vault section');
}

for (const needle of [
  'LegacyVaultDetailRedirect',
  'default: module.LegacyVaultDetailRedirect',
  'to="/climbs?hasVault=true"',
  'path="/vaults" element={<LegacyVaultsRedirect />}',
  'path="/vaults/:vaultId" element={<LegacyVaultDetailRedirect />}',
]) {
  assertContains(authenticatedApp, needle, 'legacy Vault route redirects');
}

for (const stale of [
  "import('./pages/Vaults')",
  "import('./pages/VaultView')",
  "from './hooks/queries'",
  '<Vaults />',
  '<VaultView />',
]) {
  assertNotContains(authenticatedApp, stale, 'legacy Vault route redirects');
}

for (const needle of [
  "type Tab = 'all' | 'vaults' | 'staked'",
  "label: 'With vaults'",
  'climbs.filter(hasAttachedVault)',
  "searchParams.get('hasVault') === 'true'",
]) {
  assertContains(climbsView, needle, 'Climbs with-vault filter');
}

for (const stale of [
  'prepareCreateVault',
  'ClimbToVaultFlow',
]) {
  assertNotContains(rideView, stale, 'RideView canon vault cutover');
}

for (const needle of [
  'climbId: climb?.id',
  'navigate(`/climbs/${climb.id}/create-vault`)',
  'creationOpen && canCreate',
  'CanonVaultCreationModal',
]) {
  assertContains(climbView, needle, 'ClimbView canon vault cutover');
}

for (const needle of [
  'CanonVaultCreationForm',
  'VaultCreationPaymentMethod',
]) {
  assertContains(vaultCreationModal, needle, 'canon vault creation modal');
}

for (const needle of [
  'data-object-page="create-vault"',
  'baseMapStyle="terrainBg"',
  'ElevationSparkline',
  'create-vault-workspace',
  'CanonVaultCreationForm',
]) {
  assertContains(createVaultView, needle, 'dedicated canon vault creation page');
}

for (const needle of [
  'Preparing Vault',
  'Confirm in your wallet',
  'Creating Vault',
  'Creation submitted',
  'Vault created',
  'Could not create Vault.',
]) {
  assertContains(vaultCreationForm, needle, 'canon vault creation states');
}

for (const needle of [
  "setPhase('preparing')",
  "setPhase('wallet_confirmation')",
  "setPhase('submitting')",
  "setPhase(submitted.activationState === 'active' ? 'success' : 'pending')",
  "setPhase('error')",
  'preparationId: prepared.preparationId',
]) {
  assertContains(vaultCreationHook, needle, 'canon vault creation state machine');
}

for (const needle of [
  "'/vaults/create/canon/prepare'",
  "'/vaults/create/canon/submit'",
]) {
  assertContains(apiClient, needle, 'canon vault API client');
}

for (const stale of [
  'signature_hex: data.signatureHex',
  'name: data.name',
  'vert_m: data.vertM',
  'distance_m: Math.round(data.distanceM)',
]) {
  assertNotContains(apiClient, stale, 'canon vault API client');
}

for (const needle of [
  'data-object-page="rider"',
  'portal-object-page--rider',
  'data-object-layer="rider-identity"',
  'data-object-layer="rider-activity-history"',
  'This year activity history',
]) {
  assertContains(profile, needle, 'Profile object grammar');
}

assertNotContains(profile, 'Last four weeks activity proof', 'Profile object grammar');

for (const needle of [
  '.portal-object-page',
  '.portal-object-page--ride',
  '.portal-object-page--climb',
  '.portal-object-page--rider',
]) {
  assertContains(polishCss, needle, 'portal-surface-polish.css');
}

for (const needle of [
  '.climb-detail-route-card',
  '.climb-detail-route-card__figure',
  '.climb-detail-route-card__elevation',
  'aspect-ratio: 4 / 3',
  '.climb-detail-hero__facts',
  '.climb-detail-economy-strip',
  '.climb-detail-economy-strip__create',
  '.canon-vault-creation__payment',
  '.create-vault-layout',
  '.create-vault-map',
  '.create-vault-workspace',
  '.climb-detail-record-board',
  '.climb-detail-leaderboard__row',
  '.climb-detail-leaderboard__row[data-rank="1"]',
  'var(--portal-public-dung, var(--portal-dung))',
  '.climb-detail-footnote',
]) {
  assertContains(spineCss, needle, 'portal-spine.css');
}

for (const needle of [
  'Established on ClimbView, Phase C 2.4',
  'Object-page hero',
  'Climb material',
  'Record board jewelry',
  'Attached economy strip',
  'Proof footer',
]) {
  assertContains(dataInteractionContract, needle, 'portal data-interaction contract');
}

for (const needle of [
  "page.locator('[data-object-page=\"ride\"]')",
  "page.locator('[data-object-page=\"climb\"]')",
  "page.locator('[data-object-page=\"rider\"]')",
]) {
  assertContains(routeSpec, needle, 'portal route smoke');
}

check(
  packageJson.scripts?.['qa:object-pages'] === 'node scripts/check-object-page-surface.mjs',
  'package.json must expose qa:object-pages',
);
check(
  Boolean(packageJson.scripts?.['perf:release']?.includes('npm run qa:object-pages')),
  'package.json perf:release must run object-page surface checks',
);

if (failures.length > 0) {
  console.error('Object-page surface gate failed:');
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log('Object-page surface gate passed.');
