import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { Buffer } from 'buffer';
import { PublicKey, Transaction, VersionedTransaction, AddressLookupTableAccount } from '@solana/web3.js';

import type { PreparedVaultTransaction } from '../src/lib/api.ts';
import {
  PreparedTransactionIntentError,
  validateStage1VersionedTransaction,
  validateAndSignStage1VersionedTransactionBytes,
  validateAndSignPreparedTransaction,
  validateAndSignPreparedTransactionBytes,
  validatePreparedTransactionIntent,
  type PreparedTransactionIntent,
} from '../src/lib/portalTransactionIntent.ts';

interface Fixture {
  name: string;
  wallet: string;
  prepared: PreparedVaultTransaction;
  intent: PreparedTransactionIntent;
  lookup?: { address: string; addresses: string[] };
}

const fixtures = JSON.parse(readFileSync(
  new URL('./fixtures/prepared-transaction-intents.json', import.meta.url),
  'utf8',
)) as Fixture[];

const byName = new Map(fixtures.map((fixture) => [fixture.name, fixture]));
const stage1Fixtures = JSON.parse(readFileSync(
  new URL('./fixtures/prepared-stage1-transactions.json', import.meta.url), 'utf8',
)) as Fixture[];
const serializationOptions = {
  requireAllSignatures: false,
  verifySignatures: false,
};

function fixture(name: string): Fixture {
  const value = byName.get(name);
  assert.ok(value, `missing fixture ${name}`);
  return value;
}

function changedIntent(
  source: Fixture,
  changes: Record<string, unknown>,
): PreparedTransactionIntent {
  return { ...source.intent, ...changes } as PreparedTransactionIntent;
}

function changedPrepared(
  source: Fixture,
  changes: Partial<PreparedVaultTransaction>,
): PreparedVaultTransaction {
  return { ...source.prepared, ...changes };
}

function changedTransaction(
  source: Fixture,
  mutate: (transaction: Transaction) => void,
): PreparedVaultTransaction {
  const transaction = Transaction.from(Buffer.from(source.prepared.transaction, 'base64'));
  mutate(transaction);
  // These fixtures are unsigned. Recompile signer slots after role/key edits
  // so the mutant reaches the firewall instead of failing in the SDK encoder.
  transaction.signatures = [];
  return changedPrepared(source, {
    transaction: Buffer.from(transaction.serialize(serializationOptions)).toString('base64'),
  });
}

function changedWire(
  source: Fixture,
  mutate: (wire: Buffer) => void,
): PreparedVaultTransaction {
  const wire = Buffer.from(source.prepared.transaction, 'base64');
  mutate(wire);
  return changedPrepared(source, { transaction: wire.toString('base64') });
}

function readShortVec(bytes: Buffer, start: number): { next: number; value: number } {
  let value = 0;
  let shift = 0;
  let cursor = start;
  while (cursor < bytes.length) {
    const byte = bytes[cursor];
    value |= (byte & 0x7f) << shift;
    cursor += 1;
    if ((byte & 0x80) === 0) return { next: cursor, value };
    shift += 7;
    if (shift > 28) break;
  }
  throw new Error('invalid shortvec');
}

function messageStart(wire: Buffer): number {
  const signatures = readShortVec(wire, 0);
  return signatures.next + signatures.value * 64;
}

async function rejects(
  source: Fixture,
  prepared = source.prepared,
  intent = source.intent,
  wallet = source.wallet,
) {
  await assert.rejects(
    validatePreparedTransactionIntent(prepared, intent, wallet),
    PreparedTransactionIntentError,
  validateStage1VersionedTransaction,
  validateAndSignStage1VersionedTransactionBytes,
  );
}

for (const source of stage1Fixtures.filter(row => !row.lookup)) {
  test(`Stage 1 ${source.name}: backend bytes pass and every instruction/account/data/fee substitution fails`, async () => {
    await assert.doesNotReject(validatePreparedTransactionIntent(source.prepared, source.intent, source.wallet));
    const other = new PublicKey('11111111111111111111111111111112');
    const transaction = Transaction.from(Buffer.from(source.prepared.transaction, 'base64'));
    await rejects(source, source.prepared, source.intent, other.toBase58());
    await rejects(source, changedTransaction(source, tx => { tx.feePayer = other; }));
    await rejects(source, changedTransaction(source, tx => { tx.instructions.push(tx.instructions.at(-1)!); }));
    await rejects(source, changedPrepared(source, { pda: other.toBase58() }));
    for (let i = 0; i < transaction.instructions.length; i += 1) {
      await rejects(source, changedTransaction(source, tx => { tx.instructions[i].programId = other; }));
      for (let byte = 0; byte < transaction.instructions[i].data.length; byte += 1) {
        await rejects(source, changedTransaction(source, tx => { tx.instructions[i].data[byte] ^= 1; }));
      }
      for (let k = 0; k < transaction.instructions[i].keys.length; k += 1) {
        await rejects(source, changedTransaction(source, tx => { tx.instructions[i].keys[k].pubkey = other; }));
      }
    }
    // Change the union of roles across all references (Solana coalesces them).
    const allKeys = new Set(transaction.instructions.flatMap(ix => ix.keys.map(k => k.pubkey.toBase58())));
    for (const address of allKeys) {
      if (address === transaction.feePayer!.toBase58()) continue;
      for (const role of ['isSigner', 'isWritable'] as const) {
        await rejects(source, changedTransaction(source, tx => {
          for (const ix of tx.instructions) for (const entry of ix.keys) {
            if (entry.pubkey.toBase58() === address) entry[role] = !entry[role];
          }
        }));
      }
    }
  });
}

test('Stage 1 intent changes are refused before either signing API is called', async () => {
  for (const source of stage1Fixtures.filter(row => !row.lookup)) {
    for (const field of ['amountBaseUnits', 'basisLamports', 'depositId', 'requestId', 'week']) {
      if (!(field in source.intent)) continue;
      await rejects(source, source.prepared, changedIntent(source, { [field]: '999' }));
    }
    if ('lockWeeks' in source.intent) {
      await rejects(source, source.prepared, changedIntent(source, { lockWeeks: 1 }));
    }
    if (source.intent.kind === 'stage1_self_claim') {
      const altered = structuredClone(source.intent);
      altered.claims[0].amountBaseUnits = '101';
      await rejects(source, source.prepared, altered);
    }
    let calls = 0;
    const bad = changedTransaction(source, tx => { tx.instructions[0].data[0] ^= 1; });
    await assert.rejects(validateAndSignPreparedTransaction(bad, source.intent, source.wallet, async () => { calls++; return ''; }));
    await assert.rejects(validateAndSignPreparedTransactionBytes(bad, source.intent, source.wallet, async () => { calls++; return new Uint8Array(); }));
    assert.equal(calls, 0);
  }
});

test('all 20 backend-built production instruction shapes are accepted', async () => {
  assert.equal(fixtures.length, 20);
  assert.deepEqual(
    new Set(fixtures.map((entry) => entry.intent.kind)),
    new Set([
      'stake',
      'unstake',
      'balance_add_funds',
      'balance_withdraw',
      'create_vault',
    ]),
  );
  for (const entry of fixtures) {
    await assert.doesNotReject(
      validatePreparedTransactionIntent(entry.prepared, entry.intent, entry.wallet),
      entry.name,
    );
  }
});

test('program, discriminator, accounts, roles, and extra instructions are rejected', async () => {
  const source = fixture('stake_base');

  await rejects(source, changedTransaction(source, (transaction) => {
    transaction.instructions.at(-1)!.programId = new PublicKey('11111111111111111111111111111111');
  }));
  await rejects(source, changedTransaction(source, (transaction) => {
    transaction.instructions.at(-1)!.data[0] ^= 0x01;
  }));
  await rejects(source, changedTransaction(source, (transaction) => {
    const accounts = transaction.instructions.at(-1)!.keys;
    [accounts[0], accounts[1]] = [accounts[1], accounts[0]];
  }));
  await rejects(source, changedWire(source, (wire) => {
    wire[messageStart(wire)] = 2;
  }));
  await rejects(source, changedTransaction(source, (transaction) => {
    const vault = transaction.instructions.at(-1)!.keys[0].pubkey;
    for (const instruction of transaction.instructions) {
      for (const account of instruction.keys) {
        if (account.pubkey.equals(vault)) account.isWritable = false;
      }
    }
  }));
  await rejects(source, changedTransaction(source, (transaction) => {
    transaction.instructions.push(transaction.instructions.at(-1)!);
  }));
});

test('wallet, vault, amount, mint, PDA, fee payer, and metadata substitutions are rejected', async () => {
  const stake = fixture('stake_base');
  const addCal = fixture('add_cal');
  const create = fixture('create_dung');

  await rejects(stake, stake.prepared, stake.intent, 'DpLPBaRuLnBsR3P3meU1tmiNUxreXwskXBebTYKvNGne');
  await rejects(stake, stake.prepared, changedIntent(stake, { vaultId: 43 }));
  await rejects(stake, stake.prepared, changedIntent(stake, { amountBaseUnits: '123000000001' }));
  await rejects(addCal, addCal.prepared, changedIntent(addCal, { asset: 'USDC' }));
  await rejects(addCal, addCal.prepared, changedIntent(addCal, { asset: 'DUNG' }));
  const withdrawDung = fixture('withdraw_dung');
  await rejects(withdrawDung, withdrawDung.prepared, changedIntent(withdrawDung, { asset: 'bogus' }));
  await rejects(addCal, changedPrepared(addCal, { pda: fixture('add_usdc').prepared.pda }));
  await rejects(stake, changedWire(stake, (wire) => {
    const start = messageStart(wire);
    const accountCount = readShortVec(wire, start + 3);
    Buffer.from(new PublicKey(stake.wallet).toBytes()).copy(wire, accountCount.next);
  }));
  await rejects(stake, changedPrepared(stake, { blockhash: 'SysvarRent111111111111111111111111111111111' }));
  await rejects(stake, changedPrepared(stake, { lastValidBlockHeight: 0 }));
  await rejects(stake, changedPrepared(stake, { vaultId: 43 }));
  await rejects(create, changedPrepared(create, { pda: fixture('add_cal').prepared.pda }));
});

test('canonical climb identity and creation payment substitutions are rejected', async () => {
  const source = fixture('create_dung');
  const commitment = (source.prepared as PreparedVaultTransaction & { canonCommitmentHex: string })
    .canonCommitmentHex;

  await rejects(source, source.prepared, changedIntent(source, { paymentMethod: 'cal_usdc' }));
  await rejects(source, source.prepared, changedIntent(source, { climbId: 'different-climb' }));
  await rejects(source, source.prepared, changedIntent(source, { canonId: '33333333-3333-3333-3333-333333333333' }));
  await rejects(source, source.prepared, changedIntent(source, { canonVersion: 3 }));
  await rejects(source, {
    ...source.prepared,
    canonCommitmentHex: `${commitment.slice(0, -2)}00`,
  } as PreparedVaultTransaction);
});

test('malformed, versioned, duplicate-key, and unknown transactions fail closed', async () => {
  const source = fixture('stake_base');
  await rejects(source, changedPrepared(source, { transaction: 'not base64' }));

  const versioned = Buffer.from(source.prepared.transaction, 'base64');
  versioned[messageStart(versioned)] |= 0x80;
  await rejects(source, changedPrepared(source, { transaction: versioned.toString('base64') }));

  const duplicate = Buffer.from(source.prepared.transaction, 'base64');
  const start = messageStart(duplicate);
  const accountCount = readShortVec(duplicate, start + 3);
  assert.ok(accountCount.value > 1);
  duplicate.copy(duplicate, accountCount.next + 32, accountCount.next, accountCount.next + 32);
  await rejects(source, changedPrepared(source, { transaction: duplicate.toString('base64') }));

  await rejects(source, source.prepared, { kind: 'unknown' } as never);
});

test('invalid bytes are rejected before a wallet signer is invoked', async () => {
  const source = fixture('stake_base');
  let signingCalls = 0;
  await assert.rejects(
    validateAndSignPreparedTransaction(
      source.prepared,
      changedIntent(source, { amountBaseUnits: '1' }),
      source.wallet,
      async () => {
        signingCalls += 1;
        return 'signed';
      },
    ),
    PreparedTransactionIntentError,
  validateStage1VersionedTransaction,
  validateAndSignStage1VersionedTransactionBytes,
  );
  assert.equal(signingCalls, 0);

  const result = await validateAndSignPreparedTransaction(
    source.prepared,
    source.intent,
    source.wallet,
    async () => {
      signingCalls += 1;
      return 'signed';
    },
  );
  assert.equal(result, 'signed');
  assert.equal(signingCalls, 1);
});

test('Privy receives immutable bytes serialized from the validated transaction', async () => {
  const source = fixture('stake_base');
  const prepared = { ...source.prepared };
  let signedBytes = '';

  await validateAndSignPreparedTransactionBytes(
    prepared,
    source.intent,
    source.wallet,
    async (validatedTransaction) => {
      prepared.transaction = fixture('unstake_base').prepared.transaction;
      signedBytes = validatedTransaction;
      return 'signed';
    },
  );

  assert.equal(signedBytes, source.prepared.transaction);
  assert.notEqual(signedBytes, prepared.transaction);
});

test('both wallet bridges keep the shared validator ahead of wallet APIs', () => {
  const external = readFileSync(
    new URL('../src/components/auth/ExternalWalletTransactionSignerBridge.tsx', import.meta.url),
    'utf8',
  );
  const privy = readFileSync(
    new URL('../src/components/auth/PrivyWalletTransactionSignerBridge.tsx', import.meta.url),
    'utf8',
  );
  assert.match(external, /validateAndSignPreparedTransaction/u);
  assert.match(privy, /validateAndSignPreparedTransactionBytes/u);
  assert.ok(
    external.indexOf('validateAndSignPreparedTransaction(') < external.indexOf('signTransaction(transaction)'),
  );
  assert.ok(
    privy.indexOf('validateAndSignPreparedTransactionBytes(') < privy.indexOf('privySolana.signPreparedTransaction('),
  );
  assert.match(privy, /privySolana\.signPreparedTransaction\(\s*validatedTransaction,/u);
});

for (const source of stage1Fixtures.filter(row => row.lookup)) {
  test(`Stage 1 ${source.name}: maximum-depth packet and independently resolved lookup are exact`, async () => {
    assert.equal(source.intent.kind, 'stage1_self_claim');
    const intent = source.intent as Extract<PreparedTransactionIntent, { kind: 'stage1_self_claim' }>;
    const table = new AddressLookupTableAccount({ key: new PublicKey(source.lookup!.address), state: {
      deactivationSlot: (1n << 64n) - 1n, lastExtendedSlot: 1, lastExtendedSlotStartIndex: 0,
      authority: new PublicKey(source.wallet), addresses: source.lookup!.addresses.map(k => new PublicKey(k)),
    } });
    const resolve = async () => table;
    const validate = (prepared = source.prepared, lookup = resolve) => validateStage1VersionedTransaction(prepared, intent, source.wallet, lookup);
    await assert.doesNotReject(validate());
    assert.ok(Buffer.from(source.prepared.transaction, 'base64').length <= 1232);
    await assert.rejects(validate(source.prepared, async () => null));
    for (let i = 0; i < table.state.addresses.length; i++) {
      const addresses = [...table.state.addresses]; addresses[i] = new PublicKey('11111111111111111111111111111112');
      await assert.rejects(validate(source.prepared, async () => new AddressLookupTableAccount({ key: table.key, state: { ...table.state, addresses } })));
    }
    for (const field of ['numRequiredSignatures', 'numReadonlySignedAccounts', 'numReadonlyUnsignedAccounts'] as const) {
      const tx = VersionedTransaction.deserialize(Buffer.from(source.prepared.transaction, 'base64'));
      tx.message.header[field] ^= 1;
      await assert.rejects(validate({ ...source.prepared, transaction: Buffer.from(tx.serialize()).toString('base64') }));
    }
    const original = VersionedTransaction.deserialize(Buffer.from(source.prepared.transaction, 'base64'));
    for (let i = 0; i < original.message.compiledInstructions.length; i++) {
      for (let j = 0; j < original.message.compiledInstructions[i].data.length; j++) {
        const tx = VersionedTransaction.deserialize(Buffer.from(source.prepared.transaction, 'base64'));
        tx.message.compiledInstructions[i].data[j] ^= 1;
        await assert.rejects(validate({ ...source.prepared, transaction: Buffer.from(tx.serialize()).toString('base64') }));
      }
    }
    let calls = 0;
    await assert.rejects(validateAndSignStage1VersionedTransactionBytes(source.prepared, intent, source.wallet, async () => null, async () => { calls++; }));
    assert.equal(calls, 0);
  });
}

const devnetCashMint = '932CwEMTWHDY1BEkV66DKDgngeEypU3JmybWBu4vMh1e';
const mainnetUsdcMint = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v';
const stage1Program = new PublicKey('EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH');
const tokenProgram = new PublicKey('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA');
const associatedTokenProgram = new PublicKey('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL');
const stage1Fixture = (name: string) => stage1Fixtures.find(row => row.name === name)!;
const walletAta = (wallet: string, mint: PublicKey) => PublicKey.findProgramAddressSync(
  [new PublicKey(wallet).toBytes(), tokenProgram.toBytes(), mint.toBytes()], associatedTokenProgram)[0];

// Every account a backend vector derives from its token mint, in a fixed order.
function mintAccounts(source: Fixture, mint: string): string[] {
  const key = new PublicKey(mint), wallet = new PublicKey(source.wallet);
  const pda = (seed: string, ...parts: Uint8Array[]) => PublicKey.findProgramAddressSync([Buffer.from(seed), ...parts], stage1Program)[0];
  if (source.intent.kind !== 'stage1_self_claim') {
    return [key, walletAta(source.wallet, key), pda('rider_balance_token', wallet.toBytes(), key.toBytes())].map(k => k.toBase58());
  }
  const week = (value: string) => { const bytes = Buffer.alloc(8); bytes.writeBigUInt64LE(BigInt(value)); return bytes; };
  return [key, pda('s1v1_asset', key.toBytes()), pda('s1v1_earnings', key.toBytes()), walletAta(source.wallet, key),
    ...source.intent.claims.map(leaf => pda('s1v1_claims', new PublicKey(leaf.hill).toBytes(), key.toBytes(), week(leaf.week)))]
    .map(k => k.toBase58());
}

// The backend's exact bytes in another mint: only mint-derived static keys,
// lookup addresses and the PDA reference move; the intent names the new mint.
function inMint(source: Fixture, original: string, mint: string): Fixture {
  const from = mintAccounts(source, original), to = mintAccounts(source, mint);
  const swap = (key: string) => from.includes(key) ? to[from.indexOf(key)] : key;
  const wire = Buffer.from(source.prepared.transaction, 'base64');
  const versioned = (wire[messageStart(wire)] & 0x80) !== 0;
  const keys = readShortVec(wire, messageStart(wire) + (versioned ? 4 : 3));
  const moved = new Set<string>();
  for (let i = 0; i < keys.value; i += 1) {
    const at = keys.next + i * 32, key = new PublicKey(wire.subarray(at, at + 32)).toBase58();
    if (swap(key) !== key) { new PublicKey(swap(key)).toBuffer().copy(wire, at); moved.add(key); }
  }
  source.lookup?.addresses.forEach(key => { if (swap(key) !== key) moved.add(key); });
  assert.deepEqual([...moved].sort(), [...from].sort(), `${source.name}: every mint-derived account moved`);
  return {
    ...source,
    prepared: { ...source.prepared, transaction: wire.toString('base64'), pda: swap(source.prepared.pda!) },
    intent: source.intent.kind === 'stage1_self_claim' ? { ...source.intent, mint } : source.intent,
    ...(source.lookup ? { lookup: { ...source.lookup, addresses: source.lookup.addresses.map(swap) } } : {}),
  };
}

test('Stage 1 cash claims accept the pinned devnet city cash mint; Balance USDC stays the release mint', async () => {
  for (const name of ['cash_claim_1', 'cash_claim_2']) {
    const source = stage1Fixture(name), original = (source.intent as { mint: string }).mint;
    const cash = inMint(source, original, devnetCashMint);
    await assert.doesNotReject(validatePreparedTransactionIntent(cash.prepared, cash.intent, cash.wallet), name);
    await rejects(cash, cash.prepared, source.intent);
    await rejects(cash, cash.prepared, { ...cash.intent, claimType: 'dung' } as PreparedTransactionIntent);
    const other = inMint(source, original, mainnetUsdcMint);
    await rejects(other);
  }
  const deep = inMint(stage1Fixture('cash_claim_depth16'), (stage1Fixture('cash_claim_depth16').intent as { mint: string }).mint, devnetCashMint);
  const table = new AddressLookupTableAccount({ key: new PublicKey(deep.lookup!.address), state: {
    deactivationSlot: (1n << 64n) - 1n, lastExtendedSlot: 1, lastExtendedSlotStartIndex: 0,
    authority: new PublicKey(deep.wallet), addresses: deep.lookup!.addresses.map(k => new PublicKey(k)),
  } });
  await assert.doesNotReject(validateStage1VersionedTransaction(deep.prepared,
    deep.intent as Extract<PreparedTransactionIntent, { kind: 'stage1_self_claim' }>, deep.wallet, async () => table));
  for (const name of ['add_usdc', 'withdraw_usdc', 'withdraw_usdc_create_ata']) {
    const balance = fixture(name);
    await assert.doesNotReject(validatePreparedTransactionIntent(balance.prepared, balance.intent, balance.wallet), name);
    await rejects(inMint(balance, 'DpLPBaRuLnBsR3P3meU1tmiNUxreXwskXBebTYKvNGne', devnetCashMint));
  }
});
