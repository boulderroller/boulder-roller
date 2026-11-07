from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from solders.pubkey import Pubkey

import app.solana_direct as solana_direct
import app.services.vault_completion_evidence as completion_evidence

from ._alignment_helpers import anchor_program_source


ROOT = Path(__file__).resolve().parents[4]
CANONICAL_SQL = ROOT / "backend/sql/125_completion_tribute_evidence_v2.sql"
MIGRATION_SQL = (
    ROOT
    / "backend/supabase/migrations/20260714_133_completion_tribute_evidence_v2.sql"
)
INDEXER_REPLAY = ROOT / "indexer/src/modes/replay.ts"
INDEXER_WRITER = ROOT / "indexer/src/writers/identity.ts"


def test_v2_hash_binds_exact_tribute_with_frozen_byte_layout() -> None:
    builder = getattr(completion_evidence, "build_climb_completion_evidence_v2")
    ride_attestation = Pubkey.new_unique()
    vault = Pubkey.new_unique()
    expected = hashlib.sha256(
        b"BR_CLIMB_COMPLETION_V2"
        + bytes(ride_attestation)
        + bytes(vault)
        + struct.pack("<I", 615)
        + struct.pack("<Q", 123_000_000_000)
    ).digest()

    actual = builder(
        ride_attestation=ride_attestation,
        vault=vault,
        completion_time_s=615,
        cal_tribute=123_000_000_000,
    )

    assert actual == expected
    assert actual != builder(
        ride_attestation=ride_attestation,
        vault=vault,
        completion_time_s=615,
        cal_tribute=123_000_000_001,
    )


def test_v2_direct_instruction_uses_distinct_discriminator_and_exact_hash() -> None:
    builder = getattr(solana_direct, "make_record_climb_completion_v2_ix")
    authority = Pubkey.new_unique()
    rider = Pubkey.new_unique()
    program_id = Pubkey.new_unique()
    ride_hash = hashlib.sha256(b"ride-v2").digest()
    ride_attestation, _ = solana_direct._derive_ride_attestation_pda(
        rider, ride_hash, program_id
    )
    vault, _ = solana_direct._derive_vault_pda(42, program_id)
    evidence_hash = completion_evidence.build_climb_completion_evidence_v2(
        ride_attestation=ride_attestation,
        vault=vault,
        completion_time_s=615,
        cal_tribute=77,
    )

    instruction = builder(
        authority=authority,
        rider=rider,
        ride_hash=ride_hash,
        vault_id=42,
        completion_time_s=615,
        cal_tribute=77,
        completion_evidence_hash=evidence_hash,
        program_id=program_id,
    )

    assert instruction.data[:8] == hashlib.sha256(
        b"global:record_climb_completion_v2"
    ).digest()[:8]
    assert instruction.data[20:52] == evidence_hash


def test_protocol_removed_v1_and_keeps_tribute_bound_v2() -> None:
    source = anchor_program_source()

    assert "pub struct ClimbCompletionReceiptV2" in source
    assert "pub fn record_climb_completion_v2" in source
    assert "build_climb_completion_evidence_v2" in source
    assert "LegacyCompletionEvidenceDisabled" in source
    assert "CompletionEvidenceMismatch" in source
    assert "receipt.evidence_version = 2;" in source
    assert "receipt.cal_tributed = cal_tribute;" in source
    # Program 0x4E removed the tribute-unbound V1 entry and its receipt type;
    # the error ordinal stays reserved.
    assert "pub fn record_climb_completion<" not in source
    assert "pub struct ClimbCompletionReceipt {" not in source


def test_evidence_version_is_projected_by_mirrored_sql_and_indexer() -> None:
    assert CANONICAL_SQL.read_bytes() == MIGRATION_SQL.read_bytes()
    sql = CANONICAL_SQL.read_text()
    replay = INDEXER_REPLAY.read_text()
    writer = INDEXER_WRITER.read_text()

    assert "completion_evidence_version" in sql
    assert "br_require_tribute_bound_review_resolution" in sql
    assert "ClimbCompletionFlowAssignedV2" in replay
    assert "evidenceVersion: 2" in replay
    assert "writeClimbCompletionReceiptV2" in writer
    assert "completion_evidence_hash" in writer
    assert "cal_tributed" in writer
