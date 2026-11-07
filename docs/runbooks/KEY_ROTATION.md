# Protocol Key Rotation

This runbook covers the repo-side expectations for the authority split. The
current role map lives in `docs/security/KEY_MAP.md`.

## Roles

- `FEE_PAYER_KEYPAIR`: pays rent and transaction fees
- `BACKEND_AUTHORITY_KEYPAIR`: signs privileged backend instructions
- `EXPECTED_BACKEND_AUTHORITY`: optional assertion guard; startup/config loading fails if the loaded backend authority pubkey does not match
- Admin + upgrade authority: stored separately from runtime keys and never used
  as a fee payer

## Supported Key Formats

The backend loaders accept all of the following for both fee payer and backend authority:

- inline JSON array of 64 keypair bytes
- base64-encoded raw 64-byte keypair
- base64-encoded JSON array
- filesystem path to a file containing any of the above

## Rotation Sequence

1. Generate a replacement backend authority keypair with a role-specific file
   name such as `boulderroller-backend-authority-YYYYMMDD.json`.
2. Update `ProgramConfig.backend_authority` on-chain using the admin authority.
3. Update `BACKEND_AUTHORITY_KEYPAIR` in secret storage.
4. Update `EXPECTED_BACKEND_AUTHORITY` to the new base58 pubkey.
5. Restart the backend.
6. Verify the next privileged transaction is signed by the new backend authority.

## Local Devnet File Names

Current devnet role-specific local files:

| Role | File |
|---|---|
| Admin + upgrade authority | `~/.config/solana/boulderroller-admin-upgrade-authority.json` |
| Backend authority | `~/.config/solana/boulderroller-backend-authority.json` |
| Fee payer | `~/.config/solana/boulderroller-fee-payer.json` |

Do not restore the old `boulderroller-v4a-fee-payer.json` name. That file name
was misleading because it held the admin + upgrade authority key.

## Safety Rule

Do not rotate the backend authority without also updating `EXPECTED_BACKEND_AUTHORITY`.
The assertion guard is there to fail closed if the wrong hot key lands in the environment.
