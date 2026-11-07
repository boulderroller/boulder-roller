import assert from 'node:assert/strict';
import { test } from 'node:test';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

// Exercise the real initializer with a local SDK double, without a browser or
// provider connection. TypeScript's importer is replaced at the SDK boundary.
async function hooks() {
  const options: any[] = [];
  let source = fs.readFileSync(new URL('../src/lib/sentry.ts', import.meta.url), 'utf8');
  source = source.replaceAll('import.meta.env', '({ VITE_SENTRY_DSN: "local-test", PROD: true, MODE: "test" })');
  source = source.replace("import('@sentry/react').catch", 'loadSDK().catch');
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const exports: any = {};
  const context = vm.createContext({
    exports,
    require: asyncRequire,
    loadSDK: async () => ({ init: (value: unknown) => options.push(value), captureException: () => {} }),
    setTimeout: (fn: () => void) => fn(),
  });
  function asyncRequire() { return privacyModule; }
  let privacyModule: unknown = {};
  // Before the fix there is no privacy module; the assertion below must fail
  // because Sentry.init has no hook, not because a proposed module is absent.
  const modulePath = new URL('../src/lib/sentryPrivacy.ts', import.meta.url);
  if (fs.existsSync(modulePath)) privacyModule = await import(modulePath.href);
  vm.runInContext(compiled, context);
  exports.scheduleSentryInit();
  await new Promise((resolve) => setImmediate(resolve));
  return options[0];
}

test('both Sentry event hooks remove personal data and keep diagnostic ids and frames', async () => {
  const options = await hooks();
  assert.equal(typeof options.beforeSend, 'function');
  assert.equal(typeof options.beforeSendTransaction, 'function');
  assert.equal(options.sendDefaultPii, false);
  const id = '11111111-1111-4111-8111-111111111111';
  const personal = { latitude: 40.123456, longitude: -79.987654, email: 'rider@example.test',
    wallet: '7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgEUx', token: 'secret-token', name: 'Private Rider' };
  for (const hook of [options.beforeSend, options.beforeSendTransaction]) {
    const event = { event_id: 'a'.repeat(32), user: { id, ...personal },
      request: { url: 'https://example.test/rides?token=secret-token', data: personal, headers: personal },
      extra: { ride_id: id, status_code: 503, payload: personal }, message: JSON.stringify(personal),
      exception: { values: [{ type: 'Error', value: JSON.stringify(personal), stacktrace: { frames: [
        { filename: 'app.js', function: 'upload', lineno: 20, vars: personal },
      ] } }] }, breadcrumbs: [{ message: JSON.stringify(personal), data: personal }],
      spans: [{ description: JSON.stringify(personal), data: personal }],
    };
    const result = hook(event, {});
    const encoded = JSON.stringify(result);
    for (const value of Object.values(personal)) assert.ok(!encoded.includes(String(value)));
    assert.equal(result.event_id, event.event_id);
    assert.equal(result.user.id, id);
    assert.deepEqual(result.extra, { ride_id: id, status_code: 503 });
    assert.equal(result.exception.values[0].stacktrace.frames[0].lineno, 20);
  }
});

test('scrubbing also protects code fields and source URLs while preserving span timing', async () => {
  const options = await hooks();
  const result = options.beforeSend({ extra: { code: 'secret-token' },
    exception: { values: [{ type: 'Error', mechanism: { handled: false, type: 'generic' }, stacktrace: { frames: [
      { filename: 'https://alice:secret-token@example.test/rider@example.test/app.js', lineno: 3 },
    ] } }] }, spans: [{ op: 'http.client', start_timestamp: 100, timestamp: 101 }],
    breadcrumbs: [{ category: 'http', timestamp: 100 }],
  });
  assert.ok(!JSON.stringify(result).includes('secret-token'));
  assert.ok(!JSON.stringify(result).includes('rider@example.test'));
  assert.equal(result.spans[0].start_timestamp, 100);
  assert.equal(result.spans[0].timestamp, 101);
  assert.equal(result.breadcrumbs[0].timestamp, 100);
  assert.equal(result.exception.values[0].mechanism.handled, false);
});

test('React component frames and ISO timestamps survive without prop values', async () => {
  const options = await hooks();
  const result = options.beforeSend({
    contexts: { react: { componentStack: '\n    at RideCard (https://example.test/src/RideCard.tsx?token=secret-token:12:3)\n    at App (name="Private Rider")' } },
    spans: [{ op: 'http.client', start_timestamp: '2026-10-20T12:00:00.000Z', timestamp: '2026-10-20T12:00:01Z' }],
  });
  assert.match(result.contexts.react.componentStack, /at RideCard/);
  assert.match(result.contexts.react.componentStack, /at App/);
  assert.ok(!JSON.stringify(result).includes('secret-token'));
  assert.ok(!JSON.stringify(result).includes('Private Rider'));
  assert.equal(result.spans[0].timestamp, '2026-10-20T12:00:01Z');
});
