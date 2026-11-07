"""The rehearsal must not inherit production routing or dotenv files."""
from scripts import rehearse_canon_successors as rehearsal


def test_canon_rehearsal_removes_hostile_libpq_and_application_routing(monkeypatch):
    monkeypatch.setenv('PGHOSTADDR', '192.0.2.10')
    monkeypatch.setenv('PGSERVICE', 'production')
    monkeypatch.setenv('PGPASSWORD', 'do-not-use')
    monkeypatch.setenv('DATABASE_URL', 'postgresql://example.invalid/production')
    monkeypatch.setenv('SUPABASE_URL', 'https://example.invalid')
    env = rehearsal.rehearsal_environment()
    assert not any(k.startswith('PG') for k in env)
    assert 'DATABASE_URL' not in env
    assert 'SUPABASE_URL' not in env
    assert env['ENVIRONMENT'] == 'test'
    assert env['SOLANA_STUB'] == 'true'
