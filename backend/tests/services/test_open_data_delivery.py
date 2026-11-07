from pathlib import Path
import pytest
from scripts.build_open_data_pages import render_copy


def test_landing_rejects_missing_measured_values():
    with pytest.raises(ValueError, match='Unresolved'):
        render_copy({}, {})


def test_landing_uses_adopted_copy_and_functional_links():
    manifest=dict(release_id='a'*64,published_at_utc='2026-09-09T00:00:00Z',export_schema_version='br-geography-export-1',climb_identity_count=57,geographic_revision_count=57,region_count=1)
    delivery=dict(measured_compressed_bytes=123,measured_uncompressed_bytes=456,archive_sha256='b'*64)
    page=render_copy(manifest,delivery)
    assert '{' not in page
    assert 'https://www.openstreetmap.org/copyright' in page
    assert '/open-data/releases/'+'a'*64+'/release.zip' in page
    assert 'Required functional links:' not in page
