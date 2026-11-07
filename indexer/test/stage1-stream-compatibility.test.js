const test = require('node:test');
const assert = require('node:assert/strict');
const { Connection, PublicKey } = require('@solana/web3.js');
const { BorshAccountsCoder } = require('@coral-xyz/anchor');
const { config } = require('../dist/config.js');
const { programVersionWindow } = require('../dist/program-version-window.js');
const supply = require('../dist/supply.js');
const common = require('../dist/writers/common.js');
const { startStream, stopStream } = require('../dist/modes/stream.js');

for (const data of [Buffer.alloc(0), BorshAccountsCoder.accountDiscriminator('ProgramConfig')]) {
  test(`a malformed canonical ProgramConfig notification (${data.length} bytes) clears Stage1 capability`, async t => {
    let callback;
    t.mock.method(supply, 'resolveCanonicalDungMint', async () => {
      programVersionWindow.observe(0x4d);
      return { address: PublicKey.default };
    });
    t.mock.method(supply, 'refreshDungMintSupply', async () => ({ written: true, amount: '0', slot: 8 }));
    t.mock.method(common, 'updateSyncState', async () => {});
    t.mock.method(Connection.prototype, 'onProgramAccountChange', (_, listener) => { callback = listener; return 1; });
    t.mock.method(Connection.prototype, 'onAccountChange', () => 2);
    t.mock.method(Connection.prototype, 'removeProgramAccountChangeListener', async () => {});
    t.mock.method(Connection.prototype, 'removeAccountChangeListener', async () => {});
    t.after(stopStream);
    await startStream();
    assert.equal(programVersionWindow.stage1Available, true);
    const programId = new PublicKey(config.programId);
    const [accountId] = PublicKey.findProgramAddressSync([Buffer.from('program_config')], programId);
    await callback({ accountId, accountInfo: { data, owner: programId } }, { slot: 9 });
    assert.equal(programVersionWindow.stage1Available, false);
    assert.throws(() => programVersionWindow.status(), /ProgramConfig notification/);
  });
}
