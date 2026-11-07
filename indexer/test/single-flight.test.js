const test = require('node:test');
const assert = require('node:assert/strict');

const { singleFlight } = require('../dist/single-flight.js');

test('singleFlight coalesces overlapping work and releases after completion', async () => {
  let calls = 0;
  let finish;
  const run = singleFlight(() => {
    calls++;
    return new Promise((resolve) => {
      finish = resolve;
    });
  });

  const first = run();
  const overlapping = run();

  assert.equal(first, overlapping);
  assert.equal(calls, 1);

  finish({ processed: 2, events: 3 });
  assert.deepEqual(await first, { processed: 2, events: 3 });
  assert.deepEqual(await overlapping, { processed: 2, events: 3 });

  const next = run();
  assert.equal(calls, 2);
  finish({ processed: 0, events: 0 });
  await next;
});

test('singleFlight releases after an operation throws synchronously', async () => {
  let calls = 0;
  const run = singleFlight(() => {
    calls++;
    if (calls === 1) throw new Error('sync failure');
    return Promise.resolve('recovered');
  });

  await assert.rejects(run(), /sync failure/);
  assert.equal(await run(), 'recovered');
  assert.equal(calls, 2);
});
