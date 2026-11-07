import fs from 'fs';
import path from 'path';

const SRC_ROOT = path.resolve(__dirname, '../..');

const ALLOWED_IMPORTERS = new Set([
  'components/VerifyChip.tsx',
  'components/__tests__/verifyChipUsage.test.ts',
  'screens/PostRideScreen.tsx',
  'screens/WalletScreen.tsx',
]);

function walk(dir: string): string[] {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  return entries.flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return walk(full);
    if (/\.(ts|tsx)$/.test(entry.name)) return [full];
    return [];
  });
}

describe('VerifyChip usage', () => {
  test('stays limited to identity and attested-claim surfaces', () => {
    const offenders = walk(SRC_ROOT)
      .map((file) => ({
        file,
        relative: path.relative(SRC_ROOT, file),
        source: fs.readFileSync(file, 'utf8'),
      }))
      .filter(({ source }) => /from ['"]\.\.\/components\/VerifyChip['"]/.test(source))
      .filter(({ relative }) => !ALLOWED_IMPORTERS.has(relative))
      .map(({ relative }) => relative);

    expect(offenders).toEqual([]);
  });
});
