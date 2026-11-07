const test = require('node:test');
const assert = require('node:assert/strict');
const { retryTransientRpc, transientRpcErrorClass } = require('../dist/rpc-retry.js');

test('RPC retry classification recognizes only the admitted transient failures, including nested transport causes', () => {
  for (const [error, expected] of [
    [new Error('429 Too Many Requests: max usage reached'), 'rate_limit'],
    [new Error('max usage reached'), 'rate_limit'],
    [{ status: 429 }, 'rate_limit'],
    [new Error('failed to get accounts: Minimum context slot has not been reached'), 'minimum_context_slot'],
    [{ code: -32016 }, 'minimum_context_slot'],
    [new Error('HTTP 502 Bad Gateway'), 'http_5xx'],
    [new Error('failed to fetch: 503 Service Unavailable: upstream'), 'http_5xx'],
    [new Error('599 : provider unavailable'), 'http_5xx'],
    [{ response: { status: 500 } }, 'http_5xx'],
    [new Error('request timed out'), 'timeout'],
    [{ name: 'TimeoutError' }, 'timeout'],
    [new TypeError('fetch failed', { cause: { code: 'UND_ERR_CONNECT_TIMEOUT' } }), 'timeout'],
    [new Error('socket hang up'), 'connection_reset'],
    [new TypeError('fetch failed', { cause: { code: 'ECONNRESET' } }), 'connection_reset'],
    [new Error('401 Unauthorized'), null],
    [new Error('403 Forbidden'), null],
    [new Error('Invalid param'), null],
    [new Error('decode expected 503 bytes'), null],
    [new Error('ProgramConfig version mismatch'), null],
    [new Error('ProgramConfig PDA is not owned by the configured program'), null],
    [new Error('fetch failed'), null],
    [{ code: 'ENOTFOUND' }, null],
    [null, null],
  ]) assert.equal(transientRpcErrorClass(error), expected, String(error));
});

function clock(t, random = 0) {
  let elapsed = 0;
  const waits = [];
  const warnings = [];
  t.mock.method(Date, 'now', () => elapsed);
  t.mock.method(Math, 'random', () => random);
  t.mock.method(global, 'setTimeout', (callback, delay) => {
    waits.push(delay);
    elapsed += delay;
    queueMicrotask(callback);
  });
  t.mock.method(console, 'warn', (message) => warnings.push(message));
  return { waits, warnings, now: () => elapsed, advance: (ms) => { elapsed += ms; } };
}

test('RPC retry preserves success with no extra reads or waits', async (t) => {
  const state = clock(t);
  let reads = 0;
  const expected = {};
  const result = await retryTransientRpc(async () => { reads++; return expected; }, { label: 'test', deadline: 60_000 });
  assert.equal(result, expected);
  assert.equal(reads, 1);
  assert.deepEqual(state.waits, []);
});

test('RPC retry recovers a timeout and logs its class once without endpoint credentials', async (t) => {
  const state = clock(t, 0.5);
  let reads = 0;
  const result = await retryTransientRpc(async () => {
    if (++reads === 1) throw new Error('request timed out: https://rpc.example/secret?api-key=secret');
    return 'recovered';
  }, { label: 'test', deadline: 60_000 });
  assert.equal(result, 'recovered');
  assert.equal(reads, 2);
  assert.deepEqual(state.waits, [750]);
  assert.equal(state.warnings.length, 1);
  assert.match(state.warnings[0], /timeout/);
  assert.doesNotMatch(state.warnings[0], /secret|rpc\.example/);
});

test('RPC retry caps exponential jitter and stops at its deadline with the original error', async (t) => {
  const state = clock(t);
  const failure = new Error('500 Internal Server Error');
  let reads = 0;
  await assert.rejects(retryTransientRpc(async () => {
    reads++;
    throw failure;
  }, { label: 'test', deadline: 60_000 }), (error) => error === failure);
  assert.deepEqual(state.waits, [500, 1000, 2000, 4000, 8000, 15000, 15000, 14500]);
  assert.equal(state.now(), 60_000);
  assert.equal(reads, state.waits.length);
  assert.equal(state.warnings.length, state.waits.length);
});

test('RPC retry includes time spent in the request and does not read again after the deadline', async (t) => {
  const state = clock(t);
  const failure = Object.assign(new Error('read failed'), { code: 'ECONNRESET' });
  let reads = 0;
  await assert.rejects(retryTransientRpc(async () => {
    reads++;
    state.advance(90);
    throw failure;
  }, { label: 'test', deadline: 100 }), (error) => error === failure);
  assert.equal(reads, 1);
  assert.deepEqual(state.waits, [10]);
  assert.equal(state.now(), 100);
});

test('RPC retry throws a permanent error immediately without logging a wait', async (t) => {
  const state = clock(t);
  const failure = new Error('Invalid param');
  let reads = 0;
  await assert.rejects(retryTransientRpc(async () => { reads++; throw failure; }, {
    label: 'test', deadline: 60_000,
  }), (error) => error === failure);
  assert.equal(reads, 1);
  assert.deepEqual(state.waits, []);
  assert.deepEqual(state.warnings, []);
});
