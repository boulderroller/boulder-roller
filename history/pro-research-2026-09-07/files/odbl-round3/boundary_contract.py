from __future__ import annotations
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit
from uuid import UUID
# Reference capability/immutability contract; not the deployed matcher or chain builder.
# No atlas reader, database client, network fallback or global private store is imported.
# SHA-256 below identifies export bytes; it is NOT a replacement for protocol BLAKE3.
class BoundaryError(ValueError):
    pass
@dataclass(frozen=True, order=True)
class ClimbKey:
    canon_id: str
    canon_version: int
    geographic_revision_id: str
@dataclass(frozen=True)
class FrozenClimb:
    key: ClimbKey
    geography_bytes: bytes
    canonical_profile_bytes: bytes
    def geographic_document(self) -> dict[str, Any]:
        return json.loads(self.geography_bytes)
@dataclass(frozen=True)
class PublicationReceipt:
    export_uri: str
    manifest_sha256: str
    archive_verified: bool
    source_closure_approved: bool
    ratification_approved: bool
@dataclass(frozen=True)
class PublishedRelease:
    release_id: str
    receipt: PublicationReceipt
    climbs: tuple[FrozenClimb, ...]
REQUIRED_GEOGRAPHIC_FIELDS = frozenset({
    'centerline', 'gates', 'corridor', 'h3_cells', 'profile_samples',
    'sources', 'notice_ids', 'geometry_policy', 'profile_serializer_id',
})
OPTIONAL_GEOGRAPHIC_FIELDS = frozenset({
    'public_name', 'direction', 'status', 'predecessor', 'continuity_policy',
    'public_revision_rationale', 'osm_provenance', 'vertical_datum',
    'traversal_policy', 'lossless_geometry',
})
# This exact public DTO allowlist is deliberately closed. Adding a geographic field
# requires export classification/review; the production schema will need its real fields.
def _validate_json(value: Any) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BoundaryError('Non-finite JSON value')
        return
    if isinstance(value, list):
        for child in value:
            _validate_json(child)
        return
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        for child in value.values():
            _validate_json(child)
        return
    raise BoundaryError('Unsupported JSON type')
def revision_digest(geography_bytes: bytes, profile_bytes: bytes) -> str:
    message = b'BR_GEOGRAPHY_EXPORT_V1\x00'
    message += len(geography_bytes).to_bytes(8, 'big') + geography_bytes + profile_bytes
    return hashlib.sha256(message).hexdigest()
def freeze_approved_geography(canon_id: str, canon_version: int,
                             geography: Mapping[str, Any],
                             profile_bytes: bytes) -> FrozenClimb:
    # Caller is the dedicated publisher after substantive approvals; this function
    # cannot establish title, ratification or source facts from a caller's assertion.
    try:
        canonical_id = str(UUID(canon_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise BoundaryError('Invalid UUID') from exc
    if type(canon_version) is not int or not 1 <= canon_version <= 65535:
        raise BoundaryError('Invalid v1 canon version')
    if type(profile_bytes) is not bytes or not profile_bytes:
        raise BoundaryError('Exact nonempty profile bytes required')
    body = dict(geography)
    fields = set(body)
    if not REQUIRED_GEOGRAPHIC_FIELDS <= fields:
        raise BoundaryError('Missing public geographic field')
    if fields - REQUIRED_GEOGRAPHIC_FIELDS - OPTIONAL_GEOGRAPHIC_FIELDS:
        raise BoundaryError('Unclassified field: cannot publish')
    _validate_json(body)
    geographic_bytes = json.dumps(body, sort_keys=True, separators=(',', ':'),
                                 ensure_ascii=False, allow_nan=False).encode('utf-8')
    digest = revision_digest(geographic_bytes, profile_bytes)
    return FrozenClimb(ClimbKey(canonical_id, canon_version, digest),
                       geographic_bytes, profile_bytes)
def publish_release(release_id: str, receipt: PublicationReceipt,
                    climbs: Iterable[FrozenClimb]) -> PublishedRelease:
    if not release_id or not isinstance(release_id, str):
        raise BoundaryError('Immutable release ID required')
    parts = urlsplit(receipt.export_uri)
    if parts.scheme != 'https' or not parts.netloc or parts.username or parts.password:
        raise BoundaryError('Public HTTPS export URI required')
    if (len(receipt.manifest_sha256) != 64 or
            any(c not in '0123456789abcdef' for c in receipt.manifest_sha256)):
        raise BoundaryError('Manifest SHA-256 required')
    if not all((receipt.archive_verified, receipt.source_closure_approved,
                receipt.ratification_approved)):
        raise BoundaryError('Unverified publication prerequisite')
    rows = tuple(sorted(climbs, key=lambda x: x.key))
    keys = [row.key for row in rows]
    if len(keys) != len(set(keys)):
        raise BoundaryError('Duplicate revision key')
    for row in rows:
        if row.key.geographic_revision_id != revision_digest(
                row.geography_bytes, row.canonical_profile_bytes):
            raise BoundaryError('Mutated or forged geographic revision')
    return PublishedRelease(release_id, receipt, rows)
class PublishedReader:
    def __init__(self, release: PublishedRelease) -> None:
        # A capability must be constructed only from the publisher's authenticated
        # persisted release. Python types alone are not an authorization system.
        self._release = release
        self._index = {row.key: row for row in release.climbs}
    @property
    def release_id(self) -> str:
        return self._release.release_id
    def keys(self) -> tuple[ClimbKey, ...]:
        return tuple(row.key for row in self._release.climbs)
    def require(self, key: ClimbKey) -> FrozenClimb:
        try:
            return self._index[key]
        except KeyError as exc:
            raise BoundaryError('No such published geographic revision') from exc
    def api_geography(self, key: ClimbKey) -> dict[str, Any]:
        row = self.require(key)
        return {
            'release_id': self.release_id,
            'canon_id': key.canon_id,
            'canon_version': key.canon_version,
            'geographic_revision_id': key.geographic_revision_id,
            'geography': row.geographic_document(),
            'geographic_data': {
                'license': 'ODbL-1.0',
                'license_url': 'https://opendatacommons.org/licenses/odbl/1-0/',
                'attribution': '© OpenStreetMap contributors',
                'source_offer': self._release.receipt.export_uri,
            },
        }
    def map_geography(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.api_geography(key) for key in self.keys())
    def profile_input(self, key: ClimbKey) -> bytes:
        return self.require(key).canonical_profile_bytes
    def registration_inputs(self, key: ClimbKey) -> tuple[str, int, bytes, str]:
        row = self.require(key)
        # This returns authoritative INPUTS only; actual v1/BLAKE3/Anchor construction
        # and archive reachability checks belong to the production integration.
        return (key.canon_id, key.canon_version, row.canonical_profile_bytes,
                self._release.receipt.export_uri)
    def validate_match_references(self, keys: Iterable[ClimbKey]) -> tuple[ClimbKey, ...]:
        result = tuple(keys)
        for key in result:
            self.require(key)
        return result