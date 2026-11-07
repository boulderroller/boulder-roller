import { query } from './db';

/** Same atomic genesis/program high-water mark used by the backend. */
export async function persistProgramVersion(genesis: string, program: string, version: number): Promise<number> {
  const result = await query(
    'SELECT public.observe_program_version($1, $2, $3::smallint) AS highest_version',
    [genesis, program, version]
  );
  return result.rows[0]?.highest_version;
}
