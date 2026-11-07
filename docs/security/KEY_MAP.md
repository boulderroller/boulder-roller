# Boulder Roller Key Map

**Status:** Active devnet custody map  
**Last verified:** 2026-07-06  
**Scope:** Boulder Rollers devnet program `EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH`

This file maps keypair file names to their real protocol roles. It must never
contain raw key material.

## Current Devnet Keys

| Role | Public key | Local file | On-chain power | Rotation owner |
|---|---|---|---|---|
| Admin + upgrade authority | `G8DM5Dn12fsgkKxbdUUtFVJsqMXTcJqPU9no7koqwcKH` | `~/.config/solana/boulderroller-admin-upgrade-authority.json` | Program upgrade authority and `ProgramConfig.admin_authority` for config, migration, seed, override, and admin maintenance instructions. Not a fee payer. | Tim / protocol security |
| Backend authority | `CJz8PUyNVvLuXJvjsYXgSKD9utZVP2XoTEZq6M973Gha` | `~/.config/solana/boulderroller-backend-authority.json` | `ProgramConfig.backend_authority` for backend-attested operational writes such as ride attestations, CAL credits, climb completions, vault creation, settlement, and Balance-supported protocol actions. No program upgrade power. | Protocol security, then managed secret owner under `boulderroller-v2-ttkx` |
| Fee payer | `9h6UJdZqUPNnShaUHkSoxvEeZ7gBeNxzXGQcShhBnzEP` | `~/.config/solana/boulderroller-fee-payer.json` | Pays SOL fees and rent only. No `ProgramConfig` authority and no program upgrade authority. | Platform/security owner |

## Verification Commands

Use these commands to verify role mapping without printing secret material:

```bash
solana address -k ~/.config/solana/boulderroller-admin-upgrade-authority.json
solana address -k ~/.config/solana/boulderroller-backend-authority.json
solana address -k ~/.config/solana/boulderroller-fee-payer.json
solana program show EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH --url devnet
PYTHONPATH=backend python3 - <<'PY'
import asyncio
from app.solana_direct import get_program_config_account, load_readonly_config

async def main():
    cfg = load_readonly_config()
    config = await get_program_config_account(cfg)
    for key in ("admin_authority", "backend_authority"):
        print(f"{key}={config.get(key)}")

asyncio.run(main())
PY
```

Expected current devnet authority evidence:

| Check | Expected value |
|---|---|
| Program upgrade authority | `G8DM5Dn12fsgkKxbdUUtFVJsqMXTcJqPU9no7koqwcKH` |
| `ProgramConfig.admin_authority` | `G8DM5Dn12fsgkKxbdUUtFVJsqMXTcJqPU9no7koqwcKH` |
| `ProgramConfig.backend_authority` | `CJz8PUyNVvLuXJvjsYXgSKD9utZVP2XoTEZq6M973Gha` |

## Naming Rules

- Do not use `fee-payer` in the file name for any key that can administer or
  upgrade the program.
- Do not use the admin + upgrade authority as a hot fee payer.
- Runtime services should set both `FEE_PAYER_KEYPAIR` and
  `BACKEND_AUTHORITY_KEYPAIR`; the backend also supports
  `EXPECTED_BACKEND_AUTHORITY` as a fail-closed assertion.
- Managed secret migration remains tracked by `boulderroller-v2-ttkx`; exposed
  secret rotation remains tracked by `boulderroller-v2-2f9w`.

## Mainnet-Gate Multisig Plan

This plan is staged only. Do not execute it before the mainnet gate in
`boulderroller-v2-u82.6` is ratified.

1. Generate fresh mainnet authorities that have never appeared in repo history.
2. Create a Squads multisig with a threshold approved at the mainnet gate
   (default planning shape: 2-of-3 with Tim, a hardware-wallet signer, and an
   emergency/recovery signer).
3. Transfer the mainnet program upgrade authority to the Squads vault PDA.
4. Set `ProgramConfig.admin_authority` to the same Squads-controlled authority
   so config, seed, override, and migration instructions require a proposal.
5. Keep `backend_authority` separate as a managed operational signer; rotate it
   through `docs/runbooks/KEY_ROTATION.md` and `boulderroller-v2-ttkx`.
6. Keep the fee payer hot, low-balance monitored, and powerless. It should hold
   only SOL runway and no protocol authority.
7. Record the executed transaction signatures, Squads vault pubkey, member
   pubkeys, threshold, owners, and emergency procedure in this file before any
   mainnet rider-facing permanence copy is activated.

## Drift Response

If any public key no longer matches the file name or on-chain role:

1. Stop using the mismatched key for new deploys or sponsored execution.
2. Update the environment secret path to the correct role file.
3. If the wrong key was exposed or used in production, open or update
   `boulderroller-v2-2f9w`.
4. If the fix requires managed secret distribution work, update
   `boulderroller-v2-ttkx`.
5. Re-run the verification commands above and commit this file with the
   related code or docs change.
