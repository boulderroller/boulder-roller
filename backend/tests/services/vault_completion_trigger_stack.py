"""The production trigger stack on public.vault_completions, for runtime tests.

Migration 176 adds the "New best" triggers to a table that already carries
the 152 deletion fence and four other production triggers. Runtime tests of
176 run on that stack: every trigger function and writer installed here is
read verbatim from the latest migration that defines it, in the migration
runner's order. Only these are stand-ins:

* table shells: the production column shapes, constraints and indexes of
  vault_completions, and the columns the stack reads everywhere else;
* the Threshold release authority validator, whose indexed inputs are out of
  scope;
* the account-deletion wallet fingerprint, whose keyring HMAC becomes a plain
  SHA-256 digest.

The stack (each timing fires in trigger-name order):

    BEFORE account_deletion_write_fence                      152
    BEFORE br_bind_vault_completion_evidence_version         125, function 155
    BEFORE br_vault_completion_settlement_clock              119
    BEFORE enforce_vault_completion_chain_authority_trigger  114
    AFTER  br_vault_completion_finalized_at_trigger          120, refresh 155

The writers are 128's record_vault_completion_projection and
reconcile_confirmed_vault_completion (the whole migration), 155's
reconcile_confirmed_reward_threshold_release_completion, and 152's account
anonymization statement (anonymize_vault_completions below).
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from backend.scripts.apply_sql_migrations import discover_migrations


BACKEND_ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = BACKEND_ROOT / "sql"
NEW_BEST_MIGRATION = "176_vault_completion_new_best.sql"

STACK_FUNCTIONS = (
    "account_deletion_write_fence",
    "br_account_deletion_write_fence_active",
    "br_bind_vault_completion_evidence_version",
    "br_settlement_week",
    "br_settlement_clock_version_at",
    "br_assign_vault_completion_settlement_clock",
    "enforce_vault_completion_chain_authority",
    "br_sync_vault_completion_finalized_at",
    "br_refresh_ride_finalized_at",
    "reconcile_confirmed_reward_threshold_release_completion",
)

STACK_TRIGGERS = (
    "br_bind_vault_completion_evidence_version",
    "br_vault_completion_settlement_clock",
    "enforce_vault_completion_chain_authority_trigger",
    "br_vault_completion_finalized_at_trigger",
)

# 152 installs its row fence from a loop over every wallet-bearing table, as
# account_deletion_write_fence(<has wallet fields>). For vault_completions the
# loop executes exactly this statement.
FENCE_TRIGGER = """
CREATE TRIGGER account_deletion_write_fence
BEFORE INSERT OR UPDATE OR DELETE ON public.vault_completions
FOR EACH ROW EXECUTE FUNCTION public.account_deletion_write_fence('true');
"""

ROLES = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role NOLOGIN BYPASSRLS;
    END IF;
END;
$$;
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;

-- Supabase's provisioning defaults: service_role gets every new table, and
-- the API roles may execute every new function unless a migration revokes it.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT EXECUTE ON FUNCTIONS TO anon, authenticated, service_role;
"""

SHELLS = """
-- 035, 047, 048, 053, 089, 093, 114, 119, 125 and 155.
CREATE TABLE public.vault_completions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vault_signature TEXT NOT NULL,
    wallet TEXT NOT NULL,
    activity_id TEXT NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    time_seconds INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    best_time_seconds INTEGER,
    best_time_achieved_at TIMESTAMPTZ,
    total_completions INTEGER DEFAULT 1,
    avg_power_w INTEGER,
    validated BOOLEAN DEFAULT true,
    validation_override BOOLEAN DEFAULT false,
    validation_notes TEXT,
    device_name TEXT,
    is_pr BOOLEAN DEFAULT false,
    on_chain_tx TEXT,
    on_chain_tx_error TEXT,
    cal_tribute NUMERIC NOT NULL DEFAULT 0,
    chain_confirmation_status TEXT NOT NULL DEFAULT 'legacy_unverified',
    completion_receipt_pda TEXT,
    completion_evidence_hash BYTEA,
    chain_confirmed_at TIMESTAMPTZ,
    completion_evidence_version SMALLINT,
    settlement_week BIGINT NOT NULL,
    settlement_clock_version SMALLINT NOT NULL,
    UNIQUE (vault_signature, activity_id),
    CONSTRAINT vault_completions_chain_confirmation_status_check
        CHECK (chain_confirmation_status IN ('legacy_unverified', 'confirmed')),
    CONSTRAINT vault_completions_no_placeholder_tx_check
        CHECK (on_chain_tx IS NULL OR on_chain_tx NOT LIKE 'exists:%'),
    CONSTRAINT vault_completions_confirmed_receipt_check CHECK (
        chain_confirmation_status <> 'confirmed'
        OR (
            completion_receipt_pda IS NOT NULL
            AND completion_evidence_hash IS NOT NULL
            AND octet_length(completion_evidence_hash) = 32
            AND chain_confirmed_at IS NOT NULL
            AND (on_chain_tx IS NULL OR on_chain_tx NOT LIKE 'exists:%')
        )
    ),
    CONSTRAINT vault_completions_evidence_version_check
        CHECK (completion_evidence_version IN (1, 2, 3))
);
CREATE INDEX idx_vault_completions_vault
    ON public.vault_completions (vault_signature);
CREATE INDEX idx_vault_completions_wallet
    ON public.vault_completions (wallet);
CREATE INDEX idx_vault_completions_time
    ON public.vault_completions (completed_at);
CREATE INDEX idx_vault_completions_ranking
    ON public.vault_completions (vault_signature, best_time_seconds)
    WHERE best_time_seconds IS NOT NULL;
CREATE INDEX idx_vault_completions_wallet_vault
    ON public.vault_completions (wallet, vault_signature);
CREATE INDEX idx_vault_completions_validated
    ON public.vault_completions (vault_signature, validated)
    WHERE validated = false;
CREATE INDEX idx_vault_completions_activity_onchain
    ON public.vault_completions (activity_id, vault_signature, completed_at)
    WHERE on_chain_tx IS NOT NULL;
CREATE UNIQUE INDEX idx_vault_completions_receipt_pda
    ON public.vault_completions (completion_receipt_pda)
    WHERE completion_receipt_pda IS NOT NULL;
CREATE UNIQUE INDEX idx_vault_completions_evidence_hash
    ON public.vault_completions (completion_evidence_hash)
    WHERE completion_evidence_hash IS NOT NULL;
CREATE INDEX idx_vault_completions_confirmed_candidates
    ON public.vault_completions (vault_signature, completed_at, wallet)
    WHERE chain_confirmation_status = 'confirmed';

CREATE TABLE public.rides (
    id UUID PRIMARY KEY,
    finalized_at TIMESTAMPTZ
);

-- 152's deletion authority, as its fence reads it.
CREATE TABLE public.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet TEXT NOT NULL UNIQUE,
    account_state TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE public.deletion_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID,
    wallet TEXT,
    status TEXT NOT NULL,
    storage_authorized_at TIMESTAMPTZ
);
CREATE TABLE public.deleted_account_tombstones (
    wallet_fingerprint TEXT PRIMARY KEY
);
CREATE TABLE public.deleted_wallets (
    wallet TEXT PRIMARY KEY
);

-- 120 and 155: the indexed chain evidence behind rides.finalized_at.
CREATE TABLE public.indexed_vaults (
    id NUMERIC(20, 0) PRIMARY KEY,
    signature_hex TEXT NOT NULL UNIQUE
);
CREATE TABLE public.indexed_epoch_distributions (
    vault_id NUMERIC(20, 0) NOT NULL,
    epoch NUMERIC(20, 0) NOT NULL,
    finalized_at TIMESTAMPTZ
);
CREATE TABLE public.indexed_climb_completion_flows (
    tx_signature TEXT NOT NULL DEFAULT gen_random_uuid()::TEXT,
    event_index INTEGER NOT NULL DEFAULT 0,
    vault_id NUMERIC(20, 0) NOT NULL,
    ride_attestation TEXT NOT NULL,
    completion_evidence_hash BYTEA NOT NULL UNIQUE,
    credited_settlement_week NUMERIC(20, 0) NOT NULL,
    cal_tributed NUMERIC(39, 0) NOT NULL,
    completion_evidence_version SMALLINT NOT NULL DEFAULT 1,
    release_authority_pda TEXT,
    PRIMARY KEY (tx_signature, event_index)
);
CREATE TABLE public.indexed_climb_completion_receipts (
    pda TEXT PRIMARY KEY,
    ride_attestation_pda TEXT NOT NULL,
    release_authority_pda TEXT,
    completion_evidence_version SMALLINT NOT NULL DEFAULT 1,
    completion_evidence_hash BYTEA,
    cal_tributed NUMERIC(20, 0),
    credited_settlement_week NUMERIC(20, 0)
);
CREATE TABLE public.indexed_held_ride_release_authorities (
    pda TEXT PRIMARY KEY,
    release_settlement_week NUMERIC(20, 0)
);

-- 114 and 125: the frozen evidence authority of an ordinary ride.
CREATE TABLE public.ride_economic_plans (
    ride_id UUID PRIMARY KEY,
    wallet TEXT NOT NULL,
    state TEXT NOT NULL,
    lease_owner UUID,
    lease_expires_at TIMESTAMPTZ,
    expected_attestation_pda TEXT
);
CREATE TABLE public.ride_economic_completion_steps (
    ride_id UUID NOT NULL,
    step_index INTEGER NOT NULL,
    state TEXT NOT NULL,
    chain_confirmed_at TIMESTAMPTZ,
    vault_id NUMERIC(20, 0),
    vault_signature TEXT NOT NULL,
    completion_time_s BIGINT,
    completed_at TIMESTAMPTZ NOT NULL,
    exact_tribute_base_units NUMERIC NOT NULL,
    actual_tx_signature TEXT,
    expected_receipt_pda TEXT UNIQUE,
    completion_evidence_hash BYTEA UNIQUE,
    completion_evidence_version SMALLINT NOT NULL DEFAULT 1,
    PRIMARY KEY (ride_id, step_index)
);

-- 155: the frozen evidence authority of a held ride's release.
CREATE TABLE public.reward_threshold_release_snapshots (
    id UUID PRIMARY KEY,
    ride_id UUID NOT NULL
);
CREATE TABLE public.reward_threshold_release_executions (
    snapshot_id UUID PRIMARY KEY,
    state TEXT NOT NULL,
    lease_owner UUID,
    lease_expires_at TIMESTAMPTZ,
    expected_release_authority_pda TEXT,
    wallet TEXT NOT NULL
);
CREATE TABLE public.reward_threshold_release_steps (
    snapshot_id UUID NOT NULL,
    step_index INTEGER NOT NULL,
    state TEXT NOT NULL,
    chain_confirmed_at TIMESTAMPTZ,
    vault_id NUMERIC(20, 0),
    vault_signature TEXT NOT NULL,
    completion_time_s BIGINT,
    completed_at TIMESTAMPTZ NOT NULL,
    exact_tribute_base_units NUMERIC NOT NULL,
    actual_tx_signature TEXT,
    expected_receipt_pda TEXT UNIQUE,
    completion_evidence_hash BYTEA UNIQUE,
    completion_evidence_version SMALLINT NOT NULL DEFAULT 3,
    PRIMARY KEY (snapshot_id, step_index)
);
"""

STAND_INS = """
-- Stand-in: 155's exact indexed release authority check. Its inputs are the
-- indexer's held-ride state, which these tests do not model.
CREATE FUNCTION public.validate_exact_indexed_reward_threshold_release_authority(
    p_snapshot_id UUID
) RETURNS BOOLEAN
LANGUAGE sql
AS $$ SELECT true $$;

-- Stand-in: 152's fingerprint is an HMAC under the deletion keyring.
CREATE FUNCTION public.br_account_deletion_wallet_fingerprint(p_wallet TEXT)
RETURNS TEXT
LANGUAGE sql
STABLE
SET search_path = ''
AS $$
    SELECT pg_catalog.encode(
        pg_catalog.sha256(pg_catalog.convert_to(p_wallet, 'UTF8')), 'hex'
    )
$$;
"""

_DOLLAR_QUOTE = re.compile(r"\$[A-Za-z_]*\$")


@functools.lru_cache(maxsize=None)
def _migrations() -> tuple[Path, ...]:
    """Every numbered migration except 176, in the runner's order."""
    return tuple(
        migration.path
        for migration in discover_migrations(SQL_DIR)
        if migration.filename != NEW_BEST_MIGRATION
    )


def _statement_with_body(text: str, start: int) -> str:
    """The statement at start, through its dollar-quoted body and final ';'."""
    opener = _DOLLAR_QUOTE.search(text, start)
    assert opener is not None, text[start : start + 80]
    close = text.index(opener.group(0), opener.end())
    return text[start : text.index(";", close + len(opener.group(0))) + 1]


@functools.lru_cache(maxsize=None)
def latest_function(name: str) -> tuple[str, str]:
    """(migration, statement) of the last CREATE FUNCTION public.<name>."""
    pattern = re.compile(
        rf"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+public\.{re.escape(name)}\s*\("
    )
    found = None
    for path in _migrations():
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            found = (path.name, _statement_with_body(text, match.start()))
    if found is None:
        raise LookupError(f"no migration defines public.{name}")
    return found


@functools.lru_cache(maxsize=None)
def latest_trigger(name: str) -> tuple[str, str]:
    """(migration, statement) of the last CREATE TRIGGER <name> on vault_completions."""
    pattern = re.compile(
        rf"CREATE\s+(?:OR\s+REPLACE\s+)?TRIGGER\s+{re.escape(name)}\s[^;]*?"
        r"\bON\s+(?:public\.)?vault_completions\b[^;]*;"
    )
    found = None
    for path in _migrations():
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            found = (path.name, match.group(0))
    if found is None:
        raise LookupError(f"no migration creates trigger {name}")
    return found


def _settlement_clock_contract_table() -> str:
    text = (SQL_DIR / "119_settlement_clock_v2.sql").read_text(encoding="utf-8")
    start = text.index("CREATE TABLE IF NOT EXISTS public.settlement_clock_contract (")
    return text[start : text.index("\n);", start) + 3]


SETTLEMENT_CLOCK_CONTRACT = """
-- A v2 clock with legacy history before its cutover (week 100), as indexed.
INSERT INTO public.settlement_clock_contract (
    id, contract_version, legacy_anchor_unix, v2_anchor_unix, cutover_unix,
    cutover_week, duration_seconds, grace_seconds, has_legacy_history,
    program_config_pda, program_config_slot, program_config_commitment,
    contract_hash, indexed_at
) VALUES (
    1, 2, 1704020400, 1704110400, 1704110400 + 100 * 604800,
    100, 604800, 86400, true,
    'program-config', 1, 'finalized', pg_catalog.repeat('a', 64), now()
);
"""


def _anonymization_statement() -> str:
    """152's statement that moves a deleted rider's completions off their wallet.

    It lives in finalize_account_anonymization, which 170 keeps and wraps.
    """
    text = (SQL_DIR / "152_account_deletion_lifecycle.sql").read_text(encoding="utf-8")
    marker = "UPDATE public.vault_completions\n    SET wallet = v_anonymous_wallet,"
    assert text.count(marker) == 1
    start = text.index(marker)
    return text[start : text.index(";", start) + 1]


def _anonymizer() -> str:
    return (
        "CREATE FUNCTION public.br_test_anonymize_vault_completions(\n"
        "    v_wallet TEXT,\n"
        "    v_anonymous_wallet TEXT\n"
        ") RETURNS VOID\n"
        "LANGUAGE plpgsql\n"
        "AS $test$\n"
        "BEGIN\n"
        "    -- finalize_account_anonymization writes under its request id,\n"
        "    -- which the 152 fence admits.\n"
        "    PERFORM pg_catalog.set_config(\n"
        "        'app.account_deletion_request_id',\n"
        "        pg_catalog.gen_random_uuid()::TEXT,\n"
        "        TRUE\n"
        "    );\n"
        f"    {_anonymization_statement()}\n"
        "    PERFORM pg_catalog.set_config('app.account_deletion_request_id', '', TRUE);\n"
        "END;\n"
        "$test$;\n"
    )


def install_stack(
    cursor: Any,
    *,
    riders: Iterable[str],
    climbs: Mapping[str, int],
) -> None:
    """Build vault_completions as production has it before migration 176.

    riders become active accounts and climbs indexed Vaults. One unrelated
    account has completed deletion, so the 152 fence runs its full per-row
    checks; it skips them only while no account has ever been deleted.
    """
    cursor.execute(ROLES)
    cursor.execute(SHELLS)
    cursor.execute(_settlement_clock_contract_table())
    cursor.execute(SETTLEMENT_CLOCK_CONTRACT)
    cursor.execute(STAND_INS)
    for name in STACK_FUNCTIONS:
        cursor.execute(latest_function(name)[1])
    cursor.execute(
        (SQL_DIR / "128_completion_projection_ownership.sql").read_text(encoding="utf-8")
    )
    cursor.execute(_anonymizer())
    cursor.execute(FENCE_TRIGGER)
    for name in STACK_TRIGGERS:
        cursor.execute(latest_trigger(name)[1])
    for wallet in riders:
        cursor.execute("INSERT INTO public.users (wallet) VALUES (%s)", (wallet,))
    for signature, vault_id in climbs.items():
        cursor.execute(
            "INSERT INTO public.indexed_vaults (id, signature_hex) VALUES (%s, %s)",
            (vault_id, signature),
        )
    cursor.execute(
        """
        INSERT INTO public.deleted_account_tombstones (wallet_fingerprint)
        VALUES (public.br_account_deletion_wallet_fingerprint('a-deleted-rider'))
        """
    )


def anonymize_vault_completions(cursor: Any, wallet: str, anonymous_wallet: str) -> None:
    """Run 152's anonymization statement for wallet, as account deletion does."""
    cursor.execute(
        "SELECT public.br_test_anonymize_vault_completions(%s, %s)",
        (wallet, anonymous_wallet),
    )
