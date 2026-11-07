"""Add metadata only when the displayed registry fields match a retained export.

This is an additive receipt lookup, not a new geographic reader. lfsu0 owns the
pinned-release boundary. A newer or changed row must not claim an old receipt.
"""
from functools import lru_cache
from copy import deepcopy
import json
from pathlib import Path


def inherited_source_provenance(row, rows_by_id, seen=()):
    """Carry source authority only along an exact, same-family revision link."""
    identity = str(row['id'])
    if identity in seen:
        raise ValueError('Cyclic geographic source lineage')
    provenance = deepcopy(row.get('provenance') or {})
    predecessor_id = row.get('supersedes_climb_id')
    if predecessor_id:
        previous = rows_by_id.get(str(predecessor_id))
        if (not previous or str(previous['canon_id']) != str(row['canon_id'])
                or previous['version'] + 1 != row['version']):
            raise ValueError('Missing or inconsistent geographic source lineage')
        inherited = inherited_source_provenance(previous, rows_by_id, (*seen, identity))
        if not provenance.get('region') and inherited.get('region'):
            provenance['region'] = inherited['region']
        if not provenance.get('launch_ratification') and inherited.get('launch_ratification'):
            source = inherited['launch_ratification']
            # Source hashes still identify the inherited geography, but the
            # predecessor's placement decision does not approve this revision.
            source.pop('decision_id', None)
            rule_resource = provenance.get('finish_gate_rule', {}).get('decision_resource')
            decision = (rule_resource + '#registry_id=' + str(predecessor_id)
                        if rule_resource else provenance.get('ratified_boundary', {}).get('decision_id'))
            if decision:
                source['decision_id'] = decision
            provenance['launch_ratification'] = source
    return provenance


@lru_cache(maxsize=1)
def _index():
    path=Path(__file__).resolve().parents[1]/'data/open_data_index.json'
    return json.loads(path.read_text()) if path.exists() else {}


def geographic_data_for_row(row):
    if row.get('status') not in ('ratified', 'retired'):
        return None
    candidates=_index().get(str(row.get('id')),[])
    compared=('canon_id','version','display_name','route_name','centerline_polyline','canonical_profile','length_m','vert_m','avg_gradient_pct','dem_source','odbl_source','odbl_extract_at')
    for candidate in reversed(candidates):
        exported=candidate['exported']
        if all(str(row[k])==str(exported[k]) if k=='canon_id' else row[k]==exported[k] for k in compared if k in row):
            if row.get('canon_id') and row.get('version') and ('canonical_profile' in row or 'centerline_polyline' in row):
                return candidate['geographic_data']
    # A successor inherits source credits, never its predecessor's geometry
    # receipt, release hash or download link. A later export supplies its own.
    for candidate in reversed(_index().get(str(row.get('supersedes_climb_id')), [])):
        previous = candidate['exported']
        if (str(row.get('canon_id')) == str(previous['canon_id'])
                and row.get('version') == previous['version'] + 1
                and all(field in row and row[field] == previous[field]
                        for field in ('dem_source', 'odbl_source', 'odbl_extract_at'))):
            return {**{key: deepcopy(candidate['geographic_data'][key])
                       for key in ('attribution', 'license', 'sources', 'scope')},
                    'canon_id': str(row['canon_id']), 'canon_version': row['version']}
    return None
