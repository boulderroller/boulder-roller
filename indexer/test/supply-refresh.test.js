const test = require('node:test');
const assert = require('node:assert/strict');

const {
  MAX_DUNG_SUPPLY_STALE_MS,
  requireBoundedDungSupplyRefreshInterval,
  startDungSupplyRefreshLoop,
} = require('../dist/supply-refresh.js');

test('supply refresh configuration preserves a one-minute stale-detection margin', () => {
  assert.equal(requireBoundedDungSupplyRefreshInterval(240_000), 240_000);
  assert.throws(
    () => requireBoundedDungSupplyRefreshInterval(240_001),
    /no greater than 240000 ms/
  );
  assert.throws(
    () => requireBoundedDungSupplyRefreshInterval(0),
    /positive integer/
  );
});

test('periodic supply refresh repairs a missed callback while the stream remains connected', async () => {
  let scheduledCallback = null;
  let scheduledIntervalMs = null;
  let projectedSupply = '100';
  const streamState = { connected: true };

  const loop = startDungSupplyRefreshLoop({
    intervalMs: 240_000,
    refresh: async () => {
      projectedSupply = '125';
      return { amount: projectedSupply, slot: 20, written: true };
    },
    schedule: (callback, intervalMs) => {
      scheduledCallback = callback;
      scheduledIntervalMs = intervalMs;
      return { unref() {} };
    },
    cancel: () => {},
    logger: { log() {}, warn() {}, error() {} },
  });

  assert.equal(streamState.connected, true);
  assert.equal(projectedSupply, '100');
  assert.equal(scheduledIntervalMs, 240_000);
  assert.ok(scheduledIntervalMs < MAX_DUNG_SUPPLY_STALE_MS);

  await scheduledCallback();

  assert.equal(streamState.connected, true);
  assert.equal(projectedSupply, '125');
  loop.stop();
});

test('periodic supply refresh shares an in-flight RPC observation', async () => {
  let releaseRefresh;
  let refreshCalls = 0;
  const refresh = new Promise((resolve) => {
    releaseRefresh = resolve;
  });

  const loop = startDungSupplyRefreshLoop({
    intervalMs: 240_000,
    refresh: async () => {
      refreshCalls += 1;
      await refresh;
      return { amount: '125', slot: 20, written: true };
    },
    schedule: () => ({ unref() {} }),
    cancel: () => {},
    logger: { log() {}, warn() {}, error() {} },
  });

  const first = loop.runNow();
  const second = loop.runNow();
  assert.equal(refreshCalls, 1);

  releaseRefresh();
  assert.deepEqual(await first, await second);
  loop.stop();
});
