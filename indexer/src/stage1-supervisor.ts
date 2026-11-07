import { transientRpcErrorClass } from './rpc-retry';

type Options = {
  stage1: () => Promise<unknown>;
  alert: (kind: string, attempts: number) => Promise<unknown>;
  intervalMs?: number | (() => number);
  delay?: (attempts: number, kind: string) => number;
  retryDeadlineMs?: () => number;
};

export function startStage1Supervisor(options: Options): { stop: () => void } {
  let stopped=false, failures=0, timer: ReturnType<typeof setTimeout>;
  const schedule=(ms:number) => { if(!stopped) timer=setTimeout(()=>{void tick();},ms); };
  const tick=async()=>{
    try {
      await options.stage1(); failures=0;
      schedule(typeof options.intervalMs==='function' ? options.intervalMs() : options.intervalMs??900_000);
    } catch(error) {
      const kind=transientRpcErrorClass(error)??'source_unavailable';failures++;
      // Never emit provider bodies/URLs or let alert storage kill the loop.
      console.warn(JSON.stringify({event:'stage1_indexer_held',kind,attempts:failures}));
      try { await options.alert(kind,failures); } catch { console.warn('Stage1 alert persistence unavailable'); }
      const base=kind==='rate_limit'?900_000:1_000;
      const cap=kind==='rate_limit'?21_600_000:900_000;
      const delay=options.delay?.(failures,kind)??Math.floor(Math.min(cap,base*2**Math.min(failures-1,16))*(0.5+Math.random()/2));
      schedule(Math.min(delay,options.retryDeadlineMs?.()??Infinity));
    }
  };
  schedule(0);
  return {stop:()=>{stopped=true;clearTimeout(timer);}};
}

/** Stage1 is supervised only after health and the legacy services are running. */
export async function startIndexerServices(options: Options & {health:()=>void;legacy:()=>Promise<unknown>}) {
  options.health();
  await options.legacy();
  return startStage1Supervisor(options);
}

/** Wake for both boundary banks even after a long projection-source hold. */
export function boundaryRetryDeadlineMs(now=Date.now()):number {
  const week=604800000,mondayNoon=388800000;
  const next=(Math.floor((now-mondayNoon)/week)+1)*week+mondayNoon;
  // Keep trying within the 90-second pre/post capture windows.
  if(next-now<=90_000||now-(next-week)<=90_000)return 30_000;
  return Math.max(1,next-90_000-now);
}
