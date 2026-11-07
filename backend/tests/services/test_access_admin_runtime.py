from pathlib import Path
import json
import pytest
import psycopg2
from uuid import uuid4
from backend.tests.services.test_settlement_clock_postgres_runtime import _connection, postgres_dsn
from backend.tests.services.test_invite_security_postgres_runtime import _bootstrap

ROOT=Path(__file__).resolve().parents[2]

def test_admin_actions_are_atomic_audited_and_identity_wide(postgres_dsn):
    actor,user=str(uuid4()),str(uuid4())
    with _connection(postgres_dsn) as conn:
        with conn.cursor() as c:
            _bootstrap(c)
            c.execute('CREATE TABLE users(id uuid primary key, wallet text); CREATE TABLE admin_users(user_id uuid,role text); CREATE TABLE auth_identities(user_id uuid,provider text,provider_subject text,wallet text); CREATE TABLE auth_refresh_tokens(wallet text,revoked_at timestamptz,revocation_reason text);')
            c.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON users,admin_users,auth_identities,auth_refresh_tokens TO service_role')
            c.execute("INSERT INTO users VALUES (%s,'founder'),(%s,'canonical'); INSERT INTO admin_users VALUES (%s,'admin')",(actor,user,actor))
            c.execute("INSERT INTO auth_identities VALUES (%s,'privy','did:privy:rider','linked'),(%s,'wallet','old-wallet',NULL); INSERT INTO auth_refresh_tokens(wallet) VALUES ('canonical'),('linked'),('old-wallet'),('unrelated')",(user,user))
            for name in ['159_access_door_hashed_invites.sql','160_cohort_admission.sql','161_access_admin_audit.sql']:
                c.execute((ROOT/'sql'/name).read_text())
            def call(action,target=None,details=None,code_hash=None):
                c.execute('SET ROLE service_role')
                try:
                    c.execute('SELECT access_admin_action(%s,%s,%s,%s::jsonb,%s)',(actor,action,target,json.dumps(details or {}),code_hash))
                    return c.fetchone()[0]
                finally:
                    c.execute('RESET ROLE')
            minted=call('mint_invite',details={'max_uses':1,'expires_in_days':7,'intended_for':'rider@example.com','label':'rider'},code_hash='a'*64)
            assert minted['ok'] and minted['invite']['remaining']==1
            invite_id=minted['invite']['id']
            c.execute('SELECT * FROM consume_invite_code(%s,%s,NULL,NULL,%s)',('a'*64,'linked','rider@example.com'))
            assert c.fetchone()[0]
            listed=call('list_invites')
            assert listed['invites'][0]['id']==invite_id
            assert listed['invites'][0]['remaining']==0
            assert listed['invites'][0]['uses'][0]['wallet']=='linked'
            assert listed['invites'][0]['uses'][0]['when']
            assert 'code_hash' not in json.dumps(listed) and '"code"' not in json.dumps(listed)
            assert call('deactivate_invite',invite_id)['ok']
            assert call('admit_cohort','linked')['cohort_admitted']
            c.execute('SELECT cohort_admitted_by FROM users WHERE id=%s',(user,)); assert c.fetchone()[0]==actor
            assert not call('revoke_cohort','canonical')['cohort_admitted']
            assert call('revoke_sessions','linked')['revoked']==3
            c.execute("SELECT revoked_at IS NULL FROM auth_refresh_tokens WHERE wallet='unrelated'"); assert c.fetchone()[0]
            assert call('admit_cohort','missing')['error']=='wallet_not_found'
            c.execute('SELECT action, details FROM access_audit ORDER BY at,id'); rows=c.fetchall()
            assert len(rows)==7
            assert 'a'*64 not in json.dumps(rows)
            c.execute("SELECT has_table_privilege('anon','access_audit','select'),has_table_privilege('service_role','access_audit','update'),has_function_privilege('authenticated','access_admin_action(uuid,text,text,jsonb,text)','execute')")
            assert c.fetchone()==(False,False,False)

            c.execute("CREATE FUNCTION reject_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'audit unavailable'; END $$; CREATE TRIGGER reject_audit BEFORE INSERT ON access_audit FOR EACH ROW EXECUTE FUNCTION reject_audit();")
            with pytest.raises(psycopg2.errors.RaiseException, match='audit unavailable'):
                call('admit_cohort','canonical')
            c.execute('SELECT cohort_admitted_at FROM users WHERE id=%s',(user,))
            assert c.fetchone()[0] is None
            c.execute('SELECT count(*) FROM access_audit')
            assert c.fetchone()[0] == 7
