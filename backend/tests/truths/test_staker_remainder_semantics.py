import re
from pathlib import Path


BACKEND_ROOT = Path(__file__).parents[2]
REPO_ROOT = BACKEND_ROOT.parent
PROGRAM_SRC = REPO_ROOT / "protocol" / "anchor" / "programs" / "boulder_rollers" / "src"
INDEXER_API = REPO_ROOT / "indexer" / "src" / "api.ts"
INDEXER_VAULT_WRITER = REPO_ROOT / "indexer" / "src" / "writers" / "vault.ts"
SCAN_VAULT_PAGE = REPO_ROOT / "web" / "scan" / "src" / "pages" / "VaultPage.tsx"
SCAN_SETTLEMENT = REPO_ROOT / "web" / "scan" / "src" / "lib" / "settlement.ts"
CANONICAL_MIGRATION = BACKEND_ROOT / "sql" / "131_staker_remainder_semantics.sql"
SUPABASE_MIGRATION = (
    BACKEND_ROOT
    / "supabase"
    / "migrations"
    / "20260716_139_staker_remainder_semantics.sql"
)



def _program_source() -> str:
    """The Anchor program's Rust source, joined across every module file."""
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(PROGRAM_SRC.glob("*.rs")))

def test_staker_remainder_comment_migrations_are_identical() -> None:
    assert CANONICAL_MIGRATION.read_bytes() == SUPABASE_MIGRATION.read_bytes()


def test_staker_remainder_comments_preserve_policy_and_historical_meanings() -> None:
    sql = CANONICAL_MIGRATION.read_text()

    assert "staker_remainder_policy_version" in sql
    assert "unmarked legacy carry awaiting Leaderboard pool cutover" in sql
    assert "already-unlocked staker pro-rata integer dust" in sql
    assert "never an input to the participation curve" in sql
    assert "paired StakerRemainderPolicyApplied rows mean same-week Leaderboard pool" in sql
    assert "historical unmarked rows mean locked staker carry" in sql
    assert "COMMENT ON COLUMN indexed_vaults.carry_stakers" in sql
    assert "COMMENT ON COLUMN indexed_epoch_distributions.locked_staker_amount" in sql


def test_staker_remainder_cutover_is_explicit_and_history_aware() -> None:
    program = _program_source()
    indexer = INDEXER_API.read_text()
    vault_writer = INDEXER_VAULT_WRITER.read_text()
    scan_vault_page = SCAN_VAULT_PAGE.read_text()
    scan_settlement = SCAN_SETTLEMENT.read_text()

    assert "STAKER_REMAINDER_POLICY_MARKER" in program
    assert "classify_prior_staker_carry(vault.reward_rate" in program
    assert "legacy_carry_reallocated: prior_staker_carry.legacy_locked" in program
    assert "emit!(StakerRemainderPolicyApplied" in program
    assert "StakerRemainderPolicyApplied" in indexer
    assert "Balance sweep" in indexer
    assert "Leaderboard pool" in indexer
    assert "Staker allocation" in indexer
    assert "Prior staker balance" in indexer
    assert "staker_remainder_policy_version" in vault_writer
    # Previously pinned the retired Vault carry label; ratified Settlements link to receipts, whose indexed flows retain the historical policy distinction.
    settlement_row = scan_vault_page.split("function SettlementRow(", 1)[1].split("export default", 1)[0]
    assert 'to={`/tx/${row.signature}`}' in settlement_row
    assert "row.week" in settlement_row
    assert 'formatAtomic(row.dung, "DUNG", 9, 2)' in settlement_row
    assert re.search(r"sameWeekPolicySettlements\.has\(\s*settlementPolicyKey\(fields\) \?\? ''\s*\)", indexer)
    assert "usesSameWeekPolicy ? 'Leaderboard pool' : 'Prior staker balance'" in indexer
    assert "Staker rounding remainder" in scan_settlement
    assert "Prior staker balance" in scan_settlement


def test_indexer_policy_marker_matches_the_on_chain_constant() -> None:
    program = _program_source()
    vault_writer = INDEXER_VAULT_WRITER.read_text()

    rust_marker = re.search(
        r"STAKER_REMAINDER_POLICY_MARKER: u64 = (0x[0-9A-F_]+);",
        program,
    )
    indexer_marker = re.search(
        r"STAKER_REMAINDER_POLICY_MARKER = (0x[0-9A-F_]+)n;",
        vault_writer,
    )
    rust_version = re.search(
        r"STAKER_REMAINDER_POLICY_VERSION: u8 = (\d+);",
        program,
    )
    indexer_version = re.search(
        r"STAKER_REMAINDER_POLICY_VERSION = (\d+);",
        vault_writer,
    )

    assert rust_marker and indexer_marker
    assert int(rust_marker.group(1).replace("_", ""), 16) == int(
        indexer_marker.group(1).replace("_", ""),
        16,
    )
    assert rust_version and indexer_version
    assert rust_version.group(1) == indexer_version.group(1)
