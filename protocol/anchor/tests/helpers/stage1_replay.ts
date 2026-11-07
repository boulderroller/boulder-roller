// LOCAL EVIDENCE ONLY: Stage1 custody accounts were created by transactions.
// Preserve captured data/owner/executable/lamports across a fresh genesis;
// never edit application timestamps or add a program clock override. Capture
// uses sequential processed reads while this test's application is quiescent.
import { spawn, spawnSync, ChildProcess } from 'child_process';
import { mkdtempSync, writeFileSync, openSync, closeSync, readFileSync, rmSync, renameSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { Connection, PublicKey, Keypair, AccountInfo } from '@solana/web3.js';
import { TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID } from '@solana/spl-token';
export type Capture = Map<string, AccountInfo<Buffer>>;
export const pause = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
function kernelEphemeralPorts(): [number, number] | undefined {
  try {
    const [low, high] = readFileSync('/proc/sys/net/ipv4/ip_local_port_range', 'utf8').trim().split(/\s+/).map(Number);
    return Number.isInteger(low) && Number.isInteger(high) ? [low, high] : undefined;
  } catch { return undefined; }
}

// Own only ledgers and children created by this module. Exit must be synchronous
// (Mocha --exit and uncaught failures do not await promises).
const owned = new Map<string, { child?: ChildProcess; stop: () => Promise<void> }>();
let exiting = false;
process.once('exit', () => {
  for (const [directory, runtime] of owned) {
    const child = runtime.child;
    if (child?.pid && child.exitCode === null && child.signalCode === null) {
      child.kill('SIGKILL');
      let stopped = false;
      for (let attempt = 0; attempt < 100; attempt++) {
        const status = spawnSync('ps', ['-o', 'stat=', '-p', String(child.pid)], { encoding: 'utf8' });
        if (status.status === 1 || (status.status === 0 && status.stdout.trim().startsWith('Z'))) { stopped = true; break; }
      }
      if (!stopped) { console.error(`Replay child ${child.pid} did not stop; suite cleanup required`); process.exitCode = 1; continue; }
    }
    rmSync(directory, { recursive: true, force: true });
  }
});
for (const [signal, code] of [['SIGINT', 130], ['SIGTERM', 143]] as const) {
  process.on(signal, () => {
    if (exiting) return;
    exiting = true;
    void Promise.all([...owned.values()].map(runtime => runtime.stop())).then(
      () => process.exit(code), error => { console.error(error); process.exit(1); });
  });
}

export async function capture(connection: Connection, program: PublicKey, wallets: PublicKey[]): Promise<Capture> {
  if (!['127.0.0.1', 'localhost', '0.0.0.0'].includes(new URL(connection.rpcEndpoint).hostname)) throw new Error('Local RPC only');
  const result: Capture = new Map();
  for (const owner of [program, TOKEN_PROGRAM_ID]) {
    for (const { pubkey, account } of await connection.getProgramAccounts(owner, 'processed')) result.set(pubkey.toBase58(), account);
  }
  for (const key of [program, TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID, ...wallets]) {
    const account = await connection.getAccountInfo(key, 'processed');
    if (!account) throw new Error(`Missing captured account ${key}`);
    result.set(key.toBase58(), account);
    if (account.executable && account.owner.toBase58() === 'BPFLoaderUpgradeab1e11111111111111111111111') {
      const dataKey = new PublicKey(account.data.subarray(4, 36));
      const data = await connection.getAccountInfo(dataKey, 'processed');
      if (!data) throw new Error('Missing ProgramData');
      result.set(dataKey.toBase58(), data);
    }
  }
  return result;
}

// Adapter scenarios use short simulated epochs with the real Clock syscall.
// The captured provider bytes stay intact; this is not mainnet epoch behavior.
// Keep epoch 1057+ warps inside SlotHistory's window so the exact-clock
// snapshot restart retains genesis slot 0 and its status-cache entry.
export async function replay(accounts: Capture, at: number, exactClock = true, epoch?: number, ticksPerSlot = 64, slotsPerEpoch?: number) {
  if (exiting) throw new Error('Replay process is stopping');
  const rpcPort = Number(process.env.STAGE1_REPLAY_RPC_PORT ?? '18999');
  const faucetPort = Number(process.env.STAGE1_REPLAY_FAUCET_PORT ?? '18998');
  const dynamicPorts = process.env.STAGE1_REPLAY_DYNAMIC_PORTS ?? '20000-20100';
  const match = /^(\d+)-(\d+)$/.exec(dynamicPorts);
  const low = Number(match?.[1]), high = Number(match?.[2]);
  const reserved = [rpcPort, rpcPort + 1, faucetPort];
  if (!match || ![...reserved, low, high].every(p => Number.isInteger(p) && p > 0 && p <= 65535)
      || low > high || new Set(reserved).size !== reserved.length) throw new Error('Invalid replay port configuration');
  if (reserved.some(p => p >= low && p <= high)) throw new Error('Replay dynamic ports overlap RPC, WebSocket or faucet');
  // Linux hands ports in this range to outgoing connections (32768-60999 by
  // default); after minutes of RPC traffic one can hold a fixed port and the
  // validator fails to bind it. macOS starts at 49152, so it never shows locally.
  const ephemeral = kernelEphemeralPorts();
  if (ephemeral && (low <= ephemeral[1] && high >= ephemeral[0] || reserved.some(p => p >= ephemeral[0] && p <= ephemeral[1])))
    throw new Error(`Replay ports overlap the kernel ephemeral range ${ephemeral[0]}-${ephemeral[1]}`);
  const directory = mkdtempSync(join(process.env.STAGE1_REPLAY_ROOT ?? tmpdir(), 'stage1-genesis-replay-'));
  let child: ChildProcess | undefined;
  let closing = false;
  const active = () => { if (closing) throw new Error('Replay is stopping'); };
  const stopChild = async () => {
    const proc = child;
    if (!proc?.pid || proc.exitCode !== null || proc.signalCode !== null) return;
    const exited = new Promise<void>(resolve => proc.once('exit', () => resolve()));
    proc.kill('SIGTERM');
    await Promise.race([exited, pause(5000)]);
    if (proc.exitCode === null && proc.signalCode === null) { proc.kill('SIGKILL'); await exited; }
  };
  let stopping: Promise<void> | undefined;
  const stop = () => {
    closing = true;
    return stopping ??= (async () => {
      await stopChild();
      rmSync(directory, { recursive: true, force: true });
      owned.delete(directory);
    })();
  };
  const runtime = { child, stop };
  owned.set(directory, runtime);
  try {
    const keys = ['validator', 'vote-account', 'stake-account'].map(name => {
      const key = Keypair.generate();
      writeFileSync(join(directory, `${name}-keypair.json`), JSON.stringify(Array.from(key.secretKey)), { mode: 0o600 });
      return key.publicKey.toBase58();
    });
    const primordial: Record<string, unknown> = {};
    for (const [key, account] of accounts) primordial[key] = {
      balance: account.lamports, owner: account.owner.toBase58(), executable: account.executable,
      data: account.data.toString('base64'),
    };
    const file = join(directory, 'accounts.json');
    writeFileSync(file, JSON.stringify(primordial));
    const genesis = spawnSync('solana-genesis', [
      '--ledger', directory, '--cluster-type', 'development', '--creation-time', new Date(at * 1000).toISOString(),
      '--hashes-per-tick', 'sleep', '--ticks-per-slot', exactClock ? '64000' : String(ticksPerSlot),
      ...(slotsPerEpoch !== undefined ? ['--slots-per-epoch', String(slotsPerEpoch)] : epoch === undefined ? [] : ['--slots-per-epoch', '256']),
      '--bootstrap-validator', ...keys, '--primordial-accounts-file', file,
      '--faucet-pubkey', Keypair.generate().publicKey.toBase58(), '--faucet-lamports', '1000000000',
      '--max-genesis-archive-unpacked-size', '100000000',
    ], { encoding: 'utf8', env: { ...process.env, COPYFILE_DISABLE: '1' } });
    writeFileSync(join(directory, 'genesis.log'), genesis.stdout + genesis.stderr);
    if (genesis.status !== 0) throw new Error(`Genesis failed: ${genesis.stderr}`);
    const log = join(directory, 'process.log');
    // Loader upgrades/extensions retain their actual deployment slot in a
    // capture. Execute after it; otherwise Agave correctly treats that code as
    // not yet visible. Preserve all account bytes and the requested Clock.
    const loader = 'BPFLoaderUpgradeab1e11111111111111111111111';
    const programSlots = [...accounts.values()].filter(a => a.owner.toBase58() === loader
      && a.data.length >= 45 && a.data.readUInt32LE(0) === 3).map(a => Number(a.data.readBigUInt64LE(4)) + 1);
    const warpSlot = Math.max(epoch === undefined ? 32 : epoch * 256 + 32, ...programSlots);
    let launchError: Error | undefined;
    const launch = (warp: boolean): ChildProcess => {
      active();
      const logFd = openSync(log, 'a');
      const proc = spawn('solana-test-validator', [
        '--ledger', directory, '--rpc-port', String(rpcPort), '--faucet-port', String(faucetPort),
        ...(warp ? ['--warp-slot', String(warpSlot)] : []),
        '--bind-address', '127.0.0.1', '--dynamic-port-range', dynamicPorts, '--limit-ledger-size', '100000000', '--log',
      ], { stdio: ['ignore', logFd, logFd], env: { ...process.env, COPYFILE_DISABLE: '1' } });
      proc.once('error', error => { launchError = error; });
      closeSync(logFd);
      return proc;
    };
    const connection = new Connection(`http://127.0.0.1:${rpcPort}`, 'processed');
    const ready = async () => {
      let ready = false;
      for (let i = 0; i < 150; i++) {
        active();
        if (launchError) throw launchError;
        if (child!.exitCode !== null || child!.signalCode !== null) throw new Error(`Replay validator exited (${child!.exitCode ?? child!.signalCode}): ${readFileSync(log, 'utf8').slice(-12000)}`);
        try { await connection.getLatestBlockhash('processed'); ready = true; break; } catch { await pause(200); }
      }
      active();
      if (!ready) throw new Error(`Replay RPC unavailable: ${readFileSync(log, 'utf8').slice(-12000)}`);
    };
    const start = async (warp: boolean) => {
      for (let attempt = 1; attempt <= 3; attempt++) {
        active();
        launchError = undefined;
        child = runtime.child = launch(warp);
        try { await ready(); return; }
        catch (error) {
          await stopChild();
          active();
          const diagnostic = `Replay RPC readiness failed (attempt ${attempt}/3, warp=${warp}, rpc=${connection.rpcEndpoint}): ${error}`;
          if (attempt === 3) throw new Error(diagnostic);
          console.warn(diagnostic);
          await pause(250 * attempt);
        }
      }
    };
    await start(true);
    if (exactClock || programSlots.some(slot => slot > 1)) {
      // Reload the warp snapshot for exact Clock/program-cache visibility.
      // Normally ticking replays also prove progress below and reload if
      // PoH stalls. Never edit captured application or sysvar bytes.
      await stopChild(); active(); await start(false);
    }
    if (!exactClock) {
      // solana-genesis makes the identity the authorized voter. The test
      // validator loads only the vote-account key by default. Add this freshly
      // generated local identity through its admin RPC so finalized assertions
      // can advance. No captured application account is changed.
      for (let attempt = 1; attempt <= 3; attempt++) {
        const voter = spawnSync('agave-validator', ['--ledger', directory, 'authorized-voter', 'add',
          join(directory, 'validator-keypair.json')], { encoding: 'utf8' });
        if (voter.status !== 0) throw new Error(`Local voter setup failed (${voter.status ?? voter.signal}): ${voter.error ?? ''}\n${voter.stdout}\n${voter.stderr}\n${readFileSync(log, 'utf8').slice(-2000)}`);
        const initialSlot = await connection.getSlot('processed');
        let advancing = false;
        for (let i = 0; i < 50; i++) {
          active(); await pause(200);
          if (await connection.getSlot('processed') > initialSlot) { advancing = true; break; }
        }
        if (advancing) break;
        const diagnostic = `Replay bank stalled at slot ${initialSlot} (attempt ${attempt}/3, rpc=${connection.rpcEndpoint})`;
        if (attempt === 3) throw new Error(`${diagnostic}: ${readFileSync(log, 'utf8').slice(-12000)}`);
        console.warn(diagnostic);
        await stopChild(); active(); await start(false);
      }
    }
    const entries = [...accounts];
    for (let i = 0; i < entries.length; i += 100) {
      const batch = entries.slice(i, i + 100);
      const actual = await connection.getMultipleAccountsInfo(batch.map(([key]) => new PublicKey(key)), 'processed');
      batch.forEach(([key, before], j) => {
        const after = actual[j];
        if (!after || !after.data.equals(before.data) || !after.owner.equals(before.owner)
            || after.executable !== before.executable || after.lamports !== before.lamports) throw new Error(`Replay altered ${key}`);
      });
    }
    const advance = async (target: number, throughTime: number) => {
      if (exactClock || !slotsPerEpoch) throw new Error('Native clock advancement requires an explicit ticking local epoch');
      const genesis = await connection.getGenesisHash();
      await stopChild();
      const snapshot = spawnSync('agave-ledger-tool', ['create-snapshot','--ledger',directory,'--warp-slot',String(target),'ROOT',directory], {encoding:'utf8',timeout:60000});
      if (snapshot.status !== 0) throw new Error(`Native snapshot warp failed: ${snapshot.stderr.slice(-4000)}`);
      // Only this disposable validator's journal is rebuilt from its retained
      // vote account. Application and Clock bytes are never patched.
      const tower=join(directory,`tower-1_9-${keys[0]}.bin`);
      renameSync(tower,join(directory,`parked-${target}-${keys[0]}.bin`));
      await start(false);
      const voter=spawnSync('agave-validator',['--ledger',directory,'authorized-voter','add',join(directory,'validator-keypair.json')],{encoding:'utf8'});
      if (voter.status !== 0) throw new Error(`Local voter restart failed: ${voter.stderr}`);
      if (await connection.getGenesisHash() !== genesis) throw new Error('Native replay changed genesis');
      for (let i=0;i<240;i++) {
        const clock=await connection.getAccountInfo(new PublicKey('SysvarC1ock11111111111111111111111111111111'),'finalized');
        if (clock && Number(clock.data.readBigInt64LE(32))>=throughTime) return;
        await pause(250);
      }
      throw new Error('Finalized Clock did not cross requested local boundary');
    };
    return { connection, stop, directory, advance };
  } catch (error) { await stop(); throw error; }
}
