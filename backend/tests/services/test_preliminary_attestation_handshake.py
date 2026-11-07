from app.services.ride_processor import (
    OnchainRideIdentity,
    evaluate_preliminary_attestation,
)
from app.services.ride_attester import MISSING_PRELIMINARY_ATTESTATION_REVIEW_REASON
from app.services.ride_provenance_policy import (
    DUPLICATE_PROVIDER_ACTIVITY_REVIEW_REASON,
    ECONOMIC_GUARDRAIL_FIRST_PARTY_STAMP,
    ECONOMIC_GUARDRAIL_MANUAL_FILE,
    ECONOMIC_GUARDRAIL_TRUSTED_PROVIDER,
    MISSING_PROVIDER_ACTIVITY_REVIEW_REASON,
    PROVENANCE_TIER_FIRST_PARTY_RECORDED,
    PROVENANCE_TIER_MANUAL_FILE_UPLOAD,
    PROVENANCE_TIER_TRUSTED_PROVIDER_SYNC,
    build_ride_provenance_diagnostics,
)


def _identity(ride_hash_hex: str = "ab" * 32, parser_version: int = 1) -> OnchainRideIdentity:
    ride_hash = bytes.fromhex(ride_hash_hex)
    return OnchainRideIdentity(
        ride_hash=ride_hash,
        attestation_commitment=ride_hash,
        parser_version=parser_version,
        source_kind=1,
    )


def test_evaluate_preliminary_attestation_accepts_legacy_missing_fields() -> None:
    result = evaluate_preliminary_attestation({}, _identity(), file_type="fit")

    assert result.requires_review is False
    assert result.canonical_match is None
    assert result.review_reason is None


def test_evaluate_preliminary_attestation_requires_first_party_recorder_stamp() -> None:
    result = evaluate_preliminary_attestation(
        {
            "import_diagnostics": {
                "provenance_tier": PROVENANCE_TIER_FIRST_PARTY_RECORDED,
                "preliminary_attestation_required": True,
            }
        },
        _identity(),
        file_type="fit",
    )

    assert result.requires_review is True
    assert result.canonical_match is False
    assert result.review_reason == MISSING_PRELIMINARY_ATTESTATION_REVIEW_REASON


def test_evaluate_preliminary_attestation_allows_manual_upload_without_recorder_stamp() -> None:
    result = evaluate_preliminary_attestation(
        {
            "import_diagnostics": build_ride_provenance_diagnostics(
                preliminary_ride_hash=None,
                parser_version=None,
            )
        },
        _identity(),
        file_type="fit",
    )

    assert result.requires_review is False
    assert result.canonical_match is None
    assert result.review_reason is None


def test_build_ride_provenance_diagnostics_marks_first_party_recorded() -> None:
    diagnostics = build_ride_provenance_diagnostics(
        preliminary_ride_hash="ab" * 32,
        parser_version=1,
    )

    assert diagnostics["provenance_tier"] == PROVENANCE_TIER_FIRST_PARTY_RECORDED
    assert diagnostics["ingest_source"] == PROVENANCE_TIER_FIRST_PARTY_RECORDED
    assert diagnostics["economic_guardrail_profile"] == ECONOMIC_GUARDRAIL_FIRST_PARTY_STAMP
    assert diagnostics["preliminary_attestation_required"] is True
    assert diagnostics["preliminary_ride_hash_present"] is True
    assert diagnostics["preliminary_parser_version_present"] is True
    assert "missing_preliminary_attestation" not in diagnostics


def test_build_ride_provenance_diagnostics_marks_manual_file_upload() -> None:
    diagnostics = build_ride_provenance_diagnostics(
        preliminary_ride_hash=None,
        parser_version=None,
    )

    assert diagnostics["provenance_tier"] == PROVENANCE_TIER_MANUAL_FILE_UPLOAD
    assert diagnostics["ingest_source"] == PROVENANCE_TIER_MANUAL_FILE_UPLOAD
    assert diagnostics["economic_guardrail_profile"] == ECONOMIC_GUARDRAIL_MANUAL_FILE
    assert diagnostics["preliminary_attestation_required"] is False
    assert diagnostics["preliminary_ride_hash_present"] is False
    assert diagnostics["preliminary_parser_version_present"] is False
    assert "missing_preliminary_attestation" not in diagnostics


def test_build_ride_provenance_diagnostics_marks_trusted_provider_sync() -> None:
    diagnostics = build_ride_provenance_diagnostics(
        preliminary_ride_hash=None,
        parser_version=None,
        base={
            "import_source": "strava_stream_reconstructed_gpx",
            "source_activity_id": "Strava-ACTIVITY-123",
        },
    )

    assert diagnostics["provenance_tier"] == PROVENANCE_TIER_TRUSTED_PROVIDER_SYNC
    assert diagnostics["ingest_source"] == "strava_stream_reconstructed_gpx"
    assert diagnostics["source_activity_id"] == "Strava-ACTIVITY-123"
    assert diagnostics["economic_guardrail_profile"] == ECONOMIC_GUARDRAIL_TRUSTED_PROVIDER
    assert diagnostics["preliminary_attestation_required"] is False


def test_evaluate_preliminary_attestation_requires_provider_activity_id_for_trusted_sync() -> None:
    diagnostics = build_ride_provenance_diagnostics(
        preliminary_ride_hash=None,
        parser_version=None,
        base={"import_source": "strava_stream_reconstructed_gpx"},
    )

    result = evaluate_preliminary_attestation(
        {"import_diagnostics": diagnostics},
        _identity(),
        file_type="gpx",
    )

    assert result.requires_review is True
    assert result.canonical_match is False
    assert result.review_reason == MISSING_PROVIDER_ACTIVITY_REVIEW_REASON


def test_evaluate_preliminary_attestation_allows_trusted_sync_with_row_import_source_id() -> None:
    diagnostics = build_ride_provenance_diagnostics(
        preliminary_ride_hash=None,
        parser_version=None,
        base={"import_source": "strava_stream_reconstructed_gpx"},
    )

    result = evaluate_preliminary_attestation(
        {"import_source_id": "12345", "import_diagnostics": diagnostics},
        _identity(),
        file_type="gpx",
    )

    assert result.requires_review is False
    assert result.canonical_match is None
    assert result.review_reason is None


def test_evaluate_preliminary_attestation_blocks_duplicate_provider_activity() -> None:
    diagnostics = build_ride_provenance_diagnostics(
        preliminary_ride_hash=None,
        parser_version=None,
        base={
            "import_source": "strava_stream_reconstructed_gpx",
            "source_activity_id": "12345",
            "duplicate_provider_activity": True,
        },
    )

    result = evaluate_preliminary_attestation(
        {"import_source_id": "12345", "import_diagnostics": diagnostics},
        _identity(),
        file_type="gpx",
    )

    assert result.requires_review is True
    assert result.canonical_match is False
    assert result.review_reason == DUPLICATE_PROVIDER_ACTIVITY_REVIEW_REASON


def test_evaluate_preliminary_attestation_marks_invalid_parser_under_review() -> None:
    result = evaluate_preliminary_attestation(
        {
            "preliminary_ride_hash_hex": "ab" * 32,
            "preliminary_parser_version": "not-an-int",
        },
        _identity(),
        file_type="fit",
    )

    assert result.requires_review is True
    assert result.canonical_match is False
    assert result.review_reason == "invalid_preliminary_parser_version"


def test_evaluate_preliminary_attestation_marks_hash_mismatch_under_review() -> None:
    result = evaluate_preliminary_attestation(
        {
            "preliminary_ride_hash_hex": "cd" * 32,
            "preliminary_parser_version": 1,
        },
        _identity(),
        file_type="fit",
    )

    assert result.requires_review is True
    assert result.canonical_match is False
    assert result.review_reason == "preliminary_hash_mismatch"


def test_evaluate_preliminary_attestation_marks_parser_mismatch_under_review() -> None:
    result = evaluate_preliminary_attestation(
        {
            "preliminary_ride_hash_hex": "ab" * 32,
            "preliminary_parser_version": 2,
        },
        _identity(parser_version=1),
        file_type="fit",
    )

    assert result.requires_review is True
    assert result.canonical_match is False
    assert result.review_reason == "parser_version_mismatch"


def test_evaluate_preliminary_attestation_accepts_matching_preliminary_hash() -> None:
    result = evaluate_preliminary_attestation(
        {
            "preliminary_ride_hash_hex": "ab" * 32,
            "preliminary_parser_version": 1,
        },
        _identity(),
        file_type="fit",
    )

    assert result.requires_review is False
    assert result.canonical_match is True
    assert result.review_reason is None


def test_evaluate_preliminary_attestation_enforces_gpx_hash_mismatch() -> None:
    result = evaluate_preliminary_attestation(
        {
            "preliminary_ride_hash_hex": "cd" * 32,
            "preliminary_parser_version": 1,
        },
        _identity(),
        file_type="gpx",
    )

    assert result.requires_review is True
    assert result.canonical_match is False
    assert result.review_reason == "preliminary_hash_mismatch"


def test_evaluate_preliminary_attestation_accepts_matching_gpx_hash() -> None:
    result = evaluate_preliminary_attestation(
        {
            "preliminary_ride_hash_hex": "ab" * 32,
            "preliminary_parser_version": 1,
        },
        _identity(),
        file_type="gpx",
    )

    assert result.requires_review is False
    assert result.canonical_match is True
    assert result.review_reason is None
