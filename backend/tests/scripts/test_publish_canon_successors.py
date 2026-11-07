"""Bounded publication approval and payload checks; no remote services."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest

from scripts import publish_canon_successors as successor


def test_canon_check_output_serializes_database_timestamps():
    encoded = successor.json_text({'updated_at': datetime(2026, 10, 21, tzinfo=timezone.utc)})
    assert json.loads(encoded)['updated_at'] == '2026-10-21T00:00:00+00:00'


@pytest.mark.parametrize('table,column', [('users','email'), ('canon_climbs','ratified_by'),
                                         ('canon_climbs','provenance'), ('canon_corridor_cells','wallet')])
def test_canon_archive_column_allowlist_refuses_private_tables_and_columns(table, column):
    tables = {name: [] for name in successor.ARCHIVE_COLUMNS}
    row = {name: None for name in successor.ARCHIVE_COLUMNS.get(table, ())}
    if table == 'canon_climbs': row['canonical_profile'] = []
    if table in tables:
        tables[table] = [row]
        successor.validate_archive_tables(tables)
    row[column] = 'PRIVATE CANARY'
    tables[table] = [row]
    with pytest.raises(ValueError, match='archive allowlist'):
        successor.validate_archive_tables(tables)


def test_canon_plan_cli_runs_through_stdin_without_repository_scripts(tmp_path):
    (tmp_path / 'app').symlink_to(successor.BACKEND / 'app', target_is_directory=True)
    pack = tmp_path / 'SUCCESSORS.json'
    pack.write_bytes(successor.SUCCESSORS.read_bytes())
    result = subprocess.run([sys.executable, '-', 'plan', '--successors', str(pack)],
                            input=Path(successor.__file__).read_text(), text=True,
                            capture_output=True, cwd=tmp_path, env={}, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['count'] == 16


def test_canon_successors_require_exact_confirmation_and_real_actor_time():
    rows = successor.load_successors()
    for confirmation, actor, at in [('', 'Tim', '2026-10-21T01:00:00Z'),
                                    (successor.SUCCESSORS_SHA256, '', '2026-10-21T01:00:00Z'),
                                    (successor.SUCCESSORS_SHA256, 'Tim', 'yesterday')]:
        with pytest.raises(ValueError):
            successor.approved_payloads(rows, confirmation, actor, at)


def test_canon_successors_approval_is_a_copy_and_keeps_geometry():
    rows = successor.load_successors()
    original = deepcopy(rows)
    payloads = successor.approved_payloads(rows, successor.SUCCESSORS_SHA256,
                                         'LOCAL REHEARSAL ONLY', '2026-10-21T01:00:00Z')
    assert rows == original
    assert len(payloads) == 16
    for row, payload in zip(rows, payloads):
        assert row['publish_payload']['compiler_run_mode'] == 'review_only'
        assert payload['compiler_run_mode'] == 'applied'
        for field in ('canonical_profile', 'centerline_wkt', 'gate_start_wkt', 'gate_end_wkt',
                      'length_m', 'vert_m', 'avg_gradient_pct'):
            assert payload['climb'][field] == row['publish_payload']['climb'][field]


def test_canon_successors_refuse_modified_manifest(tmp_path):
    rows = successor.load_successors()
    rows[0]['version'] = 3
    path = tmp_path / 'changed.json'
    path.write_text(json.dumps(rows))
    with pytest.raises(ValueError, match='digest'):
        successor.load_successors(path)


def test_canon_successor_receipt_failure_reports_committed_database(monkeypatch):
    def fail_receipt(value):
        raise OSError('synthetic full disk')
    monkeypatch.setattr(successor.sys, 'stdout', SimpleNamespace(write=fail_receipt))
    with pytest.raises(RuntimeError, match='DB COMMITTED'):
        successor.emit_result({'committed': True}, committed=True)
