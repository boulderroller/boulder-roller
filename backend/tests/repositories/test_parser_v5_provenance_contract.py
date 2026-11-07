from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
VECTOR = REPO_ROOT / "tests/fixtures/canonical_ride_v5_vectors.json"
V4_VECTOR = REPO_ROOT / "tests/fixtures/canonical_ride_v4_vectors.json"
CANONICAL_SQL = REPO_ROOT / "backend/sql/130_cal_tribute_policy.sql"
SUPABASE_SQL = (
    REPO_ROOT
    / "backend/supabase/migrations/20260716_138_cal_tribute_policy.sql"
)

IMPLEMENTATION_COMMIT = "73bfee87359b0573014c16674e36ae6639a0276f"
V4_IMPLEMENTATION_COMMIT = "bb7604ddc0af3f983d0a21191bf27bddfa463e80"


def test_v5_fixture_is_exact_and_preserves_v4_canonical_semantics() -> None:
    fixture = json.loads(VECTOR.read_text(encoding="utf-8"))
    v4_fixture = json.loads(V4_VECTOR.read_text(encoding="utf-8"))
    assert fixture["parser_version"] == 5

    expected_hashes = {
        "rust_sample_activity": (
            "381819dfc442184171277f0a2b07da4c7fa1194c4a8b70de4ee5d660bb54d229"
        ),
        "reference_gpx_file": (
            "5e1f79829431b1efac688971eeb8735bedaafb87d08ec988dfc05d510f5f02e7"
        ),
    }
    for name, expected_hash in expected_hashes.items():
        vector = fixture["vectors"][name]
        canonical = vector["canonical_json"].encode("utf-8")
        assert hashlib.sha256(canonical).hexdigest() == expected_hash
        assert vector["ride_hash"] == expected_hash

        v5_canonical = json.loads(vector["canonical_json"])
        v5_canonical["parser_version"] = 4
        assert v5_canonical == json.loads(
            v4_fixture["vectors"][name]["canonical_json"]
        )


def test_v5_pipeline_registration_is_exact_idempotent_and_mirrored() -> None:
    canonical = CANONICAL_SQL.read_text(encoding="utf-8")
    supabase = SUPABASE_SQL.read_text(encoding="utf-8")
    assert canonical == supabase

    assert "'5-ftp-v1'" in canonical
    assert "ride_parser_version IS DISTINCT FROM 5" in canonical
    assert f"'{IMPLEMENTATION_COMMIT}'" in canonical
    assert "'4-ftp-v1'" in canonical
    assert "ride_parser_version IS DISTINCT FROM 4" in canonical
    assert f"'{V4_IMPLEMENTATION_COMMIT}'" in canonical
    assert "parser V5 requires the exact active V4 authority" in canonical
    assert "parser V5 pipeline provenance conflict" in canonical
    assert "inactive and cannot be reactivated" in canonical
    assert "WHERE deactivated_at IS NULL AND id <> v_v5_id" in canonical
    assert "new CAL tribute plans require parser V5 authority" in canonical


def test_canonical_docs_name_v5_as_current_without_erasing_v4_replay() -> None:
    canonicalization = (
        REPO_ROOT / "docs/design/RIDE_CANONICALIZATION_SPEC.md"
    ).read_text(encoding="utf-8")
    backend_truths = (REPO_ROOT / "docs/BACKEND_TRUTHS.md").read_text(
        encoding="utf-8"
    )
    vault_matching = (REPO_ROOT / "docs/VAULT_MATCHING_SYSTEMS.md").read_text(
        encoding="utf-8"
    )
    audit = (REPO_ROOT / "docs/design/MATH_AUDIT_2026-07-09.md").read_text(
        encoding="utf-8"
    )

    assert "**V5** is current" in canonicalization
    assert "V5 is current" in backend_truths
    assert "V1-V4 remain replayable" in backend_truths
    assert "`5-ftp-v1` pipeline vector" in vault_matching
    assert "`boulderroller-v2-rn80`" in audit
    assert "immutable `5-ftp-v1`" in audit
