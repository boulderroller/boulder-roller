const { Connection } = require('@solana/web3.js');
const store = require('../../dist/program-version-store.js');

// Explicit unit fixture. Real PostgreSQL persistence is exercised by the
// service-cutover rehearsal and backend PostgreSQL runtime contract.
function mockProgramVersionStore(t) {
  const observations = new Map();
  t.mock.method(Connection.prototype, 'getGenesisHash', async () => 'unit-genesis');
  t.mock.method(store, 'persistProgramVersion', async (genesis, program, version) => {
    const key = `${genesis}:${program}`;
    const highest = Math.max(observations.get(key) ?? version, version);
    observations.set(key, highest);
    return highest;
  });
  return observations;
}
module.exports = { mockProgramVersionStore };
