const test = require('node:test');
const assert = require('node:assert/strict');
const { mockProgramVersionStore } = require('./helpers/program-version-store.js');
test.beforeEach(mockProgramVersionStore);
const { BorshAccountsCoder } = require('@coral-xyz/anchor');
const { PublicKey } = require('@solana/web3.js');

const { config } = require('../dist/config.js');
const {
  CURRENT_PROGRAM_VERSION,
} = require('../dist/generated-program-version.js');
const V4_A_PREDECESSOR_PROGRAM_VERSION = 0x44;
const {
  readDungMintSupply,
  resolveCanonicalDungMint,
} = require('../dist/supply.js');

function appendOnlyProgramConfigAccount(
  programId,
  dungMint,
  { initialized = true, programVersion = CURRENT_PROGRAM_VERSION } = {},
) {
  // Devnet still has the 325-byte V4-A account. Mint authority lives in the
  // stable prefix and must not depend on decoding fields appended later.
  const data = Buffer.alloc(325);
  Buffer.from(BorshAccountsCoder.accountDiscriminator('ProgramConfig')).copy(data, 0);
  data[72] = programVersion;
  data[73] = initialized ? 1 : 0;
  data[74] = 254;
  dungMint.toBuffer().copy(data, 107);
  return {
    context: { slot: 700 },
    value: {
      data,
      owner: programId,
    },
  };
}

test('canonical DUNG mint resolves from the stable append-only ProgramConfig prefix', async () => {
  const programId = new PublicKey(config.programId);
  const canonicalMint = new PublicKey(config.dungMintAddress);
  const connection = {
    getGenesisHash: async () => 'unit-genesis',
    getAccountInfoAndContext: async () => (
      appendOnlyProgramConfigAccount(programId, canonicalMint)
    ),
  };

  const resolved = await resolveCanonicalDungMint(connection);

  assert.equal(resolved.address.toBase58(), canonicalMint.toBase58());
  assert.equal(resolved.programConfigSlot, 700);
});

test('canonical DUNG supply is read only after ProgramConfig authority matches', async () => {
  const programId = new PublicKey(config.programId);
  const canonicalMint = new PublicKey(config.dungMintAddress);
  const observedMints = [];

  const connection = {
    getGenesisHash: async () => 'unit-genesis',
    getAccountInfoAndContext: async () => (
      appendOnlyProgramConfigAccount(programId, canonicalMint)
    ),
    getTokenSupply: async (mint, commitment) => {
      observedMints.push(mint.toBase58());
      assert.equal(commitment, 'finalized');
      return {
        context: { slot: 701 },
        value: {
          amount: '18446744073709551615',
          decimals: 9,
          uiAmount: null,
          uiAmountString: '18446744073.709551615',
        },
      };
    },
  };

  const observation = await readDungMintSupply(connection);

  assert.deepEqual(observation, {
    amount: '18446744073709551615',
    slot: 701,
  });
  assert.deepEqual(observedMints, [canonicalMint.toBase58()]);
});

test('canonical DUNG supply rejects an older ProgramConfig ABI', async () => {
  const programId = new PublicKey(config.programId);
  const canonicalMint = new PublicKey(config.dungMintAddress);
  const connection = {
    getGenesisHash: async () => 'unit-genesis',
    getAccountInfoAndContext: async () => (
      appendOnlyProgramConfigAccount(programId, canonicalMint, {
        programVersion: V4_A_PREDECESSOR_PROGRAM_VERSION,
      })
    ),
  };

  await assert.rejects(
    resolveCanonicalDungMint(connection),
    /ProgramConfig version (mismatch|downgrade)/,
  );
});

test('configured DUNG mint mismatch fails closed before reading token supply', async () => {
  const programId = new PublicKey(config.programId);
  const mismatchedMint = new PublicKey(new Uint8Array(32).fill(7));
  let tokenSupplyReads = 0;

  const connection = {
    getGenesisHash: async () => 'unit-genesis',
    getAccountInfoAndContext: async () => (
      appendOnlyProgramConfigAccount(programId, mismatchedMint)
    ),
    getTokenSupply: async () => {
      tokenSupplyReads++;
      throw new Error('must not be called');
    },
  };

  await assert.rejects(
    readDungMintSupply(connection),
    /does not match ProgramConfig DUNG mint/,
  );
  assert.equal(tokenSupplyReads, 0);
});

test('missing ProgramConfig fails closed', async () => {
  const connection = {
    getGenesisHash: async () => 'unit-genesis',
    getAccountInfoAndContext: async () => ({
      context: { slot: 700 },
      value: null,
    }),
  };

  await assert.rejects(
    resolveCanonicalDungMint(connection),
    /ProgramConfig is missing/,
  );
});

test('invalid ProgramConfig stable prefixes fail closed', async () => {
  const programId = new PublicKey(config.programId);
  const canonicalMint = new PublicKey(config.dungMintAddress);
  const account = appendOnlyProgramConfigAccount(programId, canonicalMint);
  const connection = {
    getGenesisHash: async () => 'unit-genesis',
    getAccountInfoAndContext: async () => account,
  };

  account.value.data = Buffer.alloc(138);
  await assert.rejects(
    resolveCanonicalDungMint(connection),
    /stable authority prefix requires 139 bytes/,
  );

  account.value.data = appendOnlyProgramConfigAccount(
    programId,
    canonicalMint,
  ).value.data;
  account.value.data[0] ^= 0xff;
  await assert.rejects(
    resolveCanonicalDungMint(connection),
    /discriminator does not identify ProgramConfig/,
  );
});

test('uninitialized ProgramConfig fails closed', async () => {
  const programId = new PublicKey(config.programId);
  const canonicalMint = new PublicKey(config.dungMintAddress);
  const connection = {
    getGenesisHash: async () => 'unit-genesis',
    getAccountInfoAndContext: async () => (
      appendOnlyProgramConfigAccount(
        programId,
        canonicalMint,
        { initialized: false },
      )
    ),
  };

  await assert.rejects(
    resolveCanonicalDungMint(connection),
    /ProgramConfig is not initialized/,
  );
});

test('canonical DUNG supply rejects malformed amount and slot observations', async () => {
  const programId = new PublicKey(config.programId);
  const canonicalMint = new PublicKey(config.dungMintAddress);

  const supplyResponse = {
    context: { slot: 701 },
    value: { amount: '1.5', decimals: 9 },
  };
  const connection = {
    getGenesisHash: async () => 'unit-genesis',
    getAccountInfoAndContext: async () => (
      appendOnlyProgramConfigAccount(programId, canonicalMint)
    ),
    getTokenSupply: async () => supplyResponse,
  };

  await assert.rejects(readDungMintSupply(connection), /non-u64 supply/);

  supplyResponse.value.amount = '1';
  supplyResponse.context.slot = Number.MAX_SAFE_INTEGER + 1;
  await assert.rejects(readDungMintSupply(connection), /valid finalized slot/);
});

for (const version of [0x4c, 0x4d, 0x4e]) {
  test(`cutover accepts finalized ProgramConfig 0x${version.toString(16)}`, async () => {
    const resolved = await resolveCanonicalDungMint({
      getGenesisHash: async () => 'unit-genesis',
      getAccountInfoAndContext: async () => appendOnlyProgramConfigAccount(
        new PublicKey(config.programId), new PublicKey(config.dungMintAddress),
        { programVersion: version }),
    }, new (require('../dist/program-version-window.js').ProgramVersionWindow)());
    assert.equal(resolved.programVersion, version);
    assert.equal(resolved.stage1Available, version !== 0x4c);
  });
}
