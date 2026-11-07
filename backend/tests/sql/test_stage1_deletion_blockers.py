"""Real 152 deletion lifecycle with the canonical Stage 1 Balance migration."""
import json
import uuid

import pytest

from tests.services.test_settlement_clock_postgres_runtime import _connection, postgres_dsn
from tests.sql.test_account_deletion_migration_runtime import (
    MIGRATION, ROOT, WALLET, _bootstrap_pre_152, _claim, _create_request,
    _insert_user, _storage_removed,
)

STAGE1 = MIGRATION.parent / "172_balance_operations.sql"


def baseline(cursor):
    _bootstrap_pre_152(cursor)
    cursor.execute("DROP TABLE public.balance_operations")
    cursor.execute(MIGRATION.read_text())
    # The real historical table shape allows a before/after comparison of 152.
    cursor.execute((ROOT / "backend/supabase/migrations/20260611_119_balance_operations.sql").read_text())


def insert(cursor, user, *, action="stage1_register", status="confirmed",
           projection="recorded", wallet=WALLET, personal=False):
    identifier = f"operation-{uuid.uuid4()}"
    cursor.execute("""INSERT INTO public.balance_operations
        (operation_id,rider_account_id,protocol_wallet,action_type,authority_model,
         confirmation_status,projection_status,idempotency_key,asset,amount,
         metadata,tx_signature,failure_reason,source,destination,fee_payer,
         prepared_message_hash,policy_or_delegate_id,reference_type,reference_id)
        VALUES (%s,%s,%s,%s,'wallet_boundary',%s,%s,%s,'USDC','123',%s::jsonb,
                %s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (identifier, user, wallet, action, status, projection,
         f"{wallet}:{identifier}" if personal else identifier,
         json.dumps({"wallet":wallet,"user":user}) if personal else "{}",
         *([wallet if personal else None] * 9)))
    return identifier


def blockers(cursor, user):
    cursor.execute("SELECT public.br_account_deletion_db_blockers(%s,%s)", (user, WALLET))
    return cursor.fetchone()[0]


@pytest.mark.parametrize("status", ["confirmed", "finalized", "failed", "expired"])
@pytest.mark.parametrize("owner", ["both", "user", "wallet"])
def test_terminal_stage1_operations_do_not_block(postgres_dsn, status, owner):
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        baseline(cursor)
        cursor.execute(STAGE1.read_text())
        user = _insert_user(cursor)
        insert(cursor, None if owner == "wallet" else user, status=status,
               wallet="unrelated-wallet" if owner == "user" else WALLET,
               projection="not_started" if status in ("failed", "expired") else "recorded")
        assert blockers(cursor, user) == []


@pytest.mark.parametrize("status", ["prepared", "submitted"])
def test_pending_stage1_request_is_retryable_until_durably_terminal(postgres_dsn, status):
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        baseline(cursor)
        cursor.execute(STAGE1.read_text())
        user = _insert_user(cursor)
        operation = insert(cursor, user, status=status, projection="not_started")
        # Age or a metadata timestamp is not finalized chain expiry authority.
        cursor.execute("""UPDATE balance_operations SET created_at='2000-01-01',
            metadata='{"expires_at":"2000-01-01"}' WHERE operation_id=%s""", (operation,))
        assert blockers(cursor, user) == [dict(code="claim_remains", category="processing",
            count=1, source="balance_operations", action="retry")]
        request, row = _create_request(cursor, user)
        assert row[1] == "blocked"
        cursor.execute("SELECT retryable FROM deletion_requests WHERE id=%s", (request,))
        assert cursor.fetchone() == (True,)
        cursor.execute("UPDATE balance_operations SET confirmation_status='expired' WHERE operation_id=%s", (operation,))
        assert blockers(cursor, user) == []
        cursor.execute("SELECT status FROM retry_account_deletion_request(%s,%s::jsonb)",
            (request, json.dumps(dict(allowed=True,available=True,destructive_boundary_available=True,blockers=[]))))
        assert cursor.fetchone() == ("queued",)


@pytest.mark.parametrize("status,projection", [
    ("prepared","not_started"), ("submitted","pending"), ("confirmed","recorded"),
    ("finalized","recorded"), ("confirmed","needs_review"), ("failed","not_started"),
    ("expired","not_started"),
])
def test_balance_rows_keep_exact_152_judgment_with_terminal_stage1_history(postgres_dsn, status, projection):
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        baseline(cursor)
        user = _insert_user(cursor)
        insert(cursor, user, action="deposit", status=status, projection=projection)
        # A SQL LIKE wildcard must not mistake this for the literal prefix.
        insert(cursor, user, action="stage1Xregister", status=status, projection=projection)
        expected = blockers(cursor, user)
        cursor.execute(STAGE1.read_text())
        for terminal in ("confirmed", "finalized", "failed", "expired"):
            insert(cursor, user, status=terminal)
        insert(cursor, str(uuid.uuid4()), status="submitted", wallet="unrelated-wallet")
        assert blockers(cursor, user) == expected
        cursor.execute(STAGE1.read_text())
        assert blockers(cursor, user) == expected


def test_mixed_balance_policy_blocker_survives_pending_stage1(postgres_dsn):
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        baseline(cursor)
        user = _insert_user(cursor)
        insert(cursor, user, action="deposit")
        expected = blockers(cursor, user)
        assert expected[0]["code"] == "policy_review_required"
        cursor.execute(STAGE1.read_text())
        insert(cursor, user, status="submitted", projection="not_started")
        assert blockers(cursor, user) == expected + [dict(code="claim_remains", category="processing",
            count=1, source="balance_operations", action="retry")]


def test_terminal_stage1_history_is_anonymized_at_real_finalization(postgres_dsn):
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        baseline(cursor)
        cursor.execute(STAGE1.read_text())
        user = _insert_user(cursor)
        insert(cursor, user, personal=True)
        other = insert(cursor, str(uuid.uuid4()), action="deposit", wallet="another-owner")
        cursor.execute("SELECT to_jsonb(o) FROM balance_operations o WHERE operation_id=%s", (other,))
        other_before = cursor.fetchone()[0]
        request, row = _create_request(cursor, user)
        assert row[1] == "queued"
        lease = _claim(cursor, request)
        _storage_removed(cursor, request, lease)
        cursor.execute("SELECT status,completion_verified_at FROM finalize_account_anonymization(%s,%s,%s)",
                       (request,user,lease))
        status, verified = cursor.fetchone()
        assert status == "completed" and verified is not None
        cursor.execute("SELECT id FROM users WHERE account_state='anonymized'")
        marker = cursor.fetchone()[0]
        cursor.execute("SELECT to_jsonb(o) FROM balance_operations o WHERE action_type='stage1_register'")
        retained = cursor.fetchone()[0]
        assert retained["rider_account_id"] == str(marker)
        assert retained["protocol_wallet"] == f"anonymous:{marker}"
        assert (retained["asset"],retained["amount"],retained["confirmation_status"]) == ("USDC","123","confirmed")
        assert WALLET not in json.dumps(retained) and user not in json.dumps(retained)
        assert retained["metadata"] == {} and retained["tx_signature"] is None
        cursor.execute("SELECT to_jsonb(o) FROM balance_operations o WHERE operation_id=%s", (other,))
        assert cursor.fetchone()[0] == other_before
