# Boulder Roller Balance Devnet E2E

> Retired. Program 0x4E removed `migrate_program_config`, `admin_create_vault`
> and `create_vault_from_balance_cal_usdc`, which this proof drove; the runner
> already refused the V4-B family before any RPC. The runner script was
> deleted, and the evidence below is a historical V4-A record.

This runbook proves the Boulder Roller Balance path on devnet with real
program instructions and rider-safe operation status projections.

## Command

```bash
PYTHONPATH=backend python3 backend/scripts/prove_balance_devnet_e2e.py
```

The runner uses:

- a fresh rider keypair by default
- fee-payer keypair: `~/.config/solana/boulderroller-fee-payer.json`
- backend authority keypair: `~/.config/solana/boulderroller-backend-authority.json`
- admin + upgrade authority keypair: `~/.config/solana/boulderroller-admin-upgrade-authority.json`
- devnet program: `EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH`

## Devnet Configuration Evidence

Latest successful run: `balance-devnet-e2e-1781263674`

ProgramConfig:

- PDA: `DtDkrJBoEbK9PEUzG731M2MFX1tGBhL3dX2SQ9FckPD8`
- admin authority: `G8DM5Dn12fsgkKxbdUUtFVJsqMXTcJqPU9no7koqwcKH`
- backend authority: `CJz8PUyNVvLuXJvjsYXgSKD9utZVP2XoTEZq6M973Gha`
- CAL mint: `4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh`
- DUNG mint: `CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk`
- devnet test USDC mint: `DpLPBaRuLnBsR3P3meU1tmiNUxreXwskXBebTYKvNGne`
- devnet USDC treasury token account: `GEL1JhavEKPuqVBvUiezUgNG2VYK1jtzsUazo2Scm1jA`
- vault USDC amount: `2000000`

Setup transactions:

- ProgramConfig migration: `32HSMYVhanRC3e2NZoRb9tyWaY1pKVvZaQP8n7PhbPtet3cCHmaFpU4HkJ7v8oadZPv8PJ48sNnHk5MS8DGafMFk`
- test USDC mint creation: `2Szh7KQG6UgSevNgWsxv4MtCGcEv9VsiZjQm3oATMBmCtFkJR4Gd4M2rNpi15DHKUkvFnGE57CPFFtBz2wcsBt2Q`
- test USDC treasury account creation: `4nDQ71mhdKmVn1rav9MJgUB3NAstGU2u8SAis7iE8RwAUS7nbPBp5sMDS6DehibsL789JTxHzBBhFHhE6WB7tctz`
- ProgramConfig USDC configuration: `54FnpqH8JvaP4kN8WAXDfQtdo3gMFpwchkECaGmYc3cakqnmZLak8RfjcwgJwGXEXMBTXrc1u6zWrNcCaG4oCwSG`
- backend authority devnet SOL refill: `2UACjNcU9XGA1wE2Kdfhr3fkT3gGH2epMqw2HRnCiMemap6dGifw4yEkDCnyDZSktJJo9f8XRxz2FQvVxgH9WQC5`

## Coverage From Latest Run

Latest rider: `6v4ZJja4Ur3z2MTfsSWKhY88nNaJZPoqFSyoP52zjS4r`

Primary vault for CAL/DUNG proof: `12`

Balance-funded CAL+USDC vault: `13`

| Gate | Evidence |
| --- | --- |
| RiderBalance initialized | `3xdXrK78hoHnQEy6GuZahwXNqAPqCohP9QWpcH7AXibRa2woqDDmWfHVpC5yEHLjctgBFXn1A9sve7WDUTp7R45q` |
| CAL Balance token PDA initialized | `2j4TycRGLzJpbvmasy8Jok672vPqL5bGsBGRUYCvuohaypHmp8ThjDWJDvr4L9V7pSj2Bf4LadEP2skyrDM3B4T9` |
| USDC Balance token PDA initialized | `5Wx9K5pG7eQABoyG8UeyvoAF47ynVaK92XKqzSkWZmCk6kvwxxcSa5DYN1tC24AC1N9ktLSB559djWojbLQNpuJL` |
| Add CAL to Balance | `4pz6hKUBjocyWPXGPsFDWdqGbJS9G3gvPei6rQdQeKbK5yC5kji8Ed8mEXtqv3sGesXcjthrXHgMDhjWH8dmBQ23` |
| Deposit CAL from Balance | `2RVzAvAz7kYX2mjJHWNFBqukaCi5fpu7vzm49p8p9nCkJz38JKdSToGS31p74kkTy3BGjic2MeD4M7huBM9Y6qVu` |
| Collect DUNG for rider | `665AetjQonzpmY59vS7HHzD76inQa8WWw1TdSjk5VMpQNpXuCeKBCivoe5464RLetz3LH4yjtPob7WDPpf4xEe7T` |
| Withdraw CAL to Balance | `5XfdLsSf8tAgU2Tx4ZA4hgxt3KtCPRtSxoz1Ds1YymbeGfRhb5Cq4PuGnW8haF6koMBNthwzDCjFTqFoBfeFX4Qv` |
| Withdraw CAL to wallet boundary | `2Y21V4Fok6kyKU6JsbXbZU4e7xQidWyaJVLhbKuzrt7BUiojkp3SjT1MdjAFGKVz5J8BffWd8Mt7f1cfuZ34Zr43` |
| Add USDC to Balance | `oV72YqDKtxvw9AbNyUFoHCCziTzvsZk9tpsfvYYHDd8rwiMqU8UHjQyiw4fzy7H3HW2bHLq5iizpHYqSTdKkvKg` |
| Create vault from Balance CAL+USDC | `2rWb9wugDSjAhTShdM5MJArxNUwCDSrMnMzxxqr9Wngra61cVtWiTf7S27qRZDDJomzUZ6uGHKmGF97MRMM7Zszz` |
| Revoke RiderBalance | `3PbRG9H3QuLAA64n4xDBUkoXctxRVgthaJuks1FWAaDRmXNP1ZfqZ6eBSZDDW22Bx6KfeAgvdLN5AkYYW1FpProU` |
| Stale no-prompt deposit rejected | expected failure with `InvalidBalanceStatus` / error `6067` |

The proof output also records operation read states for:

- recorded Add funds, Deposit CAL, Collect DUNG, Withdraw CAL, Withdraw to wallet, Add USDC, and Create Vault
- delayed projection state (`Delayed`)
- revoked coordinator rejection (`account_revoked`)
- failed operation state (`Needs review`)

## Closeout Verification

The app transaction builders also resolve USDC configuration from on-chain
ProgramConfig by default. This keeps Add funds, Withdraw to wallet, and
CAL+USDC vault creation aligned with the devnet proof instead of falling back
to stale environment defaults.

Passing gates from this closeout:

```bash
python3 -m pytest backend/tests/services/test_tx_builder_program_config.py \
  backend/tests/services/test_balance_operation_status.py \
  backend/tests/services/test_balance_transaction_coordinator.py \
  backend/tests/services/test_balance_route_adapters.py \
  backend/tests/services/test_balance_authority_execution.py \
  backend/tests/services/test_balance_lifecycle.py \
  backend/tests/services/test_balance_privy_policy_prototype.py \
  backend/tests/services/test_balance_rollout_readiness.py \
  backend/tests/test_solana_direct_completion.py \
  backend/tests/truths/alignment/test_program_config_compact_gate.py \
  backend/tests/truths/test_backend_truths_gate1.py -q
# 193 passed, 1 skipped, 1 warning

NODE_OPTIONS='--loader ts-node/esm --no-warnings' node scripts/validate_deployment.ts
# All 14/14 checks passed.

git diff --check
```

## Notes

The configured USDC mint is a devnet test mint whose authority is the local
admin keypair. Do not treat it as production USDC. Production rollout must
configure the real production USDC mint and treasury token account before
enabling mainnet `Pay with USDC` or CAL+USDC vault creation.
