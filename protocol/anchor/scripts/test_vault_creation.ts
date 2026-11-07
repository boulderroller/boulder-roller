/**
 * Retired V4-A helper.
 *
 * Vault creation no longer accepts a locally generated signature, name, or
 * metrics. Register a verified post-publish registry row with
 * `register_ratified_climb.ts`, then use the Anchor integration tests to create
 * the Vault from that immutable Climb PDA.
 */

console.error(
  'disabled: arbitrary Vault identity is not a V4-B path; use '
  + 'scripts/register_ratified_climb.ts --row <ratified-row.json> first',
);
process.exit(1);
