# RFC: Boulder Roller Balance Policy And Delegate Model

**Date:** 2026-06-11
**Status:** ACTIVE AUTHORITY MODEL - rider-session amendment 2026-07-17
**Bead:** `boulderroller-v2-jfm6`
**Audience:** Protocol, backend, portal, mobile, security

This document defines the scoped execution model for Boulder Roller Balance.
It closes the design gap between "wallet signs every economic action" and
"the server signs whatever the app asks for."

The decision is:

**Normal in-app Balance actions may be policy-signed or delegated only when the
program, provider policy, delegate allowance, coordinator, and revocation path
all describe the same narrow operation.**

Login opens app state. It does not grant token movement authority.

---

## 1. Provider Capability Snapshot

Privy supports user embedded wallets with app-controlled server signers, policy
IDs, app authorization keys, and server-side execution. On Solana, Privy policy
examples include conditions for program id, token-program instruction name,
`TransferChecked` mint, `TransferChecked` amount, recipient-like account rules,
time windows, and chain/network controls. Privy also supports Solana gas
sponsorship through an app-managed fee payer where the app signs and submits the
transaction while the user wallet remains the value authority.

Solana SPL Token supports checked delegate approval and revocation. A token
account can have a delegate with a delegated amount; the owner signs approval
and revocation, and transfer authority may be either the owner or the delegate
when the delegated allowance is sufficient.

The provider-limitation call:

Privy's public Solana policy examples are strong enough for token-program
policy shape. The `boulderroller-v2-q7ze` prototype now records the custom
Anchor limitation: public provider evidence is not sufficient to treat Privy
policy as the only guard for custom Anchor instruction names, account roles,
amount arguments, or destination accounts. Address-based policy rules also must
reject address lookup table ambiguity unless a future provider-backed proof says
otherwise. The fallback remains rider-session Balance execution or an explicit
wallet-boundary confirmation.

---

## 2. Execution Models

| Model | Meaning | Primary use |
|---|---|---|
| App-balance custody | Assets are already inside Boulder Roller Balance; this identifies custody, not consent | Source state only; cannot authorize rider-value movement |
| Rider session | Rider wallet configures one revocable signer; Anchor binds every exact operation to generation, nonce, and expiry | Default no-prompt Balance-funded Vault path after setup |
| Privy policy signer | Embedded wallet authorizes a server signer under provider policy | Embedded-wallet riders when the exact action is policy-scoped |
| SPL delegate | External wallet grants a limited token-account allowance | External-wallet riders who opt into no-prompt in-app movement |
| Permissionless-for-rider | Anyone can trigger because the program enforces the rider destination | `Collect DUNG` |
| Wallet-boundary | Value or authority crosses the Boulder Roller boundary | Add funds, withdraw to wallet, transfer out, export, authority change |

The backend fee payer is not an authority model. Paying SOL does not authorize
value movement.

---

## 3. Action Contract

| Rider action | Target authority | Normal wallet popup? | Required constraints |
|---|---|---|---|
| `Collect DUNG` | Permissionless-for-rider or Privy policy signer | No | DUNG mint, supply cap, VaultStake PDA, rider DUNG destination or RiderBalance DUNG PDA, treasury fee |
| `Deposit CAL` | Rider session, Privy policy signer, SPL delegate, or wallet fallback | No after setup | Exact rider/Vault/CAL amount/expiry/generation/nonce plus canonical escrow and position custody |
| `Withdraw CAL` | Rider session, Privy policy signer, SPL delegate, or wallet fallback | No after setup | Exact rider/Vault/LP amount/expiry/generation/nonce plus canonical position and Balance destination |
| `Create Vault` | Rider session, Privy policy signer, SPL delegate, or wallet fallback | No after setup | Exact new Vault and configured payment amounts, canonical PDAs, USDC treasury, `Vault.minter == rider` |
| `Pay with USDC` | Explicit rider session, Privy policy signer, SPL delegate, or wallet fallback | No only after explicit grant | ProgramConfig USDC mint, ProgramConfig USDC treasury, quote/config amount |
| `Add funds` | Wallet-boundary or onramp boundary | Yes / high assurance | Rider-confirmed asset, amount, and destination |
| `Withdraw to wallet` | Wallet-boundary | Yes / high assurance | Rider-confirmed destination token account and account-security state |
| `Transfer out` | Wallet-boundary | Yes / high assurance | Rider-confirmed recipient and amount |
| `Export wallet` | Provider account-security boundary | Yes / highest assurance | Provider step-up and recovery controls |
| `Change authority` | Provider/wallet account-security boundary | Yes / highest assurance | Old signer/delegate revoked before replacement is active |

The visible app should keep `Withdraw CAL` and `Withdraw to wallet` distinct.
The first is an in-app position movement. The second is a boundary event.

The executable backend contract for this table lives in
`backend/app/services/boulder_balance_authority.py`.

---

## 4. Privy Embedded-Wallet Path

Privy policy signing is allowed only after the rider has a Boulder Roller
account and embedded wallet setup. It is not a hidden login side effect.

Required provider-side constraints:

- chain type is Solana
- execution method is transaction signing/submission, not private-key export
- signer is attached only after account setup/login
- policy scope includes the Boulder Rollers program id when custom instructions
  are used
- token-program rules include instruction name, mint, amount, and destination
  account constraints where applicable
- policy includes time or expiry controls for prepared operations
- policy rejects wrong program, wrong asset, wrong recipient, wrong amount, and
  expired action attempts
- policy id and policy hash are recorded before coordinator execution

Required Boulder Roller constraints:

- Anchor validates ProgramConfig mints, treasuries, destinations, and amounts
- transaction coordinator validates action type against the authority catalog
- coordinator stores `policy_or_delegate_id`, policy hash, prepared message
  hash, idempotency key, confirmation state, and failure reason
- account recovery, security lock, unlink, or authority change prevents new
  policy-signed operations immediately

Privy policy is an execution mechanism. Anchor constraints are still the safety
mechanism.

---

## 5. External-Wallet SPL Delegate Path

SPL delegation is the external-wallet transition path for riders who want a
low-prompt app experience without moving every asset into a RiderBalance escrow.

Required delegate shape:

- use checked approval for the exact token account and mint
- use one delegate per token account
- allowance is expressed in base token units
- allowance is capped to the visible purpose and expected amount range
- Boulder Roller records an expiry even when SPL Token itself does not enforce
  time
- revoke uses the SPL Token revoke instruction
- account recovery, wallet unlink, or security lock blocks coordinator use of
  the old delegate immediately

Delegate execution is never a generic wallet grant. Every delegated operation
must still pass Anchor checks for mint, vault, source, destination, amount,
ProgramConfig treasury, and RiderBalance revocation state.

---

## 6. Revocation And Recovery

Revocation has to happen across layers because no single layer can prove the
whole world is clean.

| Layer | Required behavior |
|---|---|
| Portal/mobile | Shows account-security states inline and lets the rider revoke Balance authority from settings |
| Backend coordinator | Refuses stale `policy_or_delegate_id`, stopped accounts, locked accounts, recovered accounts, and revoked RiderBalance headers |
| Anchor | Rejects locked, recovering, revoked, stale or wrong rider sessions, wrong delegates, wrong mints, wrong destinations, wrong Vaults, and altered amounts |
| Privy | Removes or rotates the policy signer for the embedded wallet |
| SPL Token | Revokes the token-account delegate allowance |

When recovery starts, Boulder Roller should mark Balance execution locked before
showing any normal in-app economic action as available. The rider should see a
calm state such as `Needs review` or an account-security message, not a modal
stack of transaction language.

---

## 7. Coordinator Requirements

The transaction coordinator must import the authority catalog and refuse
operation construction when the catalog, rider state, ProgramConfig, provider
policy, or delegate state do not line up.

Minimum recorded fields:

| Field | Purpose |
|---|---|
| `operation_id` | idempotency and support handle |
| `action_type` | must match the authority catalog |
| `authority_model` | rider session, policy signer, delegate, permissionless, or boundary; app-balance is custody only |
| `asset`, `amount`, `source`, `destination` | rider-visible and protocol-visible scope |
| `policy_or_delegate_id` | rider-session, provider-policy, or delegate authority used, if any; field name is retained for storage compatibility |
| `policy_hash` | non-secret commitment to provider policy state |
| `prepared_message_hash` | malicious-client and retry protection |
| `fee_payer` | gas sponsor, not value authority |
| `confirmation_status` | chain submission/confirmation state |
| `projection_status` | app/indexer-visible state |
| `failure_reason` | support and retry detail |

The coordinator must not fall back to server-held rider key material.

---

## 8. Product Language Rules

Primary rider copy can say:

- `Boulder Roller Balance`
- `Collect DUNG`
- `Deposit CAL`
- `Withdraw CAL`
- `Create Vault`
- `Pay with USDC`
- `Add funds`
- `Withdraw to wallet`
- `Pending`
- `Delayed`
- `Needs review`

Primary rider copy should not say:

- gas
- fee payer
- sponsored transaction
- transaction signature
- explorer
- proof
- harvest
- unstake
- delegate
- policy signer

Those terms are valid in BoulderScan, admin, support, security, and developer
docs.

---

## 9. QA Gates

This bead is complete when the repository proves:

| Gate | Proof |
|---|---|
| Authority catalog | Every supported action has a single catalog entry and coherent authority models |
| Rider-session scope | Balance-funded Vault value actions require the configured signer and exact action, Vault, amount, generation, nonce, and expiry; lock, revoke, rotation, and replay fail closed |
| Privy separation | Embedded-wallet policy signing is not treated as external-wallet delegation |
| Delegate separation | External-wallet SPL delegate approval is limited and revocable |
| Boundary separation | Add funds, withdraw to wallet, transfer out, export, and authority change require step-up |
| USDC constraints | USDC payment paths bind mint, treasury, and amount to ProgramConfig or coordinator quote |
| Withdraw wording | `Withdraw CAL` is not conflated with `Withdraw to wallet` |
| Provider limitation | Custom Anchor policy enforcement is covered by the `boulderroller-v2-q7ze` executable fixture with concrete fallback behavior |

The executable provider-policy fixture is
`backend/app/services/balance_privy_policy_prototype.py`; its gate is
`backend/tests/services/test_balance_privy_policy_prototype.py`.

The unit gate is
`backend/tests/services/test_boulder_balance_authority.py`.

---

## 10. References

- Privy user and server signers:
  https://docs.privy.io/recipes/wallets/user-and-server-signers
- Privy server-side wallet access:
  https://docs.privy.io/recipes/wallets/session-signer-use-cases/server-side-access
- Privy Solana transactions:
  https://docs.privy.io/wallets/using-wallets/solana/send-a-transaction
- Privy Solana gas sponsorship:
  https://docs.privy.io/wallets/gas-and-asset-management/gas/solana
- Privy policies overview:
  https://docs.privy.io/controls/policies/overview
- Privy Solana policy examples:
  https://docs.privy.io/controls/policies/example-policies/solana
- Boulder Roller Privy policy prototype:
  `docs/rfcs/BOULDER_ROLLER_BALANCE_PRIVY_POLICY_PROTOTYPE.md`
- Privy authorization signatures:
  https://docs.privy.io/api-reference/authorization-signatures
- Solana SPL Token approve delegate:
  https://solana.com/docs/tokens/basics/approve-delegate
- Solana SPL Token revoke delegate:
  https://solana.com/docs/tokens/basics/revoke-delegate
- Solana SPL Token transfer authority:
  https://solana.com/docs/tokens/basics/transfer-tokens
