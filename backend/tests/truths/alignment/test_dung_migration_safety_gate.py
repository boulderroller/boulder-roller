import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = Path(
    os.environ.get(
        "DUNG_MIGRATION_SCRIPT_UNDER_TEST",
        REPO_ROOT / "protocol/anchor/scripts/migrate_dung_liability_reservation.ts",
    )
)
DEPLOYMENT_VALIDATOR = REPO_ROOT / "protocol/anchor/scripts/validate_deployment.ts"


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_vault_stake_census_queries_by_discriminator_before_validating_size() -> None:
    source = _source()

    assert "filters: [{ dataSize: VAULT_STAKE_SIZE }]" not in source
    assert "anchor.utils.bytes.bs58.encode(discriminator)" in source
    assert "account.data.length !== VAULT_STAKE_SIZE" in source


def test_admin_authorizes_while_a_distinct_payer_funds_migration() -> None:
    source = _source()

    assert "payer: options.payerPubkey" in source
    assert "payerKey: payer.publicKey" in source
    assert "transaction.sign([payer, authority])" in source
    assert "admin cannot be used as the migration fee payer" in source


def test_execute_requires_prepared_transport_and_reviewed_hashes() -> None:
    source = _source()

    assert 'arg === "--prepare-alt"' in source
    assert 'arg === "--simulate-only"' in source
    assert 'arg === "--operations-paused"' in source
    assert "require a pre-created --lookup-table" in source
    assert "--expected-manifest-sha256" in source
    assert "--expected-plan-sha256" in source
    assert "minContextSlot: migrationSlot" in source


def test_versioned_layout_supports_claim_only_top_up_and_current_policy() -> None:
    source = _source()

    assert "CLAIM_ONLY_DUNG_MINT_STATE_SIZE = 129" in source
    assert "CURRENT_DUNG_MINT_STATE_SIZE = 130" in source
    assert "DUNG_RESERVATION_POLICY_VERSION = 1" in source


def test_deployment_validator_requires_current_reservation_policy() -> None:
    source = DEPLOYMENT_VALIDATOR.read_text(encoding="utf-8")

    assert "CLAIM_ONLY_DUNG_MINT_STATE_SIZE = 129" in source
    assert "CURRENT_DUNG_MINT_STATE_SIZE = 130" in source
    assert "DUNG_RESERVATION_POLICY_VERSION = 1" in source
    assert "reservationPolicyVersion !== DUNG_RESERVATION_POLICY_VERSION" in source
