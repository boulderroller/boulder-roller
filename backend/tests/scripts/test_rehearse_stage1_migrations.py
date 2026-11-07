"""The rehearsal follows canonical discovery, including future migrations."""
from backend.scripts import rehearse_stage1_migrations as rehearsal


def test_expected_migrations_follow_the_selected_directory(tmp_path):
    names = [
        "168_before_stage1.sql", "169_stage1.sql", "174_pending_intents.sql",
        "175_efforts.sql", "176_new_best.sql", "177_privacy.sql",
        "178_db_hygiene.sql", "179_future.sql",
    ]
    for name in reversed(names):
        (tmp_path / name).write_text("SELECT 1;\n")
    (tmp_path / "README.md").write_text("Not a migration")
    (tmp_path / "180_directory.sql").mkdir()
    assert rehearsal.expected_migrations(tmp_path) == names[1:]


def test_expected_migrations_include_the_current_canonical_tail():
    expected = rehearsal.expected_migrations(rehearsal.BACKEND / "sql")
    assert expected[0] == "169_stage1_program_version_window.sql"
    assert "175_climb_effort_metrics.sql" in expected
    assert "176_vault_completion_new_best.sql" in expected
    assert "177_share_wkg_privacy.sql" in expected
    assert "178_db_hygiene.sql" in expected
