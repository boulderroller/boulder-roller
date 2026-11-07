import { readFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const portalRoot = path.resolve(new URL('..', import.meta.url).pathname);
const repoRoot = path.resolve(portalRoot, '../..');

const readJson = async (relativePath) => JSON.parse(await readFile(path.join(portalRoot, relativePath), 'utf8'));
const readText = async (relativePath) => readFile(path.join(portalRoot, relativePath), 'utf8');
const readRepoText = async (relativePath) => readFile(path.join(repoRoot, relativePath), 'utf8');

const failures = [];

function check(condition, message) {
  if (!condition) failures.push(message);
}

function assertContains(haystack, needle, label) {
  check(haystack.includes(needle), `${label} must contain ${needle}`);
}

function hasHtmlAcceptGuard(rule) {
  return (rule?.has ?? []).some((condition) => (
    condition.type === 'header'
    && condition.key === 'accept'
    && condition.value === '.*text/html.*'
  ));
}

async function checkPortalConfig() {
  const vercelConfig = await readJson('vercel.json');
  const packageJson = await readJson('package.json');
  const qa = await readJson('qa/portal-qa-readiness.json');
  const viteConfig = await readText('vite.config.ts');
  const backendConfig = await readRepoText('backend/app/config.py');
  const dockerCompose = await readRepoText('docker-compose.yml');
  const caddyConfig = await readRepoText('infrastructure/Caddyfile');
  const rewrites = vercelConfig.rewrites ?? [];
  const apiRewrite = rewrites.find((rewrite) => rewrite.source === '/api/:path*');
  const spaRewrite = rewrites.find((rewrite) => rewrite.source === '/(.*)');

  check(apiRewrite?.destination === `${qa.liveTargets.backend}/:path*`, 'Vercel /api rewrite must target the canonical backend host');
  check(spaRewrite?.destination === '/index.html', 'Vercel must keep SPA fallback rewrite');
  check(hasHtmlAcceptGuard(spaRewrite), 'Vercel SPA fallback rewrite must be limited to Accept: text/html');
  check(packageJson.scripts?.['qa:readiness'] === 'node scripts/check-qa-readiness.mjs', 'package.json must expose qa:readiness');
  check(packageJson.scripts?.['qa:first-traverse'] === 'node scripts/check-first-traverse-surface.mjs', 'package.json must expose qa:first-traverse');
  check(packageJson.scripts?.['qa:portal-shell'] === 'node scripts/check-portal-shell-surface.mjs', 'package.json must expose qa:portal-shell');
  check(packageJson.scripts?.['qa:object-pages'] === 'node scripts/check-object-page-surface.mjs', 'package.json must expose qa:object-pages');
  check(packageJson.scripts?.['qa:modal-policy'] === 'node scripts/check-modal-policy-surface.mjs', 'package.json must expose qa:modal-policy');
  check(packageJson.scripts?.['qa:static-assets'] === 'node scripts/check-static-assets.mjs', 'package.json must expose qa:static-assets');
  check(packageJson.scripts?.['qa:live'] === 'node scripts/check-live-deploy.mjs', 'package.json must expose qa:live');
  check(packageJson.scripts?.['deploy:prod'] === 'node scripts/deploy-production.mjs', 'package.json must expose deploy:prod');
  check(packageJson.scripts?.['typecheck:gate'] === 'tsc --project tsconfig.gate.json --pretty false', 'package.json must expose the scoped TypeScript gate');
  check(packageJson.scripts?.['perf:bundle'] === 'node scripts/check-bundle-budget.mjs', 'package.json must expose perf:bundle');
  check(packageJson.scripts?.['perf:delivery'] === 'node scripts/check-delivery-config.mjs', 'package.json must expose perf:delivery');
  check(Boolean(packageJson.scripts?.['perf:release']?.includes('npm run typecheck:gate')), 'package.json perf:release must run the scoped TypeScript gate');
  check(Boolean(packageJson.scripts?.['perf:release']?.includes('npm run test:formatters')), 'package.json perf:release must run formatter behavior tests');
  check(Boolean(packageJson.scripts?.['perf:release']?.includes('npm run qa:formatters-contract')), 'package.json perf:release must run the formatter source guard');
  check(Boolean(packageJson.scripts?.['perf:release']?.includes('npm run perf:bundle')), 'package.json perf:release must run bundle budgets');
  check(Boolean(packageJson.scripts?.['perf:release']?.includes('npm run perf:delivery')), 'package.json perf:release must run delivery config checks');
  check(Boolean(packageJson.scripts?.['perf:release']?.includes('npm run qa:static-assets')), 'package.json perf:release must run static asset checks');
  check(Boolean(packageJson.scripts?.['perf:release']?.includes('npm run qa:first-traverse')), 'package.json perf:release must run first-traverse surface checks');
  check(Boolean(packageJson.scripts?.['perf:release']?.includes('npm run qa:portal-shell')), 'package.json perf:release must run portal shell checks');
  check(Boolean(packageJson.scripts?.['perf:release']?.includes('npm run qa:object-pages')), 'package.json perf:release must run object-page surface checks');
  check(Boolean(packageJson.scripts?.['perf:release']?.includes('npm run qa:modal-policy')), 'package.json perf:release must run modal policy checks');
  check(packageJson.scripts?.build === 'vite build', 'Portal build script must remain vite build');
  check(viteConfig.includes('br-portal-build-info'), 'Vite build must emit portal build identity metadata');
  check(viteConfig.includes('version.json'), 'Vite build must emit version.json for live deploy verification');
  check(viteConfig.includes("mode === 'production' ? 'https://api.boulderroller.xyz' : 'http://localhost:8080'"), 'Vite production proxy fallback must target canonical .xyz API');
  check(backendConfig.includes('domain: str = "app.boulderroller.xyz"'), 'Backend AuthSettings default SIWS domain must use canonical Portal host');
  check(backendConfig.includes('uri: str = "https://app.boulderroller.xyz"'), 'Backend AuthSettings default SIWS URI must use canonical Portal host');
  check(backendConfig.includes('os.getenv("AUTH_SIWS_DOMAIN", "app.boulderroller.xyz")'), 'Backend env fallback SIWS domain must use canonical Portal host');
  check(backendConfig.includes('os.getenv("AUTH_SIWS_URI", "https://app.boulderroller.xyz")'), 'Backend env fallback SIWS URI must use canonical Portal host');
  check(dockerCompose.includes('AUTH_SIWS_DOMAIN: ${AUTH_SIWS_DOMAIN:-app.boulderroller.xyz}'), 'docker-compose SIWS domain fallback must use canonical Portal host');
  check(dockerCompose.includes('AUTH_SIWS_URI: ${AUTH_SIWS_URI:-https://app.boulderroller.xyz}'), 'docker-compose SIWS URI fallback must use canonical Portal host');
  check(caddyConfig.includes('api.boulderroller.org') && caddyConfig.includes('redir https://api.boulderroller.xyz{uri} permanent'), 'Caddyfile must preserve legacy API redirect to canonical .xyz API');
  check(caddyConfig.includes('api.boulderroller.xyz') && caddyConfig.includes('reverse_proxy api:8080'), 'Caddyfile must reverse proxy canonical API host to backend API service');
}

async function checkRideStateVocabulary() {
  const qa = await readJson('qa/portal-qa-readiness.json');
  const protocolStates = await readText('src/lib/protocolStates.ts');
  const rideView = await readText('src/pages/RideViewCore.tsx');
  const expectedLabels = ['Counting', 'Finalized', 'Needs review', 'Not counted'];
  const observedLabels = qa.rideProofStates.map((state) => state.label);

  check(qa.contractVersion === 'portal.qa.v1', 'QA readiness fixture must be versioned as portal.qa.v1');
  check(qa.liveTargets.portal === 'https://app.boulderroller.xyz', 'QA fixture must name the canonical Portal host');
  check(qa.liveTargets.backend === 'https://api.boulderroller.xyz', 'QA fixture must name the canonical backend host');
  check(qa.smokeSurfaces.length >= 6, 'QA fixture must cover the core Portal smoke surfaces');
  check(JSON.stringify(observedLabels) === JSON.stringify(expectedLabels), 'Ride proof state labels must match the canonical rider-facing order');

  const states = await import('../src/lib/protocolStates.ts');
  check(JSON.stringify(states.SUBJECT_STATE_LABELS) === JSON.stringify(expectedLabels), 'Per-subject canonical labels must retain the approved set without Stamped');
  check(JSON.stringify(states.STATE_SUBJECTS) === JSON.stringify(qa.stateSubjects), 'State subjects must be storage, matching/result, CAL, position, collection');
  const projection = Object.fromEntries(qa.stateSubjects.map((subject) => [subject, { state: 'needs_review', reason: 'fixture_reason' }]));
  const rows = states.readSubjectStates(projection);
  check(rows.length === 5 && new Set(rows.map((row) => row.subject)).size === 5, 'Each supported subject must have exactly one state');
  check(rows.every((row) => row.label === 'Needs review' && row.reason === 'fixture_reason'), 'Subject state and known reason must remain attached');
  for (const subject of qa.stateSubjects) {
    const partial = { ...projection };
    delete partial[subject];
    const remaining = states.readSubjectStates(partial);
    check(remaining.length === 4 && !remaining.some((row) => row.subject === subject), 'Missing subject must not inherit another subject state');
  }
  check(states.readSubjectStates({ status: 'finalized', finalizedAt: '2026-09-08' }).length === 0, 'Generic ride state must not establish subject finality');
  check(states.readSubjectStates({ storage: { state: 'saved' }, cal: { state: 'held' }, collection: { state: 'stamped' } }).length === 1, 'Unsupported words must abstain without a fallback');
  check(states.readSubjectStates({ storage: [{ state: 'saved' }, { state: 'finalized' }] }).length === 0, 'A subject cannot render a ladder');

  assertContains(rideView, 'value={proof.uiStateLabel}', 'RideView proof card');
  assertContains(rideView, "proof.thresholdEconomyState === 'held'", 'RideView proof card');
  assertContains(rideView, "'Held — clears when your Threshold is established.'", 'RideView proof card');
  assertContains(rideView, ': proof.uiStateDetail}', 'RideView proof card');
  assertContains(rideView, 'Evidence source:', 'RideView proof card');
  assertContains(rideView, 'Technical source details', 'RideView proof card');

  const technicalIndex = rideView.indexOf('Technical source details');
  for (const technicalLabel of qa.sourceDisplayPolicy.technicalOnly) {
    const renderedLabel = technicalLabel === 'Source diagnostics'
      ? technicalLabel
      : `label="${technicalLabel}"`;
    const labelIndex = rideView.indexOf(renderedLabel);
    check(labelIndex > technicalIndex, `${technicalLabel} must stay behind Technical source details`);
  }
}

async function checkClientContractFixture() {
  const fixture = JSON.parse(await readRepoText('backend/tests/fixtures/client_v1/ride_status_response.json'));
  const apiTypes = await readText('src/lib/api.ts');

  check(fixture.contract_version === 'client.v1', 'Backend ride status fixture must remain client.v1');
  check(fixture.truth_source === 'attested', 'Backend ride status fixture must keep attested truth source');
  check(Boolean(fixture.ride_hash_hex), 'Backend ride status fixture must include ride_hash_hex');
  check(Boolean(fixture.ride_attestation_pda), 'Backend ride status fixture must include ride_attestation_pda');
  check(Boolean(fixture.earnings), 'Backend ride status fixture must include earnings');

  for (const field of ['importSource', 'importSourceId', 'importDiagnostics']) {
    assertContains(apiTypes, field, 'Portal client API types');
  }
}

async function checkOptionalLiveTarget() {
  const qa = await readJson('qa/portal-qa-readiness.json');
  const liveRequested = process.env.PORTAL_QA_LIVE === '1' || Boolean(process.env.PORTAL_QA_LIVE_URL);
  if (!liveRequested) return;

  const liveUrl = process.env.PORTAL_QA_LIVE_URL ?? qa.liveTargets.portal;
  const apiUrl = process.env.PORTAL_QA_API_URL ?? qa.liveTargets.backend;
  const healthPath = qa.liveTargets.healthPath ?? '/health';
  const corsProbePath = qa.liveTargets.corsProbePath ?? '/auth/bootstrap';
  const portalOrigin = new URL(liveUrl).origin;
  const apiOrigin = new URL(apiUrl).origin;

  const response = await fetch(liveUrl, { redirect: 'follow' });
  check(response.ok, `PORTAL_QA_LIVE_URL must return 2xx/3xx, got ${response.status}`);
  const body = await response.text();
  check(body.includes('<div id="root"></div>'), 'Live Portal response must look like the Vite app shell');

  const apiHealth = await fetch(new URL(healthPath, apiOrigin), { redirect: 'follow' });
  check(apiHealth.ok, `Canonical API health must return 2xx, got ${apiHealth.status}`);
  const apiHealthBody = await apiHealth.json().catch(() => null);
  check(apiHealthBody?.status === 'ok', 'Canonical API health must return { status: "ok" }');

  const facadeHealth = await fetch(new URL(`${qa.liveTargets.apiFacade}${healthPath}`, portalOrigin), { redirect: 'follow' });
  check(facadeHealth.ok, `Portal /api facade health must return 2xx, got ${facadeHealth.status}`);
  const facadeHealthBody = await facadeHealth.json().catch(() => null);
  check(facadeHealthBody?.status === 'ok', 'Portal /api facade health must return { status: "ok" }');

  for (const legacyApi of qa.liveTargets.legacyApiRedirects ?? []) {
    const legacyResponse = await fetch(new URL(healthPath, legacyApi), { redirect: 'manual' });
    const location = legacyResponse.headers.get('location');
    check([301, 308].includes(legacyResponse.status), `${legacyApi} must permanently redirect to canonical API`);
    check(location === new URL(healthPath, apiOrigin).toString(), `${legacyApi} must redirect health to canonical API health`);
  }

  const corsProbe = await fetch(new URL(corsProbePath, apiOrigin), {
    method: 'OPTIONS',
    headers: {
      Origin: portalOrigin,
      'Access-Control-Request-Method': 'GET',
    },
  });
  check(corsProbe.ok, `Canonical API CORS preflight must return 2xx, got ${corsProbe.status}`);
  check(corsProbe.headers.get('access-control-allow-origin') === portalOrigin, 'Canonical API CORS must allow canonical Portal origin');
  check(corsProbe.headers.get('access-control-allow-credentials') === 'true', 'Canonical API CORS must allow credentials for cookie auth');
}

await checkPortalConfig();
await checkRideStateVocabulary();
await checkClientContractFixture();
await checkOptionalLiveTarget();

if (failures.length > 0) {
  console.error('Portal QA readiness failed:');
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log('Portal QA readiness passed.');
