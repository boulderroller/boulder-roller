const test = require('node:test');
const assert = require('node:assert/strict');
const { PublicKey } = require('@solana/web3.js');

const { projectLeaderboardEntries } = require('../dist/writers/leaderboard.js');

function rider(value) {
  return new PublicKey(Buffer.alloc(32, value));
}

test('projects standard competition ranks and tie metadata', () => {
  const projected = projectLeaderboardEntries([
    { user: rider(1), timeS: 100, recordedAt: 10n },
    { user: rider(2), timeS: 120, recordedAt: 20n },
    { user: rider(3), timeS: 120, recordedAt: 30n },
    { user: rider(4), timeS: 140, recordedAt: 40n },
  ]);

  assert.deepEqual(
    projected.map(({ position, rank, tie_size, is_tied }) => ({
      position,
      rank,
      tie_size,
      is_tied,
    })),
    [
      { position: 1, rank: 1, tie_size: 1, is_tied: false },
      { position: 2, rank: 2, tie_size: 2, is_tied: true },
      { position: 3, rank: 2, tie_size: 2, is_tied: true },
      { position: 4, rank: 4, tie_size: 1, is_tied: false },
    ]
  );
});
