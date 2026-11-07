"""Today's registry-table boundary only; full release isolation is lfsu0."""
from pathlib import Path
import pytest
from scripts.check_geographic_reads import check_source, CONSUMERS, BoundaryViolation

ROOT=Path(__file__).resolve().parents[2]


def test_current_production_geographic_consumers_are_classified():
    for relative in CONSUMERS:
        check_source(relative,(ROOT/'app'/relative).read_text())


@pytest.mark.parametrize('table',['atlas_candidates','private_candidates','candidate_climbs'])
def test_candidate_table_mutation_fails(table):
    source=(ROOT/'app/repositories/canon.py').read_text().replace('"canon_climbs"',repr(table))
    with pytest.raises(BoundaryViolation): check_source('repositories/canon.py',source)


def test_removing_ratified_filter_fails():
    source=(ROOT/'app/repositories/canon.py').read_text().replace('.eq("status", "ratified")','')
    with pytest.raises(BoundaryViolation): check_source('repositories/canon.py',source)


@pytest.mark.parametrize('mutation', ['geometry', 'unbounded', 'other_consumer'])
def test_registry_existence_exception_cannot_read_candidate_geometry(mutation):
    source=(ROOT/'app/repositories/canon.py').read_text()
    if mutation=='geometry':
        source=source.replace('.select("id")', '.select("id,centerline_geom")')
    elif mutation=='unbounded':
        start=source.index('async def _load_existing_registry_ids')
        source=source[:start]+source[start:].replace('.in_("id", list(batch))', '', 1)
    else:
        source=source.replace('_load_existing_registry_ids', '_load_candidate_geometry')
    with pytest.raises(BoundaryViolation): check_source('repositories/canon.py',source)
