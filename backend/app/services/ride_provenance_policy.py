"""Ride ingest provenance policy for automatic economics."""

from __future__ import annotations

from typing import Any, Dict, Optional

MISSING_PRELIMINARY_ATTESTATION_REVIEW_REASON = "missing_preliminary_attestation"
MISSING_PROVIDER_ACTIVITY_REVIEW_REASON = "missing_provider_activity_id"
DUPLICATE_PROVIDER_ACTIVITY_REVIEW_REASON = "duplicate_provider_activity"
PROVENANCE_TIER_FIRST_PARTY_RECORDED = "first_party_recorded"
PROVENANCE_TIER_TRUSTED_PROVIDER_SYNC = "trusted_provider_sync"
PROVENANCE_TIER_MANUAL_FILE_UPLOAD = "manual_file_upload"
PROVENANCE_TIER_LEGACY_UNKNOWN = "legacy_unknown"
ECONOMIC_POLICY_AUTOMATIC_ELIGIBLE = "automatic_economic_eligible"
ECONOMIC_GUARDRAIL_FIRST_PARTY_STAMP = "first_party_attestation_stamp"
ECONOMIC_GUARDRAIL_TRUSTED_PROVIDER = "trusted_provider_provenance"
ECONOMIC_GUARDRAIL_MANUAL_FILE = "manual_file_strict_checks"

TRUSTED_PROVIDER_IMPORT_SOURCES = frozenset(
    {
        "garmin",
        "strava",
        "strava_stream_reconstructed_gpx",
        "wahoo",
    }
)

PROVIDER_IMPORT_SOURCE_ALIASES = {
    "garmin": frozenset({"garmin"}),
    "strava": frozenset({"strava", "strava_stream_reconstructed_gpx"}),
    "wahoo": frozenset({"wahoo"}),
}


def normalise_provider_import_source(value: Any) -> Optional[str]:
    source = _normalise_policy_value(value)
    if source is None:
        return None
    for normalized, aliases in PROVIDER_IMPORT_SOURCE_ALIASES.items():
        if source in aliases:
            return normalized
    return source if source in TRUSTED_PROVIDER_IMPORT_SOURCES else None


def provider_import_source_aliases(value: Any) -> frozenset[str]:
    normalized = normalise_provider_import_source(value)
    if normalized is None:
        return frozenset()
    return PROVIDER_IMPORT_SOURCE_ALIASES.get(normalized, frozenset({normalized}))


def _normalise_policy_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _normalise_identifier_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _truthy_diagnostic(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _provider_activity_id(ride_row: Optional[Dict[str, Any]], diagnostics: Dict[str, Any]) -> Optional[str]:
    row_value = ride_row.get("import_source_id") if isinstance(ride_row, dict) else None
    return _normalise_identifier_value(row_value) or _normalise_identifier_value(
        diagnostics.get("source_activity_id")
    )


def trusted_provider_review_reason(
    ride_row: Optional[Dict[str, Any]],
    diagnostics: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Return a blocking review reason for incomplete provider provenance."""
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    provenance_tier = _normalise_policy_value(diagnostics.get("provenance_tier"))
    import_source = _normalise_policy_value(diagnostics.get("import_source"))
    is_trusted_provider = provenance_tier == PROVENANCE_TIER_TRUSTED_PROVIDER_SYNC or (
        provenance_tier is None and import_source in TRUSTED_PROVIDER_IMPORT_SOURCES
    )
    if not is_trusted_provider:
        return None

    if any(
        _truthy_diagnostic(diagnostics.get(name))
        for name in (
            "duplicate_provider_activity",
            "provider_activity_duplicate",
            "already_imported",
        )
    ):
        return DUPLICATE_PROVIDER_ACTIVITY_REVIEW_REASON

    if not _provider_activity_id(ride_row, diagnostics):
        return MISSING_PROVIDER_ACTIVITY_REVIEW_REASON

    return None


def build_ride_provenance_diagnostics(
    *,
    preliminary_ride_hash: Optional[str],
    parser_version: Optional[int],
    base: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Annotate ride ingest with the witness policy used for economics.

    A BR stop-time preliminary hash is first-party recorder evidence. Trusted
    provider sync and manual file upload can still be economically eligible, but
    they prove trust through provenance and integrity checks instead of the
    mobile recorder stamp.
    """
    diagnostics = dict(base or {})
    has_preliminary_hash = (
        bool(str(preliminary_ride_hash).strip()) if preliminary_ride_hash else False
    )
    has_parser_version = parser_version is not None
    has_any_preliminary_field = has_preliminary_hash or has_parser_version

    existing_tier = _normalise_policy_value(diagnostics.get("provenance_tier"))
    import_source = _normalise_policy_value(diagnostics.get("import_source"))
    source_activity_id = _normalise_identifier_value(diagnostics.get("source_activity_id"))

    if has_any_preliminary_field or existing_tier == PROVENANCE_TIER_FIRST_PARTY_RECORDED:
        provenance_tier = PROVENANCE_TIER_FIRST_PARTY_RECORDED
        ingest_source = PROVENANCE_TIER_FIRST_PARTY_RECORDED
        guardrail_profile = ECONOMIC_GUARDRAIL_FIRST_PARTY_STAMP
        preliminary_required = True
    elif (
        existing_tier == PROVENANCE_TIER_TRUSTED_PROVIDER_SYNC
        or import_source in TRUSTED_PROVIDER_IMPORT_SOURCES
    ):
        provenance_tier = PROVENANCE_TIER_TRUSTED_PROVIDER_SYNC
        ingest_source = import_source or PROVENANCE_TIER_TRUSTED_PROVIDER_SYNC
        guardrail_profile = ECONOMIC_GUARDRAIL_TRUSTED_PROVIDER
        preliminary_required = False
    else:
        provenance_tier = PROVENANCE_TIER_MANUAL_FILE_UPLOAD
        ingest_source = import_source or PROVENANCE_TIER_MANUAL_FILE_UPLOAD
        guardrail_profile = ECONOMIC_GUARDRAIL_MANUAL_FILE
        preliminary_required = False

    diagnostics["provenance_tier"] = provenance_tier
    diagnostics["ingest_source"] = ingest_source
    diagnostics["provenance_economic_policy"] = ECONOMIC_POLICY_AUTOMATIC_ELIGIBLE
    diagnostics["economic_guardrail_profile"] = guardrail_profile
    diagnostics["preliminary_attestation_required"] = preliminary_required
    diagnostics["preliminary_ride_hash_present"] = has_preliminary_hash
    diagnostics["preliminary_parser_version_present"] = has_parser_version
    if source_activity_id:
        diagnostics["source_activity_id"] = source_activity_id

    if preliminary_required and (not has_preliminary_hash or not has_parser_version):
        diagnostics["missing_preliminary_attestation"] = True
        diagnostics["preliminary_attestation_review_reason"] = (
            MISSING_PRELIMINARY_ATTESTATION_REVIEW_REASON
        )
    else:
        diagnostics.pop("missing_preliminary_attestation", None)
        diagnostics.pop("preliminary_attestation_review_reason", None)

    return diagnostics
