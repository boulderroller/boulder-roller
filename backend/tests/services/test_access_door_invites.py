from pathlib import Path
import hashlib
import hmac
import pytest
from backend.tests.services.test_invite_security_postgres_runtime import _bootstrap, _call_invite_rpc
from backend.tests.services.test_settlement_clock_postgres_runtime import _connection, postgres_dsn

SQL = Path(__file__).resolve().parents[2] / 'sql/159_access_door_hashed_invites.sql'

def digest(code):
    return hmac.new(b'test-invite-secret', code.strip().lower().encode(), hashlib.sha256).hexdigest()

def test_hashed_invites_preserve_shared_and_bind_single_use(postgres_dsn):
    with _connection(postgres_dsn) as conn:
        with conn.cursor() as cur:
            _bootstrap(cur)
            cur.execute("INSERT INTO invite_codes(code) VALUES ('legacy-shared')")
            cur.execute("SELECT set_config('app.invite_code_secret', 'test-invite-secret', false)")
            cur.execute(SQL.read_text())
            cur.execute(SQL.read_text())
            cur.execute('SELECT code, code_hash, max_uses, expires_at, is_active FROM invite_codes')
            assert cur.fetchone() == (None, digest('legacy-shared'), None, None, True)
            for wallet in ['wallet-a', 'wallet-b']:
                assert _call_invite_rpc(cur, 'SELECT * FROM consume_invite_code(%s,%s)', (digest('legacy-shared'), wallet))[0]
            cur.execute("INSERT INTO invite_codes(code_hash,intended_for) VALUES (%s,'person@example.com') RETURNING max_uses, expires_at > now()", (digest('single-use'),))
            assert cur.fetchone() == (1, True)
            for email, valid in [('wrong@example.com',False), ('PERSON@example.com',True), ('person@example.com',False)]:
                assert _call_invite_rpc(cur, 'SELECT * FROM consume_invite_code(%s,%s,NULL,NULL,%s)', (digest('single-use'), 'wallet-c', email))[0] is valid
            cur.execute("INSERT INTO invite_codes(code_hash,expires_at) VALUES (%s,now()-interval '1 second')", (digest('expired-code'),))
            assert not _call_invite_rpc(cur,'SELECT * FROM consume_invite_code(%s,%s)',(digest('expired-code'),'wallet-d'))[0]
            cur.execute("INSERT INTO invite_codes(code_hash,intended_for) VALUES (%s,'WalletCase')", (digest('wallet-code'),))
            assert not _call_invite_rpc(cur,'SELECT * FROM consume_invite_code(%s,%s)',(digest('wallet-code'),'walletcase'))[0]
            assert _call_invite_rpc(cur,'SELECT * FROM consume_invite_code(%s,%s)',(digest('wallet-code'),'WalletCase'))[0]
            cur.execute("SELECT has_function_privilege('anon','check_invite_code(text,text,text)','execute'), has_table_privilege('authenticated','invite_codes','select')")
            assert cur.fetchone() == (False,False)


def test_missing_backfill_key_rolls_back_plaintext_change(postgres_dsn):
    import psycopg2
    with _connection(postgres_dsn) as conn:
        with conn.cursor() as cur:
            _bootstrap(cur)
            cur.execute("INSERT INTO invite_codes(code) VALUES ('legacy-shared')")
            with pytest.raises(psycopg2.errors.RaiseException,match='backfill requires'):
                cur.execute(SQL.read_text())
            cur.execute('ROLLBACK')
            cur.execute('SELECT code,max_uses,expires_at,is_active FROM invite_codes')
            assert cur.fetchone()==('legacy-shared',None,None,True)


def test_row_lock_prevents_concurrent_single_use(postgres_dsn):
    from concurrent.futures import ThreadPoolExecutor
    with _connection(postgres_dsn) as conn:
        with conn.cursor() as cur:
            _bootstrap(cur)
            cur.execute(SQL.read_text())
            cur.execute('INSERT INTO invite_codes(code_hash) VALUES (%s)',(digest('concurrent-code'),))
    def consume(wallet):
        with _connection(postgres_dsn) as conn:
            with conn.cursor() as cur:
                return _call_invite_rpc(cur,'SELECT * FROM consume_invite_code(%s,%s)',(digest('concurrent-code'),wallet))[0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(consume,['rider-one','rider-two']))==[False,True]
