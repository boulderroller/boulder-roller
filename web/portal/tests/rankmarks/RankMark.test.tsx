import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  type RankMarkAsset,
  rankMarkAssets,
  resolveRankMarkAsset,
} from '../../src/assets/rankmarks';
import {
  RANK_MARK_DEFAULT_SIZE,
  RankMark,
} from '../../src/components/rankmarks/RankMark';

// The portal package is intentionally untouched in this additive lane. Run from
// web/portal with the repository-locked runner installed by `npm ci` in web/scan:
// ../scan/node_modules/.bin/vitest run tests/rankmarks/RankMark.test.tsx --environment node

type Density = '1x' | '2x' | '3x';

interface NumberedRankManifest {
  tabs: string[] | 'FULL' | null;
  files: Record<Density | 'detail', string>;
}

interface PodiumRankManifest {
  files: Record<Density | 'detail', string>;
}

interface RankMarkManifest {
  codex: Record<string, unknown>;
  podium: {
    ranks: Record<string, PodiumRankManifest>;
  };
  ranks: Record<string, NumberedRankManifest>;
}

const densities: readonly Density[] = ['1x', '2x', '3x'];

const manifest = JSON.parse(
  readFileSync(
    new URL('../../../../tools/rankmarks/build/manifest.json', import.meta.url),
    'utf8',
  ),
) as RankMarkManifest;

afterEach(() => {
  vi.restoreAllMocks();
});

function expectDensityFiles(
  asset: RankMarkAsset | null,
  expected: Record<Density, string>,
) {
  expect(asset).not.toBeNull();
  expect(asset?.src).toContain(expected['1x']);

  const densityUrls = Object.fromEntries(
    (asset?.srcSet ?? '').split(', ').map((entry) => {
      const separator = entry.lastIndexOf(' ');
      return [entry.slice(separator + 1), entry.slice(0, separator)];
    }),
  ) as Record<Density, string>;

  expect(Object.keys(densityUrls)).toEqual(densities);
  for (const density of densities) {
    expect(densityUrls[density]).toContain(expected[density]);
  }
}

describe('rank-mark asset index', () => {
  it('resolves every manifest rank at every density', () => {
    expect(manifest.codex).toBeDefined();

    for (const rankKey of Object.keys(manifest.ranks)) {
      const rank = Number(rankKey);
      const files = manifest.ranks[rankKey].files;

      expectDensityFiles(resolveRankMarkAsset(rank), {
        '1x': files['1x'],
        '2x': files['2x'],
        '3x': files['3x'],
      });
    }
  });

  it('derives the tab state from rank alone under the ratified codex', () => {
    // Tab tier and band color are independent cycles. Halo thresholds
    // mapped descending: clean 50-45, one tab 44-36 rotating every 3,
    // two tabs 35-24, three tabs 23-12, full flood 11-4.
    expect(manifest.ranks['50'].tabs).toBeNull();
    expect(manifest.ranks['45'].tabs).toBeNull();
    expect(manifest.ranks['44'].tabs).toEqual(['TL']);
    expect(manifest.ranks['41'].tabs).toEqual(['TR']);
    expect(manifest.ranks['36'].tabs).toEqual(['BR']);
    expect(manifest.ranks['35'].tabs).toEqual(['TL', 'TR']);
    expect(manifest.ranks['24'].tabs).toEqual(['BL', 'TL']);
    expect(manifest.ranks['23'].tabs).toEqual(['TL', 'TR', 'BR']);
    expect(manifest.ranks['12'].tabs).toEqual(['BL', 'TL', 'TR']);
    expect(manifest.ranks['11'].tabs).toBe('FULL');
    expect(manifest.ranks['4'].tabs).toBe('FULL');
  });

  it('resolves the three podium sprites', () => {
    expect(Object.keys(manifest.podium.ranks)).toEqual(['1', '2', '3']);

    for (const rank of [1, 2, 3]) {
      const files = manifest.podium.ranks[String(rank)].files;

      expectDensityFiles(resolveRankMarkAsset(rank), {
        '1x': files['1x'],
        '2x': files['2x'],
        '3x': files['3x'],
      });
    }

    expect(resolveRankMarkAsset(1)?.src).toContain('rank01_crown@1x.png');
    expect(resolveRankMarkAsset(2)?.src).toContain('rank02_laurel@1x.png');
    expect(resolveRankMarkAsset(3)?.src).toContain('rank03_cobble@1x.png');
    expect(Object.keys(rankMarkAssets)).toHaveLength(50);
  });

  it('fails safe for ranks outside the contract', () => {
    for (const rank of [-1, 0, 51, 1.5, Number.NaN]) {
      expect(resolveRankMarkAsset(rank)).toBeNull();
    }
  });
});

describe('RankMark', () => {
  it('renders the sprite with density selection and an explicit pixel size', () => {
    const markup = renderToStaticMarkup(<RankMark rank={4} size={48} />);

    expect(markup).toContain('alt="Rank 4"');
    expect(markup).toContain('width="48"');
    expect(markup).toContain('height="48"');
    expect(markup).toMatch(/srcset="[^"]+ 1x, [^"]+ 2x, [^"]+ 3x"/i);
  });

  it('uses the 36px row default', () => {
    expect(RANK_MARK_DEFAULT_SIZE).toBe(36);

    const markup = renderToStaticMarkup(<RankMark rank={50} />);
    expect(markup).toContain('width="36"');
    expect(markup).toContain('height="36"');
  });

  it('returns null and warns in development for invalid input', () => {
    const warning = vi.spyOn(console, 'warn').mockImplementation(() => undefined);

    expect(renderToStaticMarkup(<RankMark rank={0} />)).toBe('');
    expect(renderToStaticMarkup(<RankMark rank={4} size={0} />)).toBe('');
    expect(warning).toHaveBeenCalledTimes(2);
  });
});
