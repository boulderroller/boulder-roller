import * as anchor from '@coral-xyz/anchor';
import { expect } from 'chai';
import { ChildProcess, spawn } from 'child_process';
import { createHash } from 'crypto';
import { closeSync, openSync, readFileSync, writeFileSync } from 'fs';
import { createRequire } from 'module';
import { join } from 'path';
import { PublicKey, SystemProgram } from '@solana/web3.js';
import { createMint } from '@solana/spl-token';

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
const sha = (bytes: Buffer) => createHash('sha256').update(bytes).digest('hex');

if (process.env.STAGE1_SERVICE_CUTOVER === '1') describe('Stage1 services: real localnet indexer survives the 0x4C to 0x4D to 0x4E advances', () => {
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);
  const wallet = provider.wallet as anchor.Wallet, connection = provider.connection;
  const program: any = anchor.workspace.BoulderRollers, programId: PublicKey = program.programId;
  const pda = (seed: string) => PublicKey.findProgramAddressSync([Buffer.from(seed)], programId)[0];
  const programConfig = pda('program_config');
  const indexerDir = process.env.STAGE1_SERVICE_INDEXER!;
  // Devnet's history: 0x4C main, the 0x4D Stage 1 release, then the 0x4E candidate.
  // Indexer Stage 1 activation is proven only by the actual 0x4C -> 0x4D advance.
  const legacy = readFileSync(process.env.STAGE1_SERVICE_LEGACY!);
  const previous = readFileSync(process.env.STAGE1_SERVICE_PREVIOUS!);
  const current = readFileSync(process.env.STAGE1_SERVICE_PROGRAM!);
  const work = process.env.STAGE1_SERVICE_WORK!;
  const healthUrl = `http://127.0.0.1:${process.env.STAGE1_SERVICE_HEALTH_PORT}/health`;
  let indexer: ChildProcess, logFd: number, programData: PublicKey, db: any;
  let observing = false, monitor: Promise<void>, phase = 'old';
  const samples: any[] = [];
  const restartProbes: any[] = [];

  async function health() {
    const response = await fetch(healthUrl);
    return { code: response.status, ...(await response.json() as any) };
  }
  async function ready(version: number) {
    let last: any;
    for (let tries = 0; tries < 100; tries++) {
      if (indexer.exitCode !== null) throw new Error(`Indexer exited ${indexer.exitCode}: ${readFileSync(join(work, 'indexer.log'), 'utf8')}`);
      try {
        last = await health();
        if (last.code === 200 && last.program_version === version) return last;
      } catch (error) { last = String(error); }
      await sleep(1000);
    }
    throw new Error(`Indexer did not become healthy at ${version}: ${JSON.stringify(last)}\n${readFileSync(join(work, 'indexer.log'), 'utf8')}`);
  }
  async function cli(args: string[]) {
    await new Promise<void>((resolve, reject) => {
      const child = spawn('solana', [...args, '--url', connection.rpcEndpoint, '--keypair', process.env.ANCHOR_WALLET!, '--commitment', 'finalized'], { stdio: ['ignore', 'pipe', 'pipe'] });
      let output = '';
      child.stdout?.on('data', chunk => { output += chunk; });
      child.stderr?.on('data', chunk => { output += chunk; });
      child.on('error', reject);
      child.on('exit', code => code === 0 ? resolve() : reject(new Error(`solana ${args.slice(0, 2).join(' ')} failed: ${output}`)));
    });
  }
  async function upgradeTo(path: string, binary: Buffer, nextPhase: string) {
    phase = `extend-${nextPhase}`;
    const allocated = (await connection.getAccountInfo(programData))!.data.length - 45;
    if (binary.length > allocated) await cli(['program', 'extend', programId.toBase58(), String(binary.length - allocated)]);
    phase = `upgrade-${nextPhase}`;
    await cli(['program', 'deploy', path, '--program-id', programId.toBase58(), '--upgrade-authority', process.env.ANCHOR_WALLET!, '--use-rpc']);
    expect(sha((await connection.getAccountInfo(programData, 'finalized'))!.data.subarray(45, 45 + binary.length))).to.equal(sha(binary));
  }

  before(async () => {
    expect(new URL(connection.rpcEndpoint).hostname).to.equal('127.0.0.1');
    expect(new URL(process.env.STAGE1_SERVICE_DATABASE!).hostname).to.equal('127.0.0.1');
    programData = new PublicKey((await connection.getAccountInfo(programId))!.data.subarray(4, 36));
    expect(sha((await connection.getAccountInfo(programData))!.data.subarray(45, 45 + legacy.length))).to.equal(sha(legacy));
    await program.methods.initializeProgramConfig(wallet.publicKey).accounts({
      programConfig, program: programId, programData, admin: wallet.publicKey, systemProgram: SystemProgram.programId,
    }).rpc();
    expect((await program.account.programConfig.fetch(programConfig)).programVersion).to.equal(0x4c);
    const cal = await createMint(connection, wallet.payer, wallet.publicKey, null, 9);
    const dung = await createMint(connection, wallet.payer, wallet.publicKey, null, 9);
    await program.methods.configureMints(cal, dung).accounts({ programConfig, admin: wallet.publicKey }).rpc();
    const initialized = await program.methods.initializeDungMintState().accounts({
      dungMintState: pda('dung_mint_state'), programConfig, authority: wallet.publicKey, systemProgram: SystemProgram.programId,
    }).rpc();
    await connection.confirmTransaction(initialized, 'finalized');
    const { Pool } = createRequire(join(indexerDir, 'package.json'))('pg');
    db = new Pool({ connectionString: process.env.STAGE1_SERVICE_DATABASE });
    logFd = openSync(join(work, 'indexer.log'), 'w');
    indexer = spawn(process.execPath, [join(indexerDir, 'dist/index.js')], {
      cwd: indexerDir, stdio: ['ignore', logFd, logFd], env: {
        ...process.env, PROGRAM_ID: programId.toBase58(), DUNG_MINT_ADDRESS: dung.toBase58(),
        NODE_OPTIONS: '',
        SOLANA_RPC_URL: connection.rpcEndpoint,
        SOLANA_WS_URL: connection.rpcEndpoint.replace('http:', 'ws:').replace(/:(\d+)$/, (_, port) => `:${Number(port) + 1}`),
        DATABASE_URL: process.env.STAGE1_SERVICE_DATABASE, INDEXER_MODE: 'stream',
        HEALTH_PORT: process.env.STAGE1_SERVICE_HEALTH_PORT, POLL_INTERVAL_MS: '1000', DUNG_SUPPLY_REFRESH_INTERVAL_MS: '20000',
        IDL_PATH: join(process.cwd(), 'target/idl/boulder_rollers.json'),
      },
    });
  });

  after(async () => {
    observing = false;
    if (monitor) await monitor;
    const report = { evidence: 'actual localnet transactions and production indexer process; isolated empty schema fixture',
      indexerPid: indexer?.pid, legacyProgramVersion: 0x4c, previousProgramVersion: 0x4d, candidateProgramVersion: 0x4e,
      legacySourceRevision: '70ec4bc3117a7e244ad9e173b5062abcdf39488d',
      previousSourceRevision: '5931e4540474f658cc9e1be6951674281e548530',
      legacySha256: sha(legacy), previousSha256: sha(previous), candidateSha256: sha(current), samples, restartProbes };
    writeFileSync(process.env.STAGE1_SERVICE_REPORT!, JSON.stringify(report, null, 2));
    if (indexer && indexer.exitCode === null) {
      const exited = new Promise<void>(resolve => indexer.once('exit', () => resolve()));
      indexer.kill('SIGTERM');
      await Promise.race([exited, sleep(5000)]);
      if (indexer.exitCode === null) { indexer.kill('SIGKILL'); await exited; }
    }
    if (logFd !== undefined) closeSync(logFd);
    if (db) await db.end();
  });

  it('starts healthy on the actual 0x4C ELF and keeps Stage1 dark while legacy projections work', async () => {
    const state = await ready(0x4c);
    expect(state.stage1).to.equal('not available on this network');
    expect(state.supply.status).to.equal('fresh');
    expect((await db.query('SELECT program_version FROM indexed_program_config')).rows[0].program_version).to.equal(0x4c);
    expect((await db.query('SELECT spl_mint_supply FROM indexed_supply')).rows[0].spl_mint_supply).to.equal('0');
    observing = true;
    monitor = (async () => {
      while (observing) {
        try { const state = await health(); samples.push({ phase, code: state.code, version: state.program_version, stage1: state.stage1, status: state.status }); }
        catch (error) { samples.push({ phase, error: String(error) }); }
        await sleep(1000);
      }
    })();
    await sleep(1200);
  });

  it('stays healthy during real extension and upgrade to the 0x4D ELF before the version advances', async () => {
    const pid = indexer.pid;
    await upgradeTo(process.env.STAGE1_SERVICE_PREVIOUS!, previous, '0x4d');
    expect((await program.account.programConfig.fetch(programConfig)).programVersion).to.equal(0x4c);
    expect((await ready(0x4c)).stage1).to.equal('not available on this network');
    expect(indexer.pid).to.equal(pid);
    expect(samples.every(sample => sample.code === 200), JSON.stringify(samples)).to.equal(true);
  });

  it('observes the finalized advance without restarting and enables Stage1 with no health failure', async () => {
    phase = 'advance';
    const signature = await program.methods.advanceProgramVersion(0x4c, 0x4d).accounts({ programConfig, admin: wallet.publicKey }).rpc();
    await connection.confirmTransaction(signature, 'finalized');
    const state = await ready(0x4d);
    expect(state.stage1).to.equal('available');
    for (let attempt = 0; attempt < 50; attempt++) {
      if ((await db.query('SELECT program_version FROM indexed_program_config')).rows[0].program_version === 0x4d) break;
      await sleep(200);
    }
    expect((await db.query('SELECT program_version FROM indexed_program_config')).rows[0].program_version).to.equal(0x4d);
    await sleep(1200);
    expect(samples.some(sample => sample.version === 0x4c)).to.equal(true);
    expect(samples.some(sample => sample.version === 0x4d && sample.stage1 === 'available')).to.equal(true);
    expect(samples.every(sample => sample.code === 200), JSON.stringify(samples)).to.equal(true);
  });

  it('keeps Stage1 available through real extension and upgrade to the 0x4E candidate at 0x4D', async () => {
    const pid = indexer.pid;
    await upgradeTo(process.env.STAGE1_SERVICE_PROGRAM!, current, '0x4e');
    expect((await program.account.programConfig.fetch(programConfig)).programVersion).to.equal(0x4d);
    expect((await ready(0x4d)).stage1).to.equal('available');
    expect(indexer.pid).to.equal(pid);
    expect(samples.every(sample => sample.code === 200), JSON.stringify(samples)).to.equal(true);
  });

  it('observes the finalized 0x4D to 0x4E advance without restarting and keeps Stage1 available', async () => {
    phase = 'advance-0x4e';
    const signature = await program.methods.advanceProgramVersion(0x4d, 0x4e).accounts({ programConfig, admin: wallet.publicKey }).rpc();
    await connection.confirmTransaction(signature, 'finalized');
    expect((await ready(0x4e)).stage1).to.equal('available');
    for (let attempt = 0; attempt < 50; attempt++) {
      if ((await db.query('SELECT program_version FROM indexed_program_config')).rows[0].program_version === 0x4e) break;
      await sleep(200);
    }
    expect((await db.query('SELECT program_version FROM indexed_program_config')).rows[0].program_version).to.equal(0x4e);
    await sleep(1200);
    expect(samples.some(sample => sample.version === 0x4e && sample.stage1 === 'available')).to.equal(true);
    expect(samples.filter(sample => sample.version === 0x4d || sample.version === 0x4e).every(sample => sample.stage1 === 'available')).to.equal(true);
    expect(samples.every(sample => sample.code === 200), JSON.stringify(samples)).to.equal(true);
    console.log(`SERVICE_CUTOVER ${JSON.stringify({ pid: indexer.pid, healthySamples: samples.length, versions: [0x4c, 0x4d, 0x4e], indexerRestarts: 0 })}`);
  });

  it('a fresh service process rejects a downgraded config fixture using the actual persisted observation', async () => {
    // The chain remains at 0x4E. Only this independent read fixture changes one
    // version byte to 0x4D, which is inside the window; only the durable
    // observation refuses it. No chain state is fabricated.
    const genesis = await connection.getGenesisHash();
    const row = (await db.query('SELECT highest_version FROM program_version_observations WHERE genesis_hash=$1 AND program_id=$2', [genesis, programId.toBase58()])).rows[0];
    expect(row.highest_version).to.equal(0x4e);
    const dung = (await program.account.programConfig.fetch(programConfig)).dungMint.toBase58();
    const script = `
      const assert = require('node:assert/strict');
      const { Connection } = require('@solana/web3.js');
      const { config } = require('./dist/config.js');
      const { resolveCanonicalDungMint } = require('./dist/supply.js');
      const { programVersionWindow } = require('./dist/program-version-window.js');
      const { closePool } = require('./dist/db.js');
      (async () => {
        const connection = new Connection(config.rpcUrl, 'finalized');
        const read = connection.getAccountInfoAndContext.bind(connection);
        connection.getAccountInfoAndContext = async (...args) => {
          const response = await read(...args);
          response.value.data = Buffer.from(response.value.data);
          response.value.data[72] = 0x4d;
          return response;
        };
        await assert.rejects(resolveCanonicalDungMint(connection), /version downgrade/);
        assert.equal(programVersionWindow.stage1Available, false);
        assert.throws(() => programVersionWindow.status(), /version downgrade/);
        console.log(JSON.stringify({ evidence: 'fresh process, actual database, downgraded config fixture', rejectedVersion: 77, durableVersion: 78 }));
      })().catch(error => { console.error(error); process.exitCode = 1; }).finally(closePool);
    `;
    const output = await new Promise<string>((resolve, reject) => {
      const child = spawn(process.execPath, ['-e', script], { cwd: indexerDir,
        env: { ...process.env, NODE_OPTIONS: '', PROGRAM_ID: programId.toBase58(), DUNG_MINT_ADDRESS: dung,
          SOLANA_RPC_URL: connection.rpcEndpoint, DATABASE_URL: process.env.STAGE1_SERVICE_DATABASE },
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      let output = '';
      child.stdout?.on('data', chunk => { output += chunk; });
      child.stderr?.on('data', chunk => { output += chunk; });
      child.on('error', reject);
      child.on('exit', code => code === 0 ? resolve(output) : reject(new Error(output)));
    });
    restartProbes.push(JSON.parse(output.split('\n').find(line => line.startsWith('{'))!));
    expect((await ready(0x4e)).stage1).to.equal('available');
  });

  it('hides retained Stage1 signatures before transaction pagination and counting in PostgreSQL', async () => {
    // Read-only CTE fixtures shadow table names for this independent API call.
    // Nothing is inserted into the live indexer's account/event projections.
    const fixture = `WITH indexed_transactions(signature,instruction_name,instruction_index,slot,block_time,status,fee_lamports,compute_units) AS (
      VALUES ('legacy-a','claimCal',0,1,1,'success',5000,100),
             ('legacy-b','claimCal',0,2,2,'success',5000,100),
             ('mixed','claimCal',0,3,3,'success',5000,100),
             ('mixed','claimStage1',1,3,3,'success',5000,100),
             ('event-only','claimCal',0,4,4,'success',5000,100),
             ('unprefixed','cancelPledge',0,5,5,'success',5000,100)
    ), indexed_events(tx_signature,event_name) AS (VALUES ('event-only','Stage1CashReceived')), `;
    const requireIndexer = createRequire(join(indexerDir, 'package.json'));
    const api = requireIndexer('./dist/api.js');
    requireIndexer('./dist/program-version-window.js').programVersionWindow.observe(0x4c);
    api.setApiRuntimeForTests({ query: async (sql: string, params: unknown[]) =>
      sql.includes('WITH visible_transactions')
        ? db.query(fixture + sql.trimStart().replace(/^WITH /, ''), params)
        : { rows: [] },
    });
    try {
      const response = { code: 0, body: '', writeHead(code: number) { this.code = code; }, end(body: string) { this.body = body; } };
      await api.handleApiRequest({ url: '/v1/transactions?limit=1&offset=1', method: 'GET' }, response);
      expect(response.code).to.equal(200);
      const body = JSON.parse(response.body);
      expect(body.total).to.equal(2);
      expect(body.transactions.map((row: any) => row.signature)).to.deep.equal(['legacy-a']);
      restartProbes.push({ evidence: 'read-only PostgreSQL retained-row fixture through production API', visibleTransactions: body.total, pagination: body.transactions.map((row: any) => row.signature) });
    } finally { api.resetApiRuntimeForTests(); }
  });
});
