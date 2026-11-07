import { resolveRankMarkAsset } from '../../assets/rankmarks';
import { formatInteger } from '../../lib/formatters';

export const RANK_MARK_DEFAULT_SIZE = 36;

export interface RankMarkProps {
  rank: number;
  size?: number;
}

/**
 * Asset-only rank display primitive. The baked sprite owns the complete look;
 * under the ratified tab codex the mark's state derives from rank alone.
 */
export function RankMark({ rank, size = RANK_MARK_DEFAULT_SIZE }: RankMarkProps) {
  const asset = resolveRankMarkAsset(rank);
  const validSize = Number.isFinite(size) && size > 0;

  if (!asset || !validSize) {
    if (import.meta.env.DEV) {
      console.warn(`RankMark received invalid input: rank=${rank}, size=${size}`);
    }
    return null;
  }

  return (
    <img
      src={asset.src}
      srcSet={asset.srcSet}
      width={size}
      height={size}
      alt={`Rank ${formatInteger(rank)}`}
    />
  );
}
