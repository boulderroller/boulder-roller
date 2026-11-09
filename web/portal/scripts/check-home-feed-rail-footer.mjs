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
  try {
    return await readFile(path.join(portalRoot, relativePath), 'utf8');
  } catch {
    failures.push(`${relativePath} must exist`);
    return '';
  }
}

const activityFeed = await readPortal('src/components/feed/ActivityFeedCore.tsx');
const portalShell = await readPortal('src/components/portal/PortalShell.tsx');
const utilityLinks = await readPortal('src/components/portal/PortalUtilityLinks.tsx');
const surfacesCss = await readPortal('src/styles/portal-surfaces.css');
const packageJson = JSON.parse(await readPortal('package.json'));

assertContains(activityFeed, "import { PortalUtilityLinks } from '../portal/PortalUtilityLinks';", 'Home feed');
assertContains(activityFeed, '<PortalUtilityLinks placement="rail" />', 'Home feed right rail');
assertContains(portalShell, "import { PortalUtilityLinks } from './PortalUtilityLinks';", 'Portal shell');
assertContains(portalShell, "location.pathname === '/' || location.pathname === '/dashboard'", 'Portal shell Home-route guard');
assertContains(portalShell, '<PortalUtilityLinks placement="account" onNavigate={closeActionMenus} />', 'Portal shell account menu');

assertContains(utilityLinks, 'https://docs.boulderroller.xyz/', 'Utility links');
assertContains(utilityLinks, '/settings?tab=privacy', 'Utility links');
assertContains(utilityLinks, '>Docs<', 'Utility links copy');
assertContains(utilityLinks, '>Privacy settings<', 'Utility links copy');
assertContains(utilityLinks, '© {formatFixed(currentYear, 0)} Boulder Roller', 'Desktop rail footer');
assertNotContains(utilityLinks, 'github.com', 'Utility links');
assertNotContains(utilityLinks, 'PortalPanel', 'Uncarded utility links');

assertContains(surfacesCss, '.feed-rail-footer {', 'Rail footer styles');
assertContains(surfacesCss, '.portal-account-utility-strip {', 'Collapsed utility strip styles');
assertContains(surfacesCss, 'min-height: 48px;', 'Collapsed utility strip styles');
assertContains(surfacesCss, '@media (width >= 64rem)', 'Rail-collapse breakpoint');

const railFooterStyles = surfacesCss.match(/\.feed-rail-footer\s*\{([^}]*)\}/)?.[1] ?? '';
check(!/position\s*:\s*(fixed|sticky)/.test(railFooterStyles), 'Rail footer must remain in normal rail flow');
const accountUtilityLinkStyles = surfacesCss.match(/\.portal-account-utility-strip \.portal-utility-links__link\s*\{([^}]*)\}/)?.[1] ?? '';
assertContains(accountUtilityLinkStyles, 'min-width: 44px;', 'Collapsed utility link hit area');
assertContains(accountUtilityLinkStyles, 'min-height: 44px;', 'Collapsed utility link hit area');
const copyrightStyles = surfacesCss.match(/\.feed-rail-footer__copyright\s*\{([^}]*)\}/)?.[1] ?? '';
assertContains(copyrightStyles, 'color: var(--portal-public-ink-muted);', 'Rail footer copyright contrast');

check(packageJson.scripts?.['qa:home-feed-footer'] === 'node scripts/check-home-feed-rail-footer.mjs', 'package.json must expose qa:home-feed-footer');
check(
  Boolean(packageJson.scripts?.['perf:release']?.includes('npm run qa:home-feed-footer')),
  'package.json perf:release must run the Home feed footer gate',
);

if (failures.length > 0) {
  console.error('Home feed rail footer gate failed:');
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log('Home feed rail footer gate passed.');
