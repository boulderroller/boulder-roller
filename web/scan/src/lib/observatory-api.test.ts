import {afterEach,expect,it,vi} from 'vitest';
afterEach(()=>{vi.unstubAllEnvs();vi.unstubAllGlobals();vi.resetModules()});
it('never substitutes fixture money into a failed live page request',async()=>{
 vi.stubEnv('VITE_USE_SCAN_FIXTURES','false');
 vi.stubEnv('VITE_ALLOW_FIXTURE_FALLBACK','true');
 vi.stubEnv('DEV',true);
 vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new Error('offline')));
 vi.resetModules();
 const {getObservatory}=await import('./api');
 await expect(getObservatory()).rejects.toThrow('offline');
});
