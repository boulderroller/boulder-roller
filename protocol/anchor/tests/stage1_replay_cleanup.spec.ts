// Process/filesystem fixtures only. No chain state or validator behavior is simulated as evidence.
import { expect } from 'chai';
import { spawn, spawnSync } from 'child_process';
import { mkdtempSync, writeFileSync, existsSync, readdirSync, rmSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

function running(pid: number) {
  const state = spawnSync('ps', ['-o', 'stat=', '-p', String(pid)], { encoding: 'utf8' });
  return state.status === 0 && !state.stdout.trim().startsWith('Z');
}

describe('Stage1 replay process cleanup', () => {
  for (const mode of ['stop', 'failure', 'exit', 'SIGINT', 'SIGTERM', 'restart-SIGTERM', 'retry', 'stalled', 'port-overlap']) it(`removes its ledger and stops its validator on ${mode}`, async () => {
    const root = mkdtempSync(join(tmpdir(), 'stage1-cleanup-test-'));
    const sentinel = join(root, 'unrelated'); writeFileSync(sentinel, 'keep');
    let record: any, child: ReturnType<typeof spawn> | undefined;
    const records: any[] = [];
    const fixture = `
      import cp from 'node:child_process';
      import {syncBuiltinESMExports} from 'node:module';
      import {Connection} from '@solana/web3.js';
      const spawn = cp.spawn, spawnSync = cp.spawnSync;
      let validator;
      let launches = 0;
      let injected = false;
      cp.spawn = (command, args, options) => {
        if (command !== 'solana-test-validator') return spawn(command,args,options);
        launches++;
        validator = spawn(process.execPath, ['-e', ${JSON.stringify(mode)} === 'retry' && launches === 1 ? 'process.exit(1)' : 'setInterval(()=>{},1000)'], {stdio:'ignore'});
        if (${JSON.stringify(mode)} === 'restart-SIGTERM') {
          console.log(JSON.stringify({directory:args[args.indexOf('--ledger')+1],pid:validator.pid}));
          const kill = validator.kill.bind(validator);
          validator.kill = signal => {
            if (signal === 'SIGTERM' && !injected) {
              injected = true; process.kill(process.pid, 'SIGTERM');
              setTimeout(()=>kill(signal),100); return true;
            }
            return kill(signal);
          };
        }
        return validator;
      };
      cp.spawnSync = (command,args,options) => ['solana-genesis','agave-validator'].includes(command)
        ? {status:0,stdout:'',stderr:''} : spawnSync(command,args,options);
      syncBuiltinESMExports();
      Connection.prototype.getLatestBlockhash = async () => {
        if (${JSON.stringify(mode)} === 'retry' && launches === 1) throw new Error('RPC not ready');
        return {blockhash:'fixture',lastValidBlockHeight:1};
      };
      let slot = 32;
      Connection.prototype.getSlot = async () => ${JSON.stringify(mode)} === 'stalled' && launches === 1 ? 32 : ++slot;
      const {replay} = await import(${JSON.stringify(new URL('./helpers/stage1_replay.ts', import.meta.url).href)});
      if (${JSON.stringify(mode)} === 'port-overlap') process.env.STAGE1_REPLAY_DYNAMIC_PORTS = '19000-19100';
      const runtime = await replay(new Map(),1791201600,${mode === 'restart-SIGTERM'});
      console.log(JSON.stringify({directory:runtime.directory,pid:validator.pid}));
      if (${JSON.stringify(mode)} === 'stalled' && await runtime.connection.getSlot() <= 32) throw new Error('Accepted a stalled replay bank');
      if (${JSON.stringify(mode)} === 'port-overlap') throw new Error('Accepted overlapping ports');
      if (['stop','retry','stalled'].includes(${JSON.stringify(mode)})) {await runtime.stop();process.exit(0);}
      if (${JSON.stringify(mode)} === 'failure') throw new Error('intentional test failure');
      if (${JSON.stringify(mode)} === 'exit') process.exit(23);
      setInterval(()=>{},1000);
    `;
    try {
      child = spawn(process.execPath, ['--loader', 'ts-node/esm', '--no-warnings', '--input-type=module', '-e', fixture],
        { env: { ...process.env, NODE_OPTIONS: '', STAGE1_REPLAY_ROOT: root,
          STAGE1_REPLAY_RPC_PORT: '18999', STAGE1_REPLAY_FAUCET_PORT: '18998', STAGE1_REPLAY_DYNAMIC_PORTS: '20000-20100' }, stdio: ['ignore', 'pipe', 'pipe'] });
      let output = '', error = '';
      child.stdout!.on('data', chunk => {
        output += chunk;
        const lines = output.split('\n'); output = lines.pop()!;
        for (const line of lines.filter(line => line.startsWith('{"directory"'))) {
          const next = JSON.parse(line); records.push(next);
          if (!record) { record = next; if (mode.startsWith('SIG')) child!.kill(mode as NodeJS.Signals); }
        }
      });
      child.stderr!.on('data', chunk => { error += chunk; });
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => { child!.kill('SIGKILL'); reject(new Error('Fixture timed out')); }, 20000);
        child!.once('error', reject); child!.once('close', () => { clearTimeout(timer); resolve(); });
      });
      if (mode === 'port-overlap') {
        expect(error).include('Replay dynamic ports overlap RPC, WebSocket or faucet');
        expect(records).to.have.length(0);
      } else expect(record, error).to.exist;
      if (mode === 'stalled') expect(child.exitCode, error).eq(0);
      for (const item of records) {
        expect(existsSync(item.directory), 'replay ledger survived process exit').to.equal(false);
        expect(running(item.pid), 'validator survived its owner').to.equal(false);
      }
      expect(readdirSync(root)).to.deep.equal(['unrelated']);
      expect(existsSync(sentinel)).to.equal(true);
    } finally {
      if (child && child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
      for (const item of records) { if (running(item.pid)) process.kill(item.pid, 'SIGKILL'); rmSync(item.directory, { recursive: true, force: true }); }
      rmSync(root, { recursive: true, force: true });
    }
  });
});
