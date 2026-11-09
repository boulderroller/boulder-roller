import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(
  process.env.EYEBROW_REPO_ROOT || path.join(scriptDirectory, '../../..'),
);
const sourceRoot = path.join(repositoryRoot, 'web/portal/src');

const forbiddenSelectors = [
  'portal-page-hero__kicker',
  'wallet-connect-progress-card__eyebrow',
  'wallet-connect-select__group-eyebrow',
  'wallet-connect-other__eyebrow',
  'ride-detail-climbs-profile__eyebrow',
  'public-preview-hero__object',
  'climb-detail-hero__meta',
  'ride-detail-overview__context-kicker',
  'vault-match-panel__eyebrow',
  'vault-creation-cta__eyebrow',
];

const placementContracts = [
  {
    file: 'pages/AdminDashboard.tsx',
    markers: ['<HealthBanner', 'status={(', '<PortalTruthPill tone={healthLabel'],
  },
  {
    file: 'pages/DataCore.tsx',
    markers: ['className="training-load__footer"', "<PortalTruthPill tone={trainingError && fitnessMetrics ? 'warning' : thresholdPending ? 'warning' : 'muted'}>"],
  },
  {
    file: 'pages/Docs.tsx',
    // The docs' contents page (2026-09-03): the page's name, then one gray word to the site.
    markers: ['className="guide__header"', 'className="guide__title"', 'className="guide__word"'],
  },
  {
    file: 'pages/FindFriends.tsx',
    markers: ['title="Find riders"', 'portal-panel__meta-cluster', '<PortalTruthPill tone="verified">Live search</PortalTruthPill>'],
  },
  {
    file: 'pages/Notifications.tsx',
    // The consequence ledger (2026-09-03): the count is data beside the title, the words are gray.
    markers: ['className="notifications-log__header"', 'className="notifications-log__count"', 'className="notifications-log__word"'],
  },
  {
    file: 'pages/Portfolio.tsx',
    // 24xry.25: Tim permits only this Portfolio contract to retire the footer.
    markers: await (async () => {
      const markers = [
        '<span className="profile-eyebrow"><span>Wallet</span><span className="portfolio-sheet__meta"> · {error || tokenSnapshotError ? \'Last loaded\' : \'Current\'}</span></span>',
        '<span className="profile-eyebrow"><span>Positions</span><span className="portfolio-sheet__meta"> · {error ? \'Paused\' : \'Current\'}</span></span>',
      ];
      const content = await readFile(path.join(sourceRoot, 'pages/Portfolio.tsx'), 'utf8');
      for (const marker of markers) {
        const expression = marker.slice(marker.indexOf('{'), marker.indexOf('}') + 1);
        if (content.split(marker).length !== 2 || content.split(expression).length !== 2) {
          throw new Error(`Portfolio truth must appear exactly once as trailing eyebrow meta: ${marker}`);
        }
      }
      const css = await readFile(path.join(sourceRoot, 'styles/portal-portfolio-page.css'), 'utf8');
      if (css.includes('portal-page-hero__status-footer')) {
        throw new Error('Portfolio CSS retains the retired status-footer selector');
      }
      return markers;
    })(),
    forbidden: ['portal-page-hero__status-footer', 'PortalTruthPill'],
  },
  {
    file: 'pages/Settings.tsx',
    markers: ['className="settings-v2-actions__status"', '<PortalTruthPill tone={hasUnsavedChanges'],
  },
  {
    file: 'pages/VaultView.tsx',
    markers: ['<h3>Your position</h3>', 'vault.onChainActive === true', 'Deposits open when the climb is ready.'],
  },
  {
    file: 'components/climb/ClimbLeaderboard.tsx',
    markers: ['className="climb-section-heading"', '<h2>Leaderboard</h2>', 'className="climb-metric-picker"'],
    forbidden: ['All-time top 10', 'Ranked by time. Names use public profiles only.'],
  },
  {
    file: 'pages/PublicPreview.tsx',
    markers: ['<RidePageIdentity', '<ClimbIdentity', '<ProfileLedgerColumn'],
    forbidden: ['public-preview-hero__object', 'MetricTile', 'PreviewStat'],
  },
  {
    file: 'components/auth/WalletConnect.tsx',
    markers: ['role="group"', 'aria-label="Detected Solana wallets"'],
  },
];

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const absolutePath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...await sourceFiles(absolutePath));
    } else if (/\.(css|ts|tsx)$/.test(entry.name)) {
      files.push(absolutePath);
    }
  }

  return files;
}

function assertOrdered(content, markers, label, failures) {
  let cursor = -1;
  for (const marker of markers) {
    const next = content.indexOf(marker, cursor + 1);
    if (next === -1) {
      failures.push(`${label}: missing or misplaced ${JSON.stringify(marker)}`);
      return;
    }
    cursor = next;
  }
}

const failures = [];
const files = await sourceFiles(sourceRoot);

for (const file of files) {
  const content = await readFile(file, 'utf8');
  for (const selector of forbiddenSelectors) {
    if (content.includes(selector)) {
      failures.push(`${path.relative(repositoryRoot, file)}: forbidden eyebrow selector ${selector}`);
    }
  }
}

for (const contract of placementContracts) {
  const file = path.join(sourceRoot, contract.file);
  const content = await readFile(file, 'utf8');
  assertOrdered(content, contract.markers, contract.file, failures);
  for (const marker of contract.forbidden ?? []) {
    if (content.includes(marker)) failures.push(`${contract.file}: removed Climb v2 label ${JSON.stringify(marker)}`);
  }
}

if (failures.length > 0) {
  console.error('Portal eyebrow elimination gate failed:');
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log(`Portal eyebrow elimination gate passed: ${forbiddenSelectors.length} deleted selectors and ${placementContracts.length} semantic-placement contracts.`);
