# RFC: Boulder Roller Balance Protocol Model

**Date:** 2026-06-11
**Status:** ACTIVE PROTOCOL MODEL - rider-session amendment ratified 2026-07-17
**Bead:** `boulderroller-v2-vwdg`
**Audience:** Protocol, backend, security, portal, mobile

This document locks the protocol shape for Boulder Roller Balance and gasless
in-app economic actions. It is the protocol gate for
[`BOULDER_ROLLER_BALANCE_GASLESS_EXECUTION.md`](./BOULDER_ROLLER_BALANCE_GASLESS_EXECUTION.md)
and the security companion to
[`BOULDER_ROLLER_BALANCE_GASLESS_THREAT_MODEL.md`](../security/BOULDER_ROLLER_BALANCE_GASLESS_THREAT_MODEL.md).

The core decision is:

**Boulder Roller may sponsor execution, but the Anchor program must still make
bad asset movement impossible.**

The backend can pay fees, prepare transactions, and submit retries. The backend
is not the safety boundary.

---

## 1. Current Anchor Baseline

The June 2026 program already has a useful split between attested actions and
rider-value movement:

| Surface | Current Anchor shape | Balance implication |
|---|---|---|
| `credit_cal` | Backend Authority is constrained by `ProgramConfig`; CAL mint and rider destination are checked against `RideAttestation` and `CalMintReceipt` | Keep as the backend-authorized model for `Counted` |
| `record_climb_completion_v2` | Backend Authority is constrained by `ProgramConfig`; the write is tied to `RideAttestation`, exact tribute-bound `ClimbCompletionReceiptV2`, and the ride tribute budget | Keep as the backend-authorized model for matched climb state |
| `record_climb_completion` | Historical V1 ABI; fails closed because its receipt does not bind exact tribute | Never use as a fallback |
| `record_vault_completion` | Deprecated ABI compatibility entry point; always rejects with `InvalidRideAttestation` | Do not use; migrate remaining smoke/client helpers to the receipt-backed instruction |
| `stake_cal_in_vault` | `staker: Signer` transfers CAL from rider ATA into Vault CAL Escrow and mints LP to rider ATA | Needs Balance/delegate/policy successors for normal no-prompt `Deposit CAL` |
| `unstake_cal_from_vault` | `staker: Signer` burns LP from rider ATA and returns CAL to rider ATA, minus exit fee | Needs Balance/delegate/policy successors and clearer boundary split |
| `harvest_rewards` | `staker: Signer` mints DUNG to staker DUNG ATA and fee DUNG to `ProgramConfig.treasury_token_account` | Needs a permissionless-for-rider successor |
| `create_vault` | Creator signs and burns DUNG from creator token account | Keep as wallet fallback; add Balance/delegate/policy successor |
| `create_vault_with_usdc` | Creator signs, burns CAL, transfers USDC, and creates vault | Needs explicit ProgramConfig USDC mint/treasury constraints before no-prompt use |
| `admin_create_vault` | Backend Authority creates an alpha/devnet vault and records unchecked creator as minter | Not a default rider Balance path |

The target is not to wrap these old instructions in a sponsored fee payer and
call that gasless. The target is to add successor shapes where the account
constraints carry the safety property.

---

## 2. Authority Rules

Every Balance instruction follows these rules:

1. **Fee payer is never value authority.** A sponsored transaction only proves
   who paid SOL.
2. **Rider Account auth is never token authority.** Login opens app state; it
   does not authorize value leaving Boulder Roller.
3. **Backend Authority is for attested consequences.** It can count CAL, record
   completions, and run settlement jobs. It is not generic rider consent.
4. **Permissionless-for-rider actions must be destination-constrained.** Anyone
   may trigger them only when the program proves the output belongs to the
   rider or an approved RiderBalance destination.
5. **Delegated/policy actions must be scoped by operation.** The program must
   reject wrong vaults, mints, token accounts, destinations, treasuries, and
   over-limit amounts.
6. **Wallet-boundary actions stay high assurance.** Add funds, withdraw to
   wallet, transfer out, export wallet, and authority changes remain explicit
   wallet/security events.
7. **Custody is not consent.** Program custody, a RiderBalance header, login,
   UI confirmation, Backend Authority, and fee payer authority cannot move
   rider value without a rider-created session or another explicit grant.
8. **Quiet does not mean permissionless.** Only an action whose enforced result
   cannot disadvantage the rider may be permissionless-for-rider. Deposit,
   withdrawal, payment, and Vault creation require scoped operation authority.

---

## 3. Balance Account Model

### 3.1 RiderBalance Header

Add a rider-scoped header account when moving beyond token-account projection:

```rust
pub const RIDER_BALANCE_SEED: &[u8] = b"rider_balance";

#[account]
pub struct RiderBalance {
    pub rider: Pubkey,
    pub status: RiderBalanceStatus,
    pub active_authority_model: BalanceAuthorityModel,
    pub policy_hash: [u8; 32],
    pub delegate_authority: Pubkey,
    pub last_authority_rotation_at: i64,
    pub revoked_at: i64,
    pub bump: u8,
}
```

Constraints:

- PDA seeds are `[RIDER_BALANCE_SEED, rider]`.
- `rider` is the Protocol Wallet / Rider Wallet that owns the Balance.
- `status` distinguishes active, locked, recovering, and revoked states.
- `policy_hash` is a non-secret commitment to provider-side policy state when
  a Privy embedded wallet policy is active.
- `delegate_authority` is either empty or the approved Boulder Roller Program
  Delegate PDA/key for SPL-delegate paths.
- `revoked_at > 0` blocks new delegated/policy Balance execution.

The header is not a custody account by itself. It is the protocol state that
binds a rider to Balance-controlled escrows and authority settings.

Implementation status (`boulderroller-v2-bctm`): Anchor now exposes
`initialize_rider_balance` and stores this header at
`[RIDER_BALANCE_SEED, rider]`.

### 3.2 RiderBalance Asset Escrows

Use mint-scoped token accounts owned by a RiderBalance authority PDA when assets
are actually inside Boulder Roller Balance:

```rust
pub const RIDER_BALANCE_AUTH_SEED: &[u8] = b"rider_balance_auth";
pub const RIDER_BALANCE_TOKEN_SEED: &[u8] = b"rider_balance_token";
```

Target token account constraints:

- `rider_balance.rider == rider.key()`
- token account seed includes `rider` and `mint`
- token account owner/authority is the RiderBalance authority PDA
- token account mint equals the expected `ProgramConfig` mint
- token movement out of the escrow is signed only by the program PDA

This is the cleanest app-native model for no-prompt `Deposit CAL`, `Withdraw
CAL`, `Create Vault`, and `Pay with USDC` after assets are already inside
Boulder Roller Balance.

Implementation status (`boulderroller-v2-bctm`): Anchor now exposes
`initialize_rider_balance_token` for mint-scoped RiderBalance token PDAs.
Backend builders derive the same accounts with
`_derive_rider_balance_pda`, `_derive_rider_balance_auth_pda`, and
`_derive_rider_balance_token_pda`.

### 3.3 Delegate-Backed Balance

For external-wallet riders, support SPL delegate execution as a transition
model:

- the rider grants a limited SPL delegate allowance on a specific token account
- the delegate is either a program PDA or a ProgramConfig-registered signer
- the instruction checks account owner, mint, delegate, delegated amount, vault,
  destination, and expiry/revocation state
- the backend records the delegate id and prepared operation, but does not
  become token authority

Delegate approval and revocation are part of the Privy/delegate gate
(`boulderroller-v2-jfm6`; see
[`BOULDER_ROLLER_BALANCE_POLICY_DELEGATE_MODEL.md`](./BOULDER_ROLLER_BALANCE_POLICY_DELEGATE_MODEL.md)),
but the Anchor program must reject mismatched assets, wrong destinations, and
stale/revoked Balance state.

### 3.4 Policy-Signed Balance

For Privy embedded-wallet riders, provider policy may make the rider wallet
sign without a visible wallet popup. On-chain this can still look like
`rider: Signer`; therefore it is not enough by itself.

Policy-signed instructions still need the same Anchor constraints as wallet
fallbacks:

- ProgramConfig mints and treasuries
- rider-owned or RiderBalance-owned source accounts
- exact vault escrow destinations
- amount ceilings supplied by the instruction and coordinator
- operation ledger entries in the backend transaction coordinator
- revocation checks before message construction

Privy policy is an execution mechanism. Anchor constraints are the safety
mechanism.

Status (`boulderroller-v2-jfm6`): the authority catalog now separates
embedded-wallet policy signing, external-wallet SPL delegation, rider-session
Balance execution, permissionless `Collect DUNG`, and wallet-boundary actions. Privy
custom Anchor instruction enforcement remains a provider prototype gate before
production reliance; that follow-up is tracked as `boulderroller-v2-q7ze`.

### 3.5 Rider-Session Balance Authority

ABI `0x44` adds a rider-and-program-derived `BalanceVaultAuthority` PDA for
Balance-funded Vault value actions. The rider wallet signs configuration,
rotation, and revocation. The session stores one signer, a nonzero policy hash,
generation, next nonce, expiry (at most seven days), revocation time, and the
last consumed operation ID. The RiderBalance header mirrors the active signer
and policy hash under the `RiderSession` authority model.

Every `deposit_cal_from_balance`, `withdraw_cal_to_balance`, and
`create_vault_from_balance_cal_usdc` call carries:

```rust
pub struct BalanceVaultOperationAuthorization {
    pub operation_id: [u8; 32],
    pub generation: u64,
    pub nonce: u64,
    pub expires_at: i64,
}
```

`operation_id` is the domain-separated SHA-256 of the exact program, rider,
session signer, action kind, Vault ID, primary and secondary base-unit amounts,
generation, nonce, and expiry. The configured session signer signs the
transaction. Anchor recomputes the ID, rejects stale, expired, revoked,
wrong-signer, wrong-action, wrong-Vault, and wrong-amount intents, increments
the nonce, and records the ID atomically. Lock, recovery, or RiderBalance
revocation clears the mirrored active authority. Returning to active does not
restore it; the rider must sign a fresh rotation. `AppBalance` remains a legacy
unconfigured enum value and authorizes none of these actions.

---

## 4. Collect DUNG

### 4.1 Target Instruction

Add a successor to `harvest_rewards`:

```rust
pub fn collect_stake_rewards_for(ctx: Context<CollectStakeRewardsFor>) -> Result<()>
```

`harvest_rewards` may remain as a wallet-boundary/dev fallback, but primary
rider flows should call the successor and say `Collect DUNG`.

### 4.2 Target Account Shape

```rust
#[derive(Accounts)]
pub struct CollectStakeRewardsFor<'info> {
    #[account(
        mut,
        seeds = [VAULT_SEED, &vault.id.to_le_bytes()],
        bump = vault.bump
    )]
    pub vault: Account<'info, Vault>,

    #[account(
        mut,
        seeds = [VAULT_STAKE_SEED, staker.key().as_ref(), &vault.id.to_le_bytes()],
        bump = vault_stake.bump,
        constraint = vault_stake.user == staker.key(),
        constraint = vault_stake.vault_id == vault.id
    )]
    pub vault_stake: Account<'info, VaultStake>,

    #[account(
        seeds = [VAULT_ACTIVATION_SEED, &vault.id.to_le_bytes()],
        bump = vault_activation.bump,
        constraint = vault_activation.is_active
    )]
    pub vault_activation: Account<'info, VaultActivation>,

    /// CHECK: Rider identity only; this account is not a signer.
    pub staker: UncheckedAccount<'info>,

    #[account(
        mut,
        constraint = dung_mint.key() == program_config.dung_mint
    )]
    pub dung_mint: Account<'info, Mint>,

    #[account(
        mut,
        constraint = staker_dung_account.mint == program_config.dung_mint,
        constraint = staker_dung_account.owner == staker.key()
    )]
    pub staker_dung_account: Account<'info, TokenAccount>,

    #[account(
        mut,
        constraint = protocol_treasury.key() == program_config.treasury_token_account,
        constraint = protocol_treasury.mint == program_config.dung_mint
    )]
    pub protocol_treasury: Account<'info, TokenAccount>,

    #[account(
        mut,
        seeds = [DUNG_MINT_STATE_SEED],
        bump = dung_mint_state.bump
    )]
    pub dung_mint_state: Account<'info, DungMintState>,

    #[account(
        seeds = [PROGRAM_CONFIG_SEED],
        bump = program_config.bump,
        constraint = program_config.initialized
    )]
    pub program_config: Account<'info, ProgramConfig>,

    /// CHECK: Derived from DUNG_MINT_AUTH_SEED.
    #[account(
        seeds = [DUNG_MINT_AUTH_SEED],
        bump = program_config.dung_mint_auth_bump
    )]
    pub dung_mint_auth: UncheckedAccount<'info>,

    #[account(mut)]
    pub payer: Signer<'info>,
    pub token_program: Program<'info, Token>,
}
```

A RiderBalance destination variant can replace `staker_dung_account` with:

```rust
#[account(
    seeds = [RIDER_BALANCE_SEED, staker.key().as_ref()],
    bump = rider_balance.bump,
    constraint = rider_balance.rider == staker.key(),
    constraint = rider_balance.revoked_at == 0
)]
pub rider_balance: Account<'info, RiderBalance>,

#[account(
    mut,
    seeds = [
        RIDER_BALANCE_TOKEN_SEED,
        staker.key().as_ref(),
        program_config.dung_mint.as_ref()
    ],
    bump,
    constraint = rider_balance_dung_account.owner == rider_balance_auth.key(),
    constraint = rider_balance_dung_account.mint == program_config.dung_mint
)]
pub rider_balance_dung_account: Account<'info, TokenAccount>,
```

That variant still derives the destination from the rider and DUNG mint; the
client cannot supply an arbitrary reward recipient.

### 4.3 Required Behavior

- `staker` is not a signer.
- `payer` can be Boulder Roller Fee Payer, Backend Authority, Policy Signer, or
  any relayer.
- `VaultStake` is derived from `staker` and the vault id.
- DUNG goes only to the rider DUNG ATA or the derived RiderBalance DUNG escrow.
- Fee DUNG goes only to `ProgramConfig.treasury_token_account`.
- `dung_mint` equals `ProgramConfig.dung_mint`.
- `DungMintState.can_mint(total_earned, AllocationBucket::Community)` must pass
  before minting.
- `VaultStake.rewards_earned` is reset atomically with minting.
- Replay after success fails with `NoRewardsToHarvest` or equivalent zero-claim
  behavior.

This is the cleanest permissionless-for-rider action because no value leaves the
rider's allowed destination set.

---

## 5. Deposit CAL

Primary rider language: `Deposit CAL`.

Protocol meaning: increase a rider's vault position by moving CAL into the
Vault CAL Escrow and updating `VaultStake`.

### 5.1 App-Balance Path

Implemented instruction:

```rust
pub fn deposit_cal_from_balance(
    ctx: Context<DepositCalFromBalance>,
    amount: u64,
    authorization: BalanceVaultOperationAuthorization,
) -> Result<()>
```

Required constraints:

- `RiderBalance` derives from the rider.
- source CAL escrow is RiderBalance-owned and mint equals `ProgramConfig.cal_mint`.
- destination is `[VAULT_CAL_ESCROW_SEED, vault.id]`.
- vault LP mint is `[VAULT_LP_MINT_SEED, vault.id]`.
- LP destination is the deterministic frozen rider-and-Vault position account
  owned by `VaultStake`, not an arbitrary client-supplied token account.
- `VaultStake` derives from the rider and vault.
- sponsor/payer only funds rent and fees.
- `BalanceVaultAuthority` derives from the rider; its configured signer signs
  an exact deposit intent and consumes the current nonce.

The Balance path mints LP into the same deterministic, Vault-frozen position
custody used by wallet deposits. Its amount must equal `VaultStake.lp_tokens`.

Backend builder: `make_deposit_cal_from_balance_ix`. The builder marks the
rider as non-signer, derives the Balance CAL source and Balance LP destination,
and keeps `sponsor_authority` as the rent/fee signer.

### 5.2 Delegate Path

Target instruction:

```rust
pub fn deposit_cal_with_delegate(ctx: Context<DepositCalWithDelegate>, amount: u64) -> Result<()>
```

Required constraints:

- source token account owner is the rider.
- source mint equals `ProgramConfig.cal_mint`.
- delegate equals the approved Boulder Roller Program Delegate or registered
  policy signer.
- delegated amount is at least `amount`.
- destination is the exact Vault CAL Escrow PDA.
- `VaultStake` derives from rider and vault.
- the operation is rejected when the related RiderBalance authority state is
  revoked, expired, locked, or recovering.

### 5.3 Wallet Fallback

The current `stake_cal_in_vault` shape can remain as wallet fallback while the
Balance paths land. It should not be used as the default primary flow once the
Balance transaction coordinator is active.

---

## 6. Withdraw CAL

Primary rider language has two distinct meanings:

| Rider wording | Protocol meaning | Wallet/security prompt |
|---|---|---|
| `Withdraw CAL` | Decrease vault position and return CAL to Boulder Roller Balance | No in target |
| `Withdraw to wallet` | Move CAL out of Boulder Roller Balance to an external wallet account | Yes / high assurance |

### 6.1 App-Balance Path

Implemented instruction:

```rust
pub fn withdraw_cal_to_balance(
    ctx: Context<WithdrawCalToBalance>,
    lp_amount: u64,
    authorization: BalanceVaultOperationAuthorization,
) -> Result<()>
```

Required constraints:

- `VaultStake` derives from rider and vault.
- LP source is the deterministic frozen rider-and-Vault position account whose
  token authority is `VaultStake`.
- CAL destination is RiderBalance CAL escrow, not arbitrary client input.
- Vault CAL Escrow source is `[VAULT_CAL_ESCROW_SEED, vault.id]`.
- exit fee calculation and burn stay identical to current
  `unstake_cal_from_vault`.
- the configured rider-session signer authorizes the exact LP amount; the
  program-controlled `VaultStake` PDA remains SPL burn authority.

Backend builder: `make_withdraw_cal_to_balance_ix`. The builder marks the
rider as non-signer and returns CAL only to the derived RiderBalance CAL token
PDA; fee payer signing is handled at transaction assembly time, not as an
Anchor account.

### 6.2 Delegate Path

When LP is in a rider-owned LP ATA, delegate-backed withdrawal must prove:

- LP account owner is the rider.
- LP account mint is `[VAULT_LP_MINT_SEED, vault.id]`.
- delegate is approved and allowance covers `lp_amount`.
- CAL return destination is either rider-owned CAL ATA or RiderBalance CAL
  escrow, depending on whether the UI action is `Withdraw CAL` or `Withdraw to
  wallet`.

### 6.3 Boundary Path

Moving assets from Boulder Roller Balance to an arbitrary external wallet is
not the same action as reducing a vault position. It remains high assurance and
belongs to settings/account/payment flows, not the normal climb economy loop.

---

## 7. Create Vault

Primary rider language: `Create Vault`.

The creator/minter identity must remain the rider. A backend-sponsored vault
creation that records an unchecked `creator` is acceptable for alpha/devnet
seeding and admin operations, but not as the default rider Balance path.

### 7.1 App-Balance DUNG Path

Target instruction:

```rust
pub fn create_vault_from_balance_dung(ctx: Context<CreateVaultFromBalanceDung>, ...) -> Result<()>
```

Required constraints:

- `RiderBalance` derives from creator.
- DUNG source is RiderBalance-owned and mint equals `ProgramConfig.dung_mint`.
- burn amount equals `ProgramConfig.vault_creation_dung`.
- created `Vault.minter` equals rider.
- `sponsor_authority` pays rent only.
- `VaultCounter`, `Vault`, `LocalLegend`, and `VaultActivation` seeds stay
  canonical.

### 7.2 App-Balance CAL Plus USDC Path

Target instruction:

```rust
pub fn create_vault_from_balance_cal_usdc(
    ctx: Context<CreateVaultFromBalanceCalUsdc>,
    ...,
    authorization: BalanceVaultOperationAuthorization,
) -> Result<()>
```

Required constraints:

- CAL source is RiderBalance-owned and mint equals `ProgramConfig.cal_mint`.
- USDC source is RiderBalance-owned and mint equals `ProgramConfig.usdc_mint`.
- USDC destination equals `ProgramConfig.usdc_treasury_token_account`.
- CAL burn/debit amount equals `ProgramConfig.vault_creation_cal`.
- USDC amount equals `ProgramConfig.vault_creation_usdc` or another configured
  ProgramConfig amount.
- created `Vault.minter` equals rider.
- the rider-session signer authorizes the exact new Vault ID and configured CAL
  and USDC base-unit amounts under the current generation and nonce.

Status: implemented in `boulderroller-v2-bfyz`.

- `ProgramConfig` stores `usdc_mint`, `usdc_treasury_token_account`, and
  `vault_creation_usdc`.
- `configure_usdc_payment` is admin-only and configures the canonical USDC mint,
  treasury token account, and amount.
- Existing wallet-signed `create_vault_with_usdc` now rejects spoofed CAL mint,
  USDC mint, source ownership, treasury account, treasury mint, and amount
  drift by using `ProgramConfig.vault_creation_usdc`.
- `create_vault_from_balance_cal_usdc` creates the vault with the rider as
  `Vault.minter`, burns configured CAL from the rider's RiderBalance CAL token
  PDA, and transfers configured USDC from the rider's RiderBalance USDC token
  PDA to the configured USDC treasury.
- To stay under the SBF account-validator stack limit, the Balance path passes
  the session signer, session PDA, configured USDC treasury token account, and
  CAL mint as required trailing accounts. The instruction checks the signature,
  derives and decodes the session PDA, and validates both token accounts against
  `ProgramConfig` before any CPI.

### 7.3 Delegate/Policy Path

When the creator pays from an external wallet token account through delegate or
policy authority, the program must enforce the same mints, amounts, destination
treasuries, and creator identity. The signer mechanism changes; the account
constraints do not.

---

## 8. Pay with USDC

USDC is a payment rail, not the ride-loop currency.

Target semantics:

- USDC source is either RiderBalance USDC escrow, a Privy policy-signed wallet
  token account, or an SPL-delegated wallet token account.
- USDC mint is canonical in ProgramConfig or an equivalent immutable config.
- USDC destination is canonical in ProgramConfig or an equivalent immutable
  config.
- payment amount comes from ProgramConfig or a signed server-side quote whose
  quote id is logged by the transaction coordinator.
- successful payment changes the intended app object exactly once.

`boulderroller-v2-bfyz` adds the explicit USDC config and Balance-funded
successor required before `Pay with USDC` or USDC vault creation can become a
primary no-prompt UX. Policy/delegate signing and transaction-coordinator quote
logging remain later execution-layer work.

---

## 9. Revocation And Recovery

Revocation is split across layers:

| Layer | Responsibility |
|---|---|
| Anchor | Reject locked, revoked, recovering, expired, wrong delegate, wrong mint, wrong vault, wrong destination, and over-limit operations |
| Backend coordinator | Stop preparing operations after revocation/recovery; record old policy/delegate id and rejection reason |
| Privy/provider | Revoke embedded-wallet policy signer authorization |
| Wallet/SPL Token | Revoke SPL delegate allowances |
| Portal/mobile | Show calm account/security states without gas/transaction/explorer language in primary flows |

On-chain revocation state cannot prove provider policy has been revoked, but it
can stop Boulder Roller from using stale policy/delegate paths after an account
recovery or security lock.

For the rider-session path, revocation is fully on-chain: the rider-signed
revoke advances generation, expires the session, resets its nonce, and clears
the RiderBalance mirror. Recovery and lock clear the mirror as well. A later
active status is insufficient until the rider signs a new configuration or
rotation.

---

## 10. Anchor Test Gates

The protocol implementation gate must prove:

| Gate | Required proof |
|---|---|
| Permissionless DUNG destination | `collect_stake_rewards_for` succeeds without `staker` signer and cannot mint to an attacker account |
| Treasury enforcement | DUNG fee and USDC payment destinations must equal ProgramConfig treasuries |
| Mint enforcement | CAL, DUNG, USDC, LP, RiderBalance token accounts, and Vault escrows reject wrong mints |
| Vault escrow enforcement | CAL deposits can only enter `[VAULT_CAL_ESCROW_SEED, vault.id]` |
| Supply cap | DUNG collection fails when `DungMintState` or community caps would be exceeded |
| Idempotency | Replaying collection after success cannot duplicate DUNG |
| Rider-session authority | Generic app-balance, backend, fee payer, wrong signer, wrong generation, and reactivated old sessions cannot move rider value |
| Exact operation intent | Action, Vault, every base-unit amount, expiry, generation, and nonce are hash-bound; tamper, expiry, and replay fail |
| Delegate scope | Delegate-backed deposit/withdraw/create/pay rejects wrong delegate, expired state, wrong vault, wrong asset, and over-limit amount |
| Boundary separation | Withdraw-to-wallet is not silently routed through in-app `Withdraw CAL` |

---

## 11. Landing Sequence

1. Land this protocol model (`boulderroller-v2-vwdg`).
2. Implement the permissionless `Collect DUNG` protocol successor
   (`boulderroller-v2-jppk`), including rider-destination, treasury, DUNG mint,
   supply-cap, and replay constraints.
3. Implement RiderBalance escrow and app-balance CAL movement
   (`boulderroller-v2-bctm`) before app-native `Deposit CAL` and `Withdraw CAL`
   become primary no-prompt flows. Status: Anchor successor instructions,
   IDL/client, backend builders, and protocol/backend parity tests landed.
4. Add canonical USDC ProgramConfig/payment constraints
   (`boulderroller-v2-bfyz`) before `Pay with USDC` or USDC vault creation
   becomes primary no-prompt UX.
5. Require rider-scoped on-chain authority for Balance-funded Vault value
   actions (`boulderroller-v2-8348`). Status: ratified and implemented in ABI
   `0x44`; exact intent, expiry, generation, nonce, revocation, rotation, and
   lifecycle non-resurrection are validator-proven.
6. Land Privy/delegate policy design (`boulderroller-v2-jfm6`) against the same
   account constraints. Status: authority catalog and RFC landed; provider
   prototype follow-up is required for exact Privy Solana policy enforcement on
   Boulder Rollers custom Anchor instructions and is tracked as
   `boulderroller-v2-q7ze`.
7. Build the backend transaction coordinator (`boulderroller-v2-2n28`) so route
   behavior follows the authority model instead of old prepare/sign/submit
   assumptions. Status: active coordinator contract, durable operation table,
   and wallet-boundary vault route adapters landed in
   [`BOULDER_ROLLER_BALANCE_TRANSACTION_COORDINATOR.md`](./BOULDER_ROLLER_BALANCE_TRANSACTION_COORDINATOR.md).
8. Align portal/mobile state language (`boulderroller-v2-p6gt`) after the
   backend can return honest `Counted`, `Collectable`, `Collected`, `Pending`,
   `Delayed`, and `Needs review` states.
9. Retire or production-block the `SOLANA_STAKER_SECRET` fallback
   (`boulderroller-v2-ihc1`) before any primary gasless Balance execution ships.
   Status: normal stake/unstake API routes no longer load server-held rider key
   material; unsigned route calls require a prepared wallet-signed transaction
   until Balance/delegate/policy execution lands.

The protocol surface is now specific enough for implementation. The remaining
open security-sensitive items are tracked in the threat model and the follow-up
implementation beads, not as product ambiguity.
