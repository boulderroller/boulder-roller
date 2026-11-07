# Recovering a rejected service version observation

The Stage 1 backend and indexer accept exactly `0x4C` (76) and `0x4D` (77).
They validate that window before calling the shared monotonic observation
function. Rejected reads fail closed without changing the durable row; the
next valid read can recover. A supported 77-to-76 downgrade remains an error.

Use this repair only if the earlier Round 2 service code persisted an
unsupported byte into `public.program_version_observations`, pinning both
services despite an honest supported ProgramConfig. It is not a rollback
procedure and must never erase a legitimately observed supported version.

1. Stop both services and install the corrected code before restarting either.
   Otherwise an old process can restore the bad maximum during the repair.
2. Independently verify the intended network's genesis hash, program ID, and
   finalized ProgramConfig through a trusted RPC source. It must be at 76 or
   77. If the chain actually advanced beyond this release's window, deploy
   compatible services instead of resetting the row.
3. Inspect the exact observation row and retained health/deployment evidence.
   Recover the highest **supported** version previously observed, at least the
   currently verified supported chain version. If 77 was ever observed, retain
   77; a chain now at 76 must continue to fail. If that history is uncertain,
   preserve 77 until the history is established.
4. Run the following single atomic statement using the database owner. Replace
   the two identity strings and the two example version numbers with the
   verified values. This example repairs an unsupported 255 to the supported
   high-water mark 77. It cannot lower an existing supported row or touch a
   different genesis/program pair.

```sql
WITH verified_repair AS (
    SELECT 'REPLACE_WITH_VERIFIED_GENESIS_HASH'::text AS genesis_hash,
           'REPLACE_WITH_VERIFIED_PROGRAM_ID'::text AS program_id,
           255::smallint AS expected_rejected_version,
           77::smallint AS recovered_high_water
)
UPDATE public.program_version_observations AS observed
SET highest_version = repair.recovered_high_water
FROM verified_repair AS repair
WHERE observed.genesis_hash = repair.genesis_hash
  AND observed.program_id = repair.program_id
  AND observed.highest_version = repair.expected_rejected_version
  AND observed.highest_version NOT IN (76, 77)
  AND repair.recovered_high_water IN (76, 77)
RETURNING observed.genesis_hash, observed.program_id, observed.highest_version;
```

Exactly one row should be returned. If no row is returned, recheck the scoped
identity and recorded value; do not broaden the update. Retain the before/after
values and the verified chain evidence with the incident.

Restart both services to discard the earlier process's invalid in-memory
state. Confirm backend `/health/chain`, indexer `/status`, then indexer
`/health` report the supported version and expected Stage 1 availability.
Keep migration **169** for this release; the later keeper branch renumbers
its conflicting migration. This procedure changes no account projection and
submits no chain transaction.
