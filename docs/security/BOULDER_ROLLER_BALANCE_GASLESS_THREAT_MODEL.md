# Boulder Roller Balance Gasless Threat Model

**Date:** 2026-06-11
**Status:** ACTIVE SECURITY GATE - rider-session amendment ratified 2026-07-17
**Bead:** `boulderroller-v2-0dff`
**Scope:** Boulder Roller Balance, gasless in-app execution, policy/delegate
authority, transaction coordination, and rider-facing state language

This document is the implementation gate for
[`BOULDER_ROLLER_BALANCE_GASLESS_EXECUTION.md`](../rfcs/BOULDER_ROLLER_BALANCE_GASLESS_EXECUTION.md).
It is narrower than the repository-wide
[`THREAT_MODEL.md`](./THREAT_MODEL.md): it covers the new gasless execution
target and the work needed before protocol, backend, Privy/delegate, portal,
and mobile changes land.

## Security Decision

Boulder Roller can make normal in-app economic actions feel gasless only when
the backend is not the thing that makes the action safe.

The acceptable model is:

1. Anchor constraints make invalid destinations, mints, treasuries, supply
   caps, replay, and authority misuse fail on-chain.
2. Balance-funded Vault value actions use a rider-configured on-chain session;
   Privy policy signers or SPL delegates are likewise scoped by program,
   instruction, asset, destination, amount, expiry, and revocation.
3. The backend transaction coordinator records intent, authority model,
   prepared message hash, policy/delegate id, confirmation state, projection
   state, retry count, and failure reason.
4. Primary rider UI shows Balance states such as `Counted`, `Collectable`,
   `Collected`, `Pending`, `Delayed`, and `Needs review`, not chain plumbing.
5. Wallet/security prompts remain for platform-boundary actions: add funds,
   withdraw to wallet, transfer out, export wallet, and authority changes.

The unacceptable model is "the server signs whatever the UI asked for." The
backend may pay fees or submit transactions, but it must not become a
discretionary custodian.

## Current Implementation Baseline

The June 2026 codebase has mixed authority patterns:

| Surface | Current shape | Gasless implication |
|---|---|---|
| `credit_cal` | Backend Authority gated by `ProgramConfig`, tied to `RideAttestation` and `CalMintReceipt` | Good model for backend-authorized actions |
| `record_climb_completion_v2` | Backend Authority gated by `ProgramConfig`, tied to `RideAttestation`, exact tribute-bound `ClimbCompletionReceiptV2`, and the ride tribute budget | Good model when action derives from attested ride state |
| `record_climb_completion` | Historical V1 ABI; fails closed because its receipt does not bind exact tribute | Never use as a fallback |
| `record_vault_completion` | Deprecated ABI compatibility entry point; always rejects with `InvalidRideAttestation` | Do not use; migrate remaining smoke/client helpers to the receipt-backed instruction |
| `stake_cal_in_vault` | `staker: Signer`, token transfer from rider CAL ATA into Vault CAL Escrow | Balance-funded successor uses rider-session authority; delegated or policy-signed paths remain separate no-prompt options |
| `unstake_cal_from_vault` | `staker: Signer`, LP burn and escrow CAL return | Needs separate in-app position withdrawal vs boundary withdrawal semantics |
| `harvest_rewards` | `staker: Signer`, DUNG minted to staker ATA, treasury fee enforced by `ProgramConfig` | Needs `collect_stake_rewards_for` or policy signer so destination can be enforced without a rider wallet popup |
| Vault route wallet flow | Server prepares tx, rider signs, backend compares submitted message bytes against prepared bytes | Keep for wallet-boundary fallback and malicious-client resistance |
| `SOLANA_STAKER_SECRET` fallback | Retired from normal stake/unstake API routes; direct Solana helpers remain isolated for devnet smoke scripts | Normal rider routes require prepared wallet-signed transactions until Balance/delegate/policy execution lands |
| Balance-funded Vault actions | RiderBalance custody plus a rider-configured `BalanceVaultAuthority` session; exact operation signed and nonce-consumed on-chain | Quiet execution is authorized, not permissionless; generic app, backend, fee payer, and login authority are rejected |

## Assets And Privileges

| Asset or privilege | Why it matters |
|---|---|
| Rider Account session | Opens private app state but must not itself authorize value leaving Boulder Roller |
| Protocol Wallet / Rider Wallet | Owns token accounts or embedded wallet authority |
| Boulder Roller Balance | Rider-facing balance backed by token accounts, escrows, PDAs, or projections |
| CAL token accounts and Vault CAL Escrow | Source of deposits, withdrawals, and vault positions |
| DUNG mint and DungMintState | Supply-cap and allocation integrity |
| USDC token accounts and protocol USDC treasury | Payment rail for vault creation or future app purchases |
| ProgramConfig | Source of backend authority, mints, treasury accounts, fees, and protocol constants |
| Backend Authority | Can commit attested economic consequences; compromise is high impact |
| Boulder Roller Fee Payer | Pays SOL fees; compromise is mostly fee-drain unless combined with another authority |
| Privy authorization key / policy signer | Can execute app-approved embedded-wallet transactions within policy scope |
| SPL delegate authority | Can transfer or burn up to delegated amount from a token account |
| Rider-session authority | Can sign only exact Balance-funded Vault intents while its on-chain generation, nonce, expiry, policy hash, and revocation state remain valid |
| Operation ledger | Evidence for support, retries, idempotency, and abuse response |
| Rider-facing copy | Prevents users from misunderstanding custody, wallet prompts, or finality |

## Trust Boundaries

| Boundary | Rule |
|---|---|
| Public root / unauth app entry -> authenticated app | Login grants account access only; it does not grant token movement authority |
| Rider Account -> Protocol Wallet | Wallet authority is separate from app session authority |
| RiderBalance custody -> value action | Custody proves the source and destination, not rider intent; the exact action requires a rider-created session or wallet fallback |
| Portal/mobile -> backend transaction coordinator | Client intent is untrusted until checked against server-side action rules |
| Backend coordinator -> Privy policy signer | The policy signer may only execute policies already granted by the user or account setup flow |
| Backend coordinator -> SPL delegate | Delegate allowance is limited and revocable; it is not a general rider wallet |
| Backend coordinator -> Anchor program | Anchor is the last line of defense; account constraints must reject bad destinations and mints |
| Solana RPC -> backend/indexer | RPC confirmation is chain evidence; indexer projection is read cache |
| Portal/mobile -> BoulderScan/admin/support | Primary rider copy hides chain plumbing; advanced surfaces may expose it accurately |

## Authority Classification

| Action | Target authority | Required security properties |
|---|---|---|
| Sign in | Rider Account auth | Email/social login cannot imply wallet authorization |
| Upload ride | Rider Account auth plus attestation pipeline | Upload consent is not token movement consent |
| Count CAL | Backend Authority | Tied to `RideAttestation`, amount match, `CalMintReceipt` replay guard |
| Record climb completion | Backend Authority | Tied to attested ride, completion receipt, ProgramConfig authority |
| Finalize settlement week | Backend Authority | One-way finalization, grace-window rules, per-bucket conservation |
| Collect DUNG | Permissionless-for-rider or policy signer | Destination is rider ATA or approved RiderBalance path; treasury and mint enforced |
| Deposit CAL | Rider session, policy signer, SPL delegate, or wallet fallback | Exact rider, Vault, CAL amount, expiry, generation, nonce, asset, and escrow enforced |
| Withdraw CAL from vault | Rider session, policy signer, SPL delegate, or wallet fallback | Exact LP amount and Vault; distinguish in-app position change from withdraw-to-wallet boundary |
| Create Vault | Rider session, policy signer, SPL delegate, or wallet-boundary fallback | Exact new Vault and configured CAL/USDC amounts; treasury and creator/minter identity enforced |
| Pay with USDC | Explicit rider session, policy signer, SPL delegate, or wallet fallback | USDC mint and treasury destination enforced; amount bounded |
| Add funds | Rider Wallet or high-assurance onramp | Boundary action; step-up or wallet confirmation expected |
| Withdraw to wallet / transfer out | Rider Wallet or high-assurance account auth | Boundary action; destination confirmation, step-up, and limits expected |
| Export wallet / change authority | Privy/Rider Wallet recovery controls | Highest assurance; never hidden inside normal ride/economy flows |

## Abuse Paths And Required Controls

| ID | Abuse path | Impact | Required controls | Gate |
|---|---|---|---|---|
| G-01 | Backend signs arbitrary rider-value movement | Critical custody break | Program constraints, coordinator allowlist, no server-held user key fallback | `boulderroller-v2-ihc1`, `boulderroller-v2-2n28` |
| G-02 | Policy signer compromise executes broader actions than intended | Theft or unauthorized state changes | Privy policies scoped to program, instruction, amount, recipient, expiry; monitor and revoke | `boulderroller-v2-jfm6` |
| G-03 | SPL delegate allowance is too broad or never revoked | Token drain within allowance | Use checked approvals, minimal allowance, single asset, explicit expiry/revoke path | `boulderroller-v2-jfm6` |
| G-04 | DUNG collection redirects rewards to attacker | Direct reward theft | Anchor-enforced recipient owner or RiderBalance destination; no client-supplied arbitrary recipient | `boulderroller-v2-vwdg`, `boulderroller-v2-jppk`, `boulderroller-v2-bctm` |
| G-05 | Treasury spoofing sends fees or USDC to wrong account | Protocol revenue theft | ProgramConfig treasury constraints; production coordinator must not trust env fallback | `boulderroller-v2-vwdg`, `boulderroller-v2-bfyz`, `boulderroller-v2-2n28` |
| G-06 | Mint or supply-cap bypass | Economic inflation | Mint auth PDAs, DungMintState `can_mint`, allocation bucket checks, cap tests | `boulderroller-v2-vwdg` |
| G-07 | Replay or duplicate execution | Double collection, double deposit, duplicate state | Operation id, idempotency key, prepared message hash, PDA receipts, retry-safe states | `boulderroller-v2-2n28` |
| G-08 | Projection says complete while chain failed or is delayed | User trust break and support risk | Separate confirmation and projection states; UI uses Pending/Delayed/Needs review | `boulderroller-v2-2n28`, `boulderroller-v2-p6gt` |
| G-09 | Email session alone authorizes withdraw/transfer/export | Boundary theft after account compromise | Step-up, wallet/security confirmation, limits, recovery locks for boundary actions | `boulderroller-v2-jfm6` |
| G-10 | Account recovery leaves old policy/delegate active | Post-recovery drain | Revoke or rotate policy/delegate authority during recovery, wallet unlink, and authority change | `boulderroller-v2-jfm6` |
| G-11 | Support/admin leaks private transaction, wallet, or policy details | Privacy and phishing risk | Support surfaces redact by default; raw details limited to admin/BoulderScan contexts | `boulderroller-v2-p6gt`, `boulderroller-v2-2n28` |
| G-12 | Rider copy reintroduces gas, transaction, signature, or explorer language in primary flows | Cognitive-load and consent confusion | Static copy gate with explicit allowlist for BoulderScan/admin/support/dev docs | `boulderroller-v2-p6gt` |
| G-13 | Fee payer drains through repeated sponsored attempts | Operational loss / denial of service | Rate limits, preflight eligibility, operation dedupe, fee budget alerts | `boulderroller-v2-2n28` |
| G-14 | Malicious client submits a changed signed transaction | Account misuse | Continue message-byte or prepared-message-hash comparison for wallet fallback paths | `boulderroller-v2-2n28` |
| G-15 | Any caller forces a Balance deposit, exit fee, or Vault purchase because custody is program-controlled | Unauthorized rider-value movement | Rider-signed session setup/rotation, exact operation hash, signer check, expiry, generation, sequential nonce, revocation, and wallet fallback | `boulderroller-v2-8348` |

## QA Gates

### Anchor Gates

Protocol work must include tests proving:

| Gate | Required proof |
|---|---|
| DUNG collection destination | `Collect DUNG` cannot send rewards outside the rider ATA or approved RiderBalance destination |
| Treasury enforcement | Protocol fee destination must equal `ProgramConfig.treasury_token_account` |
| Mint enforcement | CAL, DUNG, USDC, LP, and escrow accounts must match expected mints |
| Supply cap | DUNG minting fails when `DungMintState` or allocation caps would be exceeded |
| Idempotency | Replaying collection or receipt-protected actions cannot duplicate value |
| Delegate/policy scope | Any new delegated instruction must reject wrong program, wrong instruction, wrong vault, wrong asset, wrong destination, or over-limit amount |
| Rider-session scope | Balance-funded Vault actions reject generic app/backend/fee-payer signers, wrong signer/action/Vault/amount/generation, expiry, replay, revocation, and lifecycle resurrection |

### Backend Coordinator Gates

Backend work must include tests proving:

| Gate | Required proof |
|---|---|
| Authority classification | Every economic route is classified as backend-authorized, permissionless-for-rider, rider-session-signed, delegated/policy-signed, or wallet-boundary; app-balance custody alone is never authority |
| Operation ledger | Each attempt records operation id, authority model, asset, source/destination, idempotency key, prepared message hash, fee payer, policy/delegate id, signature, confirmation, projection, retry count, and failure reason |
| ProgramConfig source | Coordinator reads mints, treasuries, fees, and backend authority from chain/ProgramConfig for transaction construction |
| No server-held user key | Normal API routes cannot execute stake/unstake through `SOLANA_STAKER_SECRET` or equivalent user-key material |
| Retry safety | Retrying after RPC timeout, confirmation delay, or projection failure cannot submit a divergent operation |
| Rider state language | API responses expose `Counted`, `Collectable`, `Collected`, `Pending`, `Delayed`, and `Needs review` for primary app use |

The active backend contract for these gates is
[`BOULDER_ROLLER_BALANCE_TRANSACTION_COORDINATOR.md`](../rfcs/BOULDER_ROLLER_BALANCE_TRANSACTION_COORDINATOR.md).

### Privy And Delegate Gates

Auth/authority work must include tests or provider-backed fixtures proving:

| Gate | Required proof |
|---|---|
| Embedded-wallet policy signer | Policy IDs are attached to user embedded wallets only after account setup/login and are scoped to allowed Boulder Roller actions |
| Policy constraints | Policy rejects wrong program, wrong recipient, wrong amount, wrong asset, and expired action attempts |
| SPL delegate approval | External-wallet delegate approvals are limited to exact token account, mint, delegate, amount, and user-visible purpose |
| Revocation | Rider can revoke policy/delegate authority; backend refuses use after revocation or account recovery |
| Rider-session rotation | Rider wallet configures, rotates, and revokes the on-chain session; lock/recovery clears it and reactivation cannot resurrect it |
| Boundary step-up | Add funds, withdraw to wallet, transfer out, export wallet, and authority changes require wallet/security confirmation |
| Provider limitation | Exact Privy Solana policy enforcement for Boulder Rollers custom Anchor instructions is prototyped before production reliance; tracked by `boulderroller-v2-q7ze` |

The active authority model for these gates is
[`BOULDER_ROLLER_BALANCE_POLICY_DELEGATE_MODEL.md`](../rfcs/BOULDER_ROLLER_BALANCE_POLICY_DELEGATE_MODEL.md).

### Portal And Mobile Gates

Portal/mobile work must include static and Playwright/native checks proving:

| Gate | Required proof |
|---|---|
| Primary copy allowlist | Normal rider flows do not say gas, fee payer, transaction signature, sponsored transaction, explorer, proof, harvest, or unstake |
| Advanced copy boundary | BoulderScan, admin, support, and developer surfaces may expose chain details with accurate labels |
| Modeless state | Collect/deposit/withdraw/create/pay flows use inline state where possible; wallet/provider prompts appear only at boundary or explicit signer steps |
| Login separation | Email/social login never implies token movement authority |
| Projection honesty | UI distinguishes Pending, Delayed, Needs review, and final Collected states |

## Blockers And Sequencing

The gasless implementation can proceed in this order:

1. `boulderroller-v2-vwdg`: define protocol account/instruction model,
   especially `collect_stake_rewards_for` or equivalent. The active protocol
   gate is
   [`BOULDER_ROLLER_BALANCE_PROTOCOL_MODEL.md`](../rfcs/BOULDER_ROLLER_BALANCE_PROTOCOL_MODEL.md).
2. `boulderroller-v2-jppk`: implement the permissionless `Collect DUNG`
   successor and prove rider destination, treasury, mint, cap, and replay
   constraints.
3. `boulderroller-v2-bctm`: implement RiderBalance escrow and app-balance CAL
   movement for no-prompt `Deposit CAL` and `Withdraw CAL`.
4. `boulderroller-v2-8348`: require rider-scoped authority for every
   Balance-funded Vault value action. Status: ratified and implemented in ABI
   `0x44`, with exact-intent, replay, expiry, revocation, rotation, and lifecycle
   validator proof.
5. `boulderroller-v2-bfyz`: add canonical USDC mint, treasury, and payment
   constraints before no-prompt `Pay with USDC`.
6. `boulderroller-v2-jfm6`: define Privy policy signer and SPL delegate
   execution model, including revocation. Status: authority catalog and RFC
   landed; provider prototype follow-up remains required before Privy custom
   Anchor policy signing is treated as production-ready (`boulderroller-v2-q7ze`).
7. `boulderroller-v2-2n28`: implement backend transaction coordinator and
   operation ledger. Status: active coordinator contract, durable
   `balance_operations` table, and wallet-boundary vault route adapters landed.
8. `boulderroller-v2-p6gt`: align portal/mobile Balance state language and
   static copy gates.
9. End-to-end: prove collect/deposit/withdraw/create/pay flows in devnet with
   no primary gas/transaction/signature copy and no server-held rider key.

New P1 blocker from this review:

| Bead | Why it blocks |
|---|---|
| `boulderroller-v2-ihc1` | Completed: normal stake/unstake routes no longer load `SOLANA_STAKER_SECRET` or `SOLANA_STAKER_PATH`; the direct Solana helpers are isolated outside API fallback execution. |

No additional P0 blockers were found in this threat-model pass. The remaining
security requirements are covered by the existing gasless implementation beads
above plus `boulderroller-v2-ihc1`.

## References

- [`BOULDER_ROLLER_BALANCE_GASLESS_EXECUTION.md`](../rfcs/BOULDER_ROLLER_BALANCE_GASLESS_EXECUTION.md)
- [`BOULDER_ROLLER_BALANCE_PROTOCOL_MODEL.md`](../rfcs/BOULDER_ROLLER_BALANCE_PROTOCOL_MODEL.md)
- [`BOULDER_ROLLER_BALANCE_POLICY_DELEGATE_MODEL.md`](../rfcs/BOULDER_ROLLER_BALANCE_POLICY_DELEGATE_MODEL.md)
- [`BOULDER_ROLLER_BALANCE_TRANSACTION_COORDINATOR.md`](../rfcs/BOULDER_ROLLER_BALANCE_TRANSACTION_COORDINATOR.md)
- [`PROTOCOL_TRUTHS.md`](../PROTOCOL_TRUTHS.md)
- [`BACKEND_TRUTHS.md`](../BACKEND_TRUTHS.md)
- [`PORTAL_TRUTHS.md`](../PORTAL_TRUTHS.md)
- [`MOBILE_TRUTHS.md`](../MOBILE_TRUTHS.md)
- [`LANGUAGE_SPEC.md`](../design/LANGUAGE_SPEC.md)
- [`ANCHOR_SECURITY.md`](./ANCHOR_SECURITY.md)
- [`THREAT_MODEL.md`](./THREAT_MODEL.md)
- Privy wallet policies and controls: https://docs.privy.io/controls/policies/overview
- Privy Solana policy examples: https://docs.privy.io/controls/policies/example-policies/solana
- Privy user and server signers: https://docs.privy.io/recipes/wallets/user-and-server-signers
- Privy Solana transaction signing: https://docs.privy.io/wallets/using-wallets/solana/send-a-transaction
- Solana SPL Token delegate approval: https://solana.com/docs/tokens/basics/approve-delegate
- Solana SPL Token delegate revocation: https://solana.com/docs/tokens/basics/revoke-delegate
- Solana SPL Token transfer authority: https://solana.com/docs/tokens/basics/transfer-tokens
