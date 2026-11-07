# On-Chain Schemas

> **⚠ SEVERELY STALE — DO NOT TRUST**
>
> This document describes an older chain generation (Segment / SegmentCounter / Claim / SwannySeat / Epoch accounts) that no longer exists. The current chain ontology is Climb + Vault + VaultStake + LocalLegend + VaultLeaderboard + RideAttestation (V4-B), governed by `docs/PROTOCOL_TRUTHS.md`.
>
> For current schema reference, see:
> - `protocol/anchor/programs/boulder_rollers/src/lib.rs` — source of truth for V4-A account shapes
> - `protocol/anchor/idl/boulder_rollers.json` — generated IDL
> - `docs/design/PROTOCOL_ALIGNMENT_FIX_PLAN.md` — WS-1 describes the target V4-B account model
>
> This doc needs to be deleted or fully regenerated. Tracked under the `wdvr.8` cleanup workstream.

## Accounts

- `UserState` (`seeds: ["user", owner]`): owner `Pubkey`; `cal_balance` `u64`; `cal_earned_today` `u64`; `last_cal_mint` `i64`; `total_rides` `u64`; `total_tss` `u64`; `bio_score` `u16`; `bump` `u8`.
- `SegmentCounter` (`seeds: ["counter"]`): `count` `u64`; `bump` `u8`.
- `Segment` (`seeds: ["segment", id_le]`): `id` `u64`; `creator` `Pubkey`; start/end lat/lon `i32` (lat/lon * 1e7); `distance_meters` `u32`; `elevation_gain` `u16`; `name` `[u8; 64]`; `description` `[u8; 256]`; `created_at` `i64`; `total_rides` `u64`; `total_staked` `u64`; `cal_burned` `u64`; `cover_photo_ipfs` `[u8; 64]`; `bump` `u8`.
- `Claim` (`seeds: ["claim", user, segment_id_le]`): `user` `Pubkey`; `segment` `u64`; `amount` `u64`; `lp_tokens` `u64`; `staked_at` `i64`; `last_harvest` `i64`; `bump` `u8`.
- `SwannySeat` (`seeds: ["swanny_seat", segment_id_le, seat_index]`): `segment` `u64`; `seat_index` `u8`; `holder` `Option<Pubkey>`; `locked_amount` `u64`; `locked_at` `i64`; `unlock_at` `i64`; `tasks_completed` `u8`; `bump` `u8`.
- `Epoch` (`seeds: ["epoch", segment_id_le, epoch_number_le]`): `segment` `u64`; `epoch_number` `u64`; `start_time` `i64`; `end_time` `i64`; `total_pot` `u64`; `leaderboard` `Vec<LeaderboardEntry>`; `distributed` `bool`; `bump` `u8`.
- `LeaderboardEntry` (embedded): `user` `Pubkey`; `time_seconds` `u32`; `tss` `u16`.

## Instructions (implemented)

- `initialize_user(payer)` → creates `UserState` PDA with defaults, `bio_score` starts at 1000.
- `mint_daily_cal(owner)` → mints 2_500 CAL once per UTC day to `UserState` (`cal_balance`, `cal_earned_today`, `last_cal_mint` updated; emits `CalMinted`).
- `burn_cal_for_segment(owner)` → burns 100 CAL from `UserState`, increments `segment.cal_burned`, and every 1_000 CAL mints 1 DUNG (9 decimals) into the segment pot using the segment PDA as mint authority.
- `initialize_counter(authority)` → creates global `SegmentCounter`.
- `create_segment(...)` → burns 100 DUNG from creator, charges 0.02 SOL to `treasury`, initializes `Segment` PDA using the current counter, and increments the counter (emits `SegmentCreated`).
- `initialize_segment_lp_mint(payer)` → creates LP mint PDA for a segment (authority = segment PDA, 9 decimals).
- `stake_in_segment(amount)` → transfers `amount` DUNG from staker to segment pot, mints LP pro‑rata (1:1 on first stake), initializes/updates Claim, and bumps `segment.total_staked`.
- `unstake_from_segment(lp_amount)` → burns LP from staker, transfers proportional DUNG back from pot with segment PDA as signer, updates Claim and `segment.total_staked`.

## Events

- `CalMinted { user, amount, timestamp }`
- `SegmentCreated { id, creator, start_lat, start_lon, end_lat, end_lon, timestamp }`
