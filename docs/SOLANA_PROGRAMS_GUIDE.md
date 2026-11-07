# Solana Programs Guide (Devnet)

**Latest protocol spec:** `history/BR_cal_allocation_refactor_spec.md`

## Programs (devnet)
- `boulder_rollers`: `EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH`

Legacy programs (`dung_mint`, `proof_verifier`) are archived under `archive/legacy/`.

## Mints
- **CAL mint**: SPL token (9 decimals). Devnet address `4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh`.
- **DUNG mint**: SPL token (9 decimals). Devnet address `CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk`. Mint authority = `DUNG_MINT_AUTH_PDA`.

## Core PDAs (boulder_rollers)
- ProgramConfig: `["program_config"]`
- Rider soul: `["rider_soul", rider]`
- Ride attestation: `["ride_attestation", rider, ride_hash]`
- CAL mint receipt: `["cal_mint_receipt", ride_attestation, rider]`
- Climb completion receipt V1/V2: `["climb_completion_receipt", ride_attestation, vault]` (same replay-guard PDA; distinct account discriminators)
- Ride tribute budget: `["ride_tribute_budget", ride_attestation]`
- CAL mint auth: `["cal_mint_auth"]`
- DUNG mint auth: `["dung_mint_auth"]`
- DUNG mint state: `["dung_mint_state"]`
- Vault: `["vault", vault_id_le]`
- Vault activation: `["vault_activation", vault_id_le]`
- Vault CAL escrow: `["vault_cal_escrow", vault_id_le]`
- Vault stake: `["vault_stake", vault_id_le, user]`

## Key Instructions (boulder_rollers)
- `credit_cal` → mint CAL directly to rider ATA, tied to a RideAttestation. Replaces the retired batch/claim path removed in V4-A.
- `record_climb_completion_v2` -> live receipt-backed Climb completion + Record Board / KOM update + exact Vault tribute credit. The program recomputes the V2 evidence hash before mutation.
- `record_climb_completion` (V1) and `record_vault_completion` were removed in program 0x4E; both had failed closed (no exact-tribute binding, no per-ride replay receipt).
- `stake_cal_in_vault` / `unstake_cal_from_vault` → CAL staking, eligibility gated by `VaultStake.effective_from_epoch` (stake becomes effective next Settlement Week).
- `harvest_rewards` → transfer `VaultStake.unclaimed_rewards` to staker ATA (5% fee).
- `distribute_epoch_rewards` → Settlement Week finalization with per-bucket direct allocation to Record Board / stakers / Local Legend / treasury / POL. *(Renames to `finalize_settlement_week` in V4-B.)*

## Notes
- CAL is minted directly per ride via `credit_cal`, with structural replay protection via `CalMintReceipt` PDAs keyed by `(ride_attestation, rider)`. The legacy batch/claim path was removed during the V4-A coherence redeploy.
- Completion V2 hashes `BR_CLIMB_COMPLETION_V2 || ride_attestation || vault || time_s_u32_le || cal_tribute_u64_le`. Historical V1 receipts remain readable only as identity evidence and cannot be resumed as exact amount evidence.
- DUNG is minted only via vault emissions at Settlement Week finalization, not per-ride.
