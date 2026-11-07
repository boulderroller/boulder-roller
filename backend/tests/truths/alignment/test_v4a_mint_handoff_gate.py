"""Static safety gate for the one-time V4-A -> V4-B mint handoff."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
SETUP_SCRIPT = REPO_ROOT / "protocol/anchor/scripts/setup-devnet.ts"
OPERATOR_SCRIPT = (
    REPO_ROOT / "protocol/anchor/scripts/execute_v4a_mint_handoff.mjs"
)
BRIDGE_SOURCE = (
    REPO_ROOT / "protocol/migrations/v4a_mint_handoff/src/lib.rs"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_fresh_bootstrap_can_defer_only_from_one_exact_prior_program() -> None:
    setup = _read(SETUP_SCRIPT)

    assert "--defer-mint-authority-handoff-from <program-id>" in setup
    assert "deferMintAuthorityHandoffFrom?: PublicKey" in setup
    assert "deferredCalAuthority" in setup
    assert "deferredDungAuthority" in setup
    assert "CAL mint authority handoff deferred to the reviewed bridge" in setup
    assert "DUNG mint authority handoff deferred to the reviewed bridge" in setup
    assert 'import BN from "bn.js";' in setup
    assert "anchor.BN" not in setup


def test_operator_is_finalized_dry_run_by_default_and_verifies_both_mints() -> None:
    operator = _read(OPERATOR_SCRIPT)

    assert "send: false" in operator
    assert "deployed V4-A bytes do not equal the reviewed handoff bridge" in operator
    assert "fresh V4-B ProgramConfig is not version 0x4B" in operator
    assert "preflightCommitment: 'finalized'" in operator
    assert "finalized CAL mint authority does not equal the V4-B PDA" in operator
    assert "finalized DUNG mint authority does not equal the V4-B PDA" in operator


def test_bridge_binds_exact_roles_mints_version_and_atomic_cpis() -> None:
    bridge = _read(BRIDGE_SOURCE)

    assert 'pubkey!("G8DM5Dn12fsgkKxbdUUtFVJsqMXTcJqPU9no7koqwcKH")' in bridge
    assert 'pubkey!("CJz8PUyNVvLuXJvjsYXgSKD9utZVP2XoTEZq6M973Gha")' in bridge
    assert 'pubkey!("4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh")' in bridge
    assert 'pubkey!("CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk")' in bridge
    assert "const V4B_PROGRAM_VERSION: u8 = 0x4B;" in bridge
    assert bridge.count("\n    invoke_signed(") == 2
