require('../dist/program-version-window.js').programVersionWindow.observe(0x4d);
const test = require('node:test');
const { mockProgramVersionStore } = require('./helpers/program-version-store.js');
test.beforeEach(mockProgramVersionStore);
const assert = require('node:assert/strict');
const fs = require('node:fs');
const crypto = require('node:crypto');
const { BorshCoder, BN } = require('@coral-xyz/anchor');
const { PublicKey } = require('@solana/web3.js');
const { config } = require('../dist/config');
const { decodeEvents } = require('../dist/decoder');
const { serializeEventFields } = require('../dist/modes/replay');
const { handleApiRequest, setApiRuntimeForTests, resetApiRuntimeForTests } = require('../dist/api');
const idl = JSON.parse(fs.readFileSync(config.idlPath, 'utf8'));
const coder = new BorshCoder(idl);
const signature = '3'.repeat(88);
const wallet = new PublicKey(Buffer.alloc(32, 2)).toBase58();
const hash = 'ab'.repeat(32);
const proofId = '11111111-1111-4111-8111-111111111111';
const snake = name => name.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase();
function sample(type) {
  if (type === 'publicKey') return [new PublicKey(wallet), wallet];
  if (type === 'u64' || type === 'i64' || type === 'u128') return [new BN('9007199254740993'), '9007199254740993'];
  if (type === 'bool') return [false, false];
  if (typeof type === 'string') return [0, 0];
  if (type.array) {
    if (type.array[0] === 'u8') return [Array(type.array[1]).fill(171), 'ab'.repeat(type.array[1])];
    const values = Array.from({length: type.array[1]}, () => sample(type.array[0]));
    return [values.map(([value]) => value), values.map(([, json]) => json)];
  }
  if (type.defined) {
    const def = idl.types.find(t => t.name === type.defined);
    if (def.type.kind === 'struct') {
      const values = def.type.fields.map(field => [field.name, sample(field.type)]);
      return [Object.fromEntries(values.map(([name, [value]]) => [name, value])),
        Object.fromEntries(values.map(([name, [, json]]) => [name, json]))];
    }
    const name = def.type.variants[0].name;
    const value = { [name[0].toLowerCase() + name.slice(1)]: {} };
    return [value, value];
  }
  throw new Error(`Uncovered IDL type: ${JSON.stringify(type)}`);
}
async function request(path, query) {
  setApiRuntimeForTests({ query, getRpcConnection: () => ({
    getGenesisHash: async () => 'unit-genesis',
    getAccountInfoAndContext: async () => {
      const data = Buffer.alloc(334);
      crypto.createHash('sha256').update('account:ProgramConfig').digest().subarray(0, 8).copy(data);
      data[72] = 0x4d; data[73] = 1;
      new PublicKey(config.dungMintAddress).toBuffer().copy(data, 107);
      return { context: { slot: 700 }, value: { data, owner: new PublicKey(config.programId) } };
    },
  }) });
  const res = { statusCode: 0, body: '', writeHead(s) { this.statusCode = s; }, end(b) { this.body = b; } };
  await handleApiRequest({ url: path, method: 'GET', headers: {} }, res);
  return { status: res.statusCode, body: JSON.parse(res.body) };
}
function transactionQuery(events) {
  return async sql => {
    if (sql.includes('FROM indexed_transactions')) return { rows: [{ signature, status: 'success', instruction_index: 0, instruction_name: 'fixture', instruction_accounts: { rider: { pubkey: wallet, isSigner: true, isMut: true } } }] };
    if (sql.includes('FROM indexed_events')) return { rows: events };
    if (sql.includes('indexer_sync_state')) return { rows: [] };
    if (sql.includes("transaction-room:")) return {rows:[]};
    throw new Error(`Unexpected SQL: ${sql}`);
  };
}
test.afterEach(resetApiRuntimeForTests);
for (const event of idl.events) {
  test(`transaction decodes indexed ${event.name} fields from Borsh logs`, async () => {
    const data = {}, expected = [];
    for (const field of event.fields) {
      const [value, json] = sample(field.type);
      data[field.name] = value;
      expected.push({ name: snake(field.name), type: field.type, value: json });
    }
    const buffer = Buffer.alloc(4096);
    const len = coder.events.layouts.get(event.name).encode(data, buffer);
    const disc = crypto.createHash('sha256').update(`event:${event.name}`).digest().subarray(0, 8);
    const log = Buffer.concat([disc, buffer.subarray(0, len)]).toString('base64');
    const [decoded] = decodeEvents([`Program ${config.programId} invoke [1]`, `Program data: ${log}`, `Program ${config.programId} success`]);
    assert.equal(decoded.name, event.name);
    const fields = serializeEventFields(decoded.data);
    const result = await request(`/v1/transactions/${signature}`, transactionQuery([{ event_name: event.name, fields, event_index: 0 }]));
    assert.equal(result.status, 200);
    assert.deepEqual(result.body.events[0].decoded_fields, expected);
    assert.deepEqual(result.body.events[0].fields, Object.fromEntries(event.fields.map((f, i) => [f.name, expected[i].value])));
  });
}
test('settlement links only recorded allocations for the same climb and week, preserving zero and precision', async () => {
  const events = [
    { event_name: 'EpochRewardsDistributed', fields: { vaultId: '12', epoch: '14', totalDistributed: '9007199254740993' } },
    { event_name: 'StakerAllocation', fields: { vaultId: '12', epoch: '14', staker: wallet, amount: '9007199254740993' }, event_index: 1 },
    { event_name: 'StakerAllocation', fields: { vaultId: '12', epoch: '14', staker: wallet, amount: '0' }, event_index: 2 },
    { event_name: 'StakerAllocation', fields: { vaultId: '13', epoch: '14', staker: wallet, amount: '9' } },
    { event_name: 'StakerAllocation', fields: { vaultId: '12', epoch: '15', staker: wallet, amount: '9' } },
  ];
  const { body } = await request(`/v1/transactions/${signature}`, transactionQuery(events));
  assert.deepEqual(body.events[0].position_allocations, [
    { event_index: 1, wallet, dung_atomic: '9007199254740993' },
    { event_index: 2, wallet, dung_atomic: '0' },
  ]);
});
test('missing fields stay absent and historical snake_case fields keep IDL types', async () => {
  const { body } = await request(`/v1/transactions/${signature}`, transactionQuery([{ event_name: 'ClimbCompleted', fields: { time_s: 0, is_new_kom: false, cal_tributed: null } }]));
  assert.deepEqual(body.events[0].decoded_fields, [
    { name: 'time_s', type: 'u32', value: 0 },
    { name: 'is_new_kom', type: 'bool', value: false },
  ]);
});
for (const id of [proofId, hash, wallet]) {
  test(`proof resolver returns only an attestation signature for ${id.length}-character id`, async () => {
    const { status, body } = await request(`/v1/proofs/${id}`, async (sql, params) => {
      assert.ok(params.includes(id));
      assert.match(sql, /RideAttestationRecorded/);
      assert.match(sql, /status = 'success'/);
      if (id === proofId) {
        assert.match(sql, /FROM proofs/);
        assert.match(sql, /ride_attestation_tx_signature/);
        assert.doesNotMatch(sql, /p\.signature/);
      }
      return { rows: [{ signature }] };
    });
    assert.equal(status, 200);
    assert.deepEqual(body, { signature });
  });
}
test('proof resolver returns not found without an indexed successful attestation', async () => {
  const result = await request(`/v1/proofs/${proofId}`, async () => ({ rows: [] }));
  assert.equal(result.status, 404);
});
test('ambiguous ride hash does not redirect to an arbitrary rider', async () => {
  const result = await request(`/v1/proofs/${hash}`, async () => ({ rows: [{ signature }, { signature: '4'.repeat(88) }] }));
  assert.equal(result.status, 404);
});
test('unsupported proof ids return not found without querying', async () => {
  const result = await request('/v1/proofs/1', async () => { throw new Error('must not query'); });
  assert.equal(result.status, 404);
});
test('historically flattened enums are absent from decoded fields instead of presented as decoded values', async () => {
  const { body } = await request(`/v1/transactions/${signature}`, transactionQuery([{ event_name: 'ClimbRegistered', fields: { canonVersion: 3, recordContinuityPolicy: '[object Object]' } }]));
  assert.deepEqual(body.events[0].decoded_fields, [{ name: 'canon_version', type: 'u16', value: 3 }]);
  assert.equal(body.events[0].fields.recordContinuityPolicy, '[object Object]');
});
