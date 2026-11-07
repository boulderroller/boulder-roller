from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

from app.settlement_clock import SettlementClock
from ._alignment_helpers import anchor_program_source, repo_root


def test_settlement_clock_constants_match_across_authoritative_layers() -> None:
    root = repo_root()
    rust = anchor_program_source()
    python = (root / "backend/app/settlement_clock.py").read_text()
    sql = (root / "backend/sql/119_settlement_clock_v2.sql").read_text()

    for source in (rust, python, sql):
        normalized = source.replace("_", "")
        assert "1704020400" in normalized
        assert "1704110400" in normalized
        assert "604800" in normalized
        assert "86400" in normalized


def test_settlement_clock_sql_mirror_is_byte_identical() -> None:
    root = repo_root()
    canonical = root / "backend/sql/119_settlement_clock_v2.sql"
    deploy_mirror = (
        root
        / "backend/supabase/migrations/20260714_126_settlement_clock_v2.sql"
    )

    assert canonical.read_bytes() == deploy_mirror.read_bytes()


def test_active_python_surfaces_do_not_recompute_weeks_from_unix_zero() -> None:
    root = repo_root()
    forbidden = ("* 604800", "* 604_800", "epoch * EPOCH_DURATION")
    active_paths = (
        "backend/app/routes/distributions.py",
        "backend/app/repositories/vault.py",
        "backend/app/services/epoch_processor.py",
    )

    leaks = []
    for relative_path in active_paths:
        text = (root / relative_path).read_text()
        for needle in forbidden:
            if needle in text:
                leaks.append(f"{relative_path}: {needle}")
    assert not leaks, "Unauthoritative Settlement Week conversion:\n  " + "\n  ".join(leaks)


def test_program_config_clock_is_read_at_finalized_commitment() -> None:
    root = repo_root()
    source = (root / "backend/app/solana_direct.py").read_text()
    start = source.index("async def get_program_config_account(")
    end = source.index("async def get_program_settlement_clock(", start)
    reader = source[start:end]

    assert "commitment=Finalized" in reader
    assert "get_account_info(\n                config_pda,\n                commitment=Finalized" in reader


def test_python_week_helpers_cannot_synthesize_a_fallback_clock() -> None:
    root = repo_root()
    direct = (root / "backend/app/solana_direct.py").read_text()
    dry_run = (root / "scripts/test_epoch_distribution.py").read_text()

    assert "SettlementClock.v2_only()" not in direct
    assert "get_program_settlement_clock" in dry_run
    assert "get_current_epoch(settlement_clock)" in dry_run


def test_sql_cutover_stores_history_and_clock_provenance() -> None:
    root = repo_root()
    sql = (root / "backend/sql/119_settlement_clock_v2.sql").read_text()

    assert "settlement_clock_contract" in sql
    assert "ADD COLUMN IF NOT EXISTS settlement_week BIGINT" in sql
    assert "legacy-v1:1704020400:604800:86400" in sql
    assert "RETURN 1;" in sql
    assert "vc.settlement_week" in sql
    assert "br_settlement_week_end" in sql
    assert "is_cutover_week" in sql
    assert "settlement_clock_source_commitment" in sql
    assert "program_config_commitment" in sql
    assert "sha256" in sql
    assert "direct settlement_clock_contract insert is forbidden" in sql


def test_runtime_clients_do_not_own_a_second_settlement_clock() -> None:
    root = repo_root()
    for relative_path in (
        "web/portal/src",
        "mobile/src",
        "indexer/src",
    ):
        for path in (root / relative_path).rglob("*"):
            if path.suffix not in {".ts", ".tsx"}:
                continue
            # Previously banned the indexer's server-side Week projection with browser clocks; verify its canonical parity below.
            if path == root / "indexer/src/observatory.ts":
                continue
            text = path.read_text(encoding="utf-8")
            assert "1704110400" not in text, f"client-owned anchor in {path}"

    vectors = []
    expected = []
    anchor = 1_704_110_400
    duration = 604_800
    for cutover in [anchor, anchor + 100 * duration]:
        config = {"settlement_clock_version": 2, "settlement_clock_v2_starts_at": cutover, "chain_slot": 42}
        clock = SettlementClock.from_program_config(config)
        for timestamp in [anchor - 1, anchor, cutover - 90_001, cutover - 90_000, cutover - 1, cutover, cutover + duration - 1, cutover + duration, cutover + duration + 86_400]:
            vectors.append([config, datetime.fromtimestamp(timestamp, timezone.utc).isoformat()])
            window = clock.window_at(timestamp)
            expected.append({"epoch": window.settlement_week, "starts_at": window.starts_at, "ends_at": window.ends_at, "finalizes_at": window.finalizes_at})
    for config in [None, {}, {"settlement_clock_version": 1, "settlement_clock_v2_starts_at": anchor, "chain_slot": 42}, {"settlement_clock_version": 2, "settlement_clock_v2_starts_at": anchor + 1, "chain_slot": 42}, {"settlement_clock_version": 2, "settlement_clock_v2_starts_at": anchor}]:
        vectors.append([config, "2026-09-07T15:15:06Z"])
        expected.append({})
    # Use the indexer's installed TS runtime, including on backend CI's Node 20.
    script = """
require('tsx/cjs');
const { projectWeekClock } = require('./src/observatory.ts');
(async () => {
  let input = '';
  for await (const chunk of process.stdin) input += chunk;
  process.stdout.write(JSON.stringify(
    JSON.parse(input).map(args => projectWeekClock(...args))
  ));
})();
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=root / "indexer",
        input=json.dumps(vectors),
        text=True,
        capture_output=True,
        check=True,
        timeout=20,
    )
    assert json.loads(result.stdout) == expected
    api = (root / "indexer/src/api.ts").read_text()
    assert "SELECT settlement_clock_version, settlement_clock_v2_starts_at, chain_slot" in api
    assert "FROM indexed_program_config WHERE id = 1" in api
    assert "projectWeekClock(clockResult.rows[0], indexed?.at)" in api
