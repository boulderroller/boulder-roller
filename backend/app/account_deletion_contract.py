"""Small shared contracts used by deletion authority readers.

Keep this module dependency-free so both chain decoding and lifecycle services
can consume the same field inventory without creating an import cycle.
"""

VAULT_STAKE_ACTIVE_FIELDS = (
    "lp_tokens",
    "cal_staked",
    "effective_lp_tokens",
    "pending_lp_tokens",
    "pending_effective_week_plus_one",
)

VAULT_STAKE_CLAIM_FIELDS = ("rewards_earned",)

VAULT_STAKE_DELETION_U64_FIELDS = (
    *VAULT_STAKE_ACTIVE_FIELDS,
    *VAULT_STAKE_CLAIM_FIELDS,
)
