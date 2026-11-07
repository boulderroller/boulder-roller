const test = require('node:test');
const assert = require('node:assert/strict');

const {
  buildIndexerHealthPayload,
  indexerHealthStatusCode,
} = require('../dist/health.js');

const SUCCESSFUL_SNAPSHOT = {
  status: 'succeeded',
  total: 16,
  indexed: 16,
  skipped: 0,
  decode_failures: 0,
  write_failures: 0,
  fetch_failures: 0,
  started_at: '2026-05-04T01:07:00.000Z',
  completed_at: '2026-05-04T01:07:30.000Z',
  error: null,
};

test('health payload marks stale slots lagging when stream and replay are stale', () => {
  const payload = buildIndexerHealthPayload(
    {
      last_account_slot: 100,
      last_tx_slot: 295,
      last_account_sync_at: '2026-04-24T17:11:06.260Z',
      last_tx_sync_at: '2026-05-01T21:01:23.582Z',
      stream_connected: false,
    },
    300,
    new Date('2026-05-04T01:08:03.175Z'),
    SUCCESSFUL_SNAPSHOT
  );

  assert.equal(payload.status, 'lagging');
  assert.equal(payload.lag_slots, 200);
  assert.equal(payload.account_lag_slots, 200);
  assert.equal(payload.tx_lag_slots, 5);
  assert.equal(payload.stream_connected, false);
});

test('health payload stays ok during idle periods when stream is connected and replay checked recently', () => {
  const payload = buildIndexerHealthPayload(
    {
      last_account_slot: 100,
      last_tx_slot: 295,
      last_account_sync_at: '2026-04-24T17:11:06.260Z',
      last_tx_sync_at: '2026-05-04T01:03:03.175Z',
      stream_connected: true,
    },
    300,
    new Date('2026-05-04T01:08:03.175Z'),
    SUCCESSFUL_SNAPSHOT
  );

  assert.equal(payload.status, 'ok');
  assert.equal(payload.lag_slots, 200);
  assert.equal(payload.account_lag_slots, 200);
  assert.equal(payload.tx_lag_slots, 5);
  assert.equal(payload.stream_connected, true);
});

test('health detects stale DUNG supply even while the stream remains connected', () => {
  const payload = buildIndexerHealthPayload(
    {
      last_account_slot: 1000,
      last_tx_slot: 995,
      last_tx_sync_at: '2026-05-04T01:07:30.000Z',
      stream_connected: true,
    },
    1010,
    new Date('2026-05-04T01:08:03.175Z'),
    SUCCESSFUL_SNAPSHOT,
    {
      spl_mint_supply: '125',
      spl_mint_supply_slot: '990',
      spl_mint_supply_indexed_at: '2026-05-04T01:02:00.000Z',
    }
  );

  assert.equal(payload.stream_connected, true);
  assert.equal(payload.supply.status, 'stale');
  assert.equal(payload.supply.amount, '125');
  assert.equal(payload.supply.slot, 990);
  assert.equal(payload.supply.max_stale_ms, 300_000);
  assert.ok(payload.supply.age_ms > payload.supply.max_stale_ms);
  assert.equal(payload.status, 'lagging');
  assert.equal(indexerHealthStatusCode(payload), 503);
});

test('health payload stays ok when account and transaction cursors are fresh', () => {
  const payload = buildIndexerHealthPayload(
    {
      last_account_slot: 1000,
      last_tx_slot: 995,
      stream_connected: true,
    },
    1010,
    new Date('2026-05-04T01:08:03.175Z'),
    SUCCESSFUL_SNAPSHOT
  );

  assert.equal(payload.status, 'ok');
  assert.equal(payload.lag_slots, 15);
  assert.equal(payload.account_lag_slots, 10);
  assert.equal(payload.tx_lag_slots, 15);
});

test('health remains unavailable while the initial snapshot is running', () => {
  const payload = buildIndexerHealthPayload(
    { last_account_slot: 1000, last_tx_slot: 995, stream_connected: true },
    1010,
    new Date('2026-05-04T01:08:03.175Z'),
    { ...SUCCESSFUL_SNAPSHOT, status: 'running', completed_at: null }
  );

  assert.equal(payload.status, 'starting');
  assert.equal(payload.snapshot.status, 'running');
  assert.equal(indexerHealthStatusCode(payload), 503);
});

test('health fails closed when the snapshot records a writer failure', () => {
  const payload = buildIndexerHealthPayload(
    { last_account_slot: 1000, last_tx_slot: 995, stream_connected: true },
    1010,
    new Date('2026-05-04T01:08:03.175Z'),
    {
      ...SUCCESSFUL_SNAPSHOT,
      status: 'failed',
      indexed: 15,
      write_failures: 1,
      error: 'LocalLegend writer failed',
    }
  );

  assert.equal(payload.status, 'error');
  assert.equal(payload.snapshot.write_failures, 1);
  assert.equal(indexerHealthStatusCode(payload), 503);
});
