"""Closed public geographic provenance; private evidence never leaves this projection."""
import math
import re

# Explicit nested classification. None is a scalar, [None] a scalar array.
def scalars(names): return {name: None for name in names.split()}
GATE = scalars('a_lat a_lon b_lat b_lon')
ANCHOR = {**scalars('label osm_node_id lat lon resolved_offset_m'), 'exact_gate': GATE}
POLICY = scalars('corridor_half_width_m gate_start_half_extent_m gate_end_half_extent_m source')
POSITION = scalars('lat lon setback_from_junction_m')
CAPTURE_REVISION = {
 **scalars('model revision_id candidate_fingerprint record_continuity_policy authority decided_by decided_on decision_resource gate_start_half_extent_m gate_start_wkt policy_source predecessor_revision_id scope status successor_end_half_extent_m'),
 'evidence': 'private', 're_evidence': 'private',
 'registry': scalars('blake3 source'), 'prior_geometry_policy': POLICY,
 'revised_geometry_policy': POLICY, 'unchanged_identity_fields': [None],
}
FINISH_RULE = {
 **scalars('admission clearance_extends_default_setback decision_resource default_setback_m metres_moved model old_gate_end_wkt predecessor_fingerprint prior_ratified_end_anchor_is_historical record_continuity_policy setback_from_junction_m stop_line_clearance_m'),
 'clearance_interpretation': scalars('authority date decided_by rule'),
 'controls': [{**scalars('along_m kind lat lon node_id'), 'tags': scalars('button_operated crossing crossing:island crossing:markings direction highway stop tactile_paving traffic_signals traffic_signals:direction traffic_signals:sound traffic_signals:vibration')}],
 'founder_approval': {**scalars('authority initial_authority on position_tolerance_m'), 'by': 'private',
                      'approved_position': POSITION, 'quote': 'private',
                      'covering_note': {**scalars('authority note'), 'position': POSITION}},
 'junction': scalars('along_m lat lon node_id'),
 'mapped_stop_positions_m': 'osm_node_distances',
 # These duplicate locations derived from the founder's rides, not OSM.
 'observed_stop_along_m': 'private', 'observed_stop_clearance_m': 'private',
 'stop_evidence_amendment': 'private',
}
PROVENANCE = {
 **scalars('compile_method road_class highway_tag persistence_m vertical_semantics region'),
 'profile_spacing': scalars('target_m avg_m max_m'),
 'canonical_profile_hash': scalars('algorithm value'),
 'candidate_fingerprint': {**scalars('algorithm base_algorithm base_value geometry_samples coordinate_grid_degrees legacy_v2_value'), 'exact_gate_start': GATE, 'exact_gate_end': GATE},
 'corridor': scalars('half_width_m h3_cover publish_geometry compiler_preview_geometry'),
 'boundary_snap': scalars('start end snap_window_m'),
 'launch_ratification': {**scalars('decision_id'), **{k:'private' for k in ('candidate_manifest_sha256','canon_report_sha256','review_labels_sha256','authority')}},
 'way_chain': {**scalars('algorithm endpoint_tolerance_m max_abs_elevation_seam_m'), 'max_turn_deg': scalars('continuation same_name'), 'osm_way_refs': [None], 'road_names': [None], 'edges': [scalars('from_way to_way turn_angle_deg endpoint_gap_m elevation_seam_m')]},
 'ratified_boundary': {**scalars('algorithm decision_id replaces_candidate_fingerprint publication_status record_continuity_policy'), 'anchors': {'start': ANCHOR, 'end': ANCHOR}, **{key: [None] for key in ('ordered_osm_way_refs','reversed_way_refs','seam_gaps_m','seam_elevation_deltas_m')}, 'evidence': 'private', 'finish_decision': {**scalars('decision finish_at finish_m_past_current reason type'), 'quote': 'private'}},
 'capture_tolerance_revision': CAPTURE_REVISION,
 'superseded_capture_tolerance_revision': {**scalars('authority record_continuity_policy start_gate_unchanged status successor_end_half_extent_m'), 'revision': CAPTURE_REVISION},
 'finish_gate_rule': FINISH_RULE,
 'directional_extraction': {**scalars('algorithm orientation'), 'opposite_way_refs': [None]},
}

class ExportError(ValueError): pass

def project(value, spec, path='provenance'):
    if value is None: return None
    if spec == 'osm_node_distances':
        if not isinstance(value, dict) or any(
            not re.fullmatch(r'node/[0-9]+', k) or type(v) not in (int, float) or not math.isfinite(v)
            for k, v in value.items()
        ): raise ExportError(f'Unclassified OSM node distance: {path}')
        return dict(value)
    if isinstance(spec, dict):
        if not isinstance(value, dict): raise ExportError(f'Invalid object: {path}')
        if set(value)-set(spec): raise ExportError(f'Unclassified field at {path}: {sorted(set(value)-set(spec))}')
        return {k: project(v, spec[k], path+'.'+k) for k,v in value.items() if spec[k] != 'private'}
    if isinstance(spec, list):
        if not isinstance(value, list): raise ExportError(f'Invalid array: {path}')
        return [project(v,spec[0],path+'[]') for v in value]
    if not isinstance(value, (str,int,float,bool)): raise ExportError(f'Unclassified nested field: {path}')
    return value

def project_provenance(value): return project(value, PROVENANCE)

def schema_from_spec(spec):
    if spec == 'osm_node_distances': return {'type':['object','null'], 'additionalProperties':False, 'patternProperties':{'^node/[0-9]+$':{'type':'number'}}}
    if isinstance(spec, dict): return {'type':['object','null'], 'additionalProperties':False, 'properties':{k:schema_from_spec(v) for k,v in spec.items() if v!='private'}}
    if isinstance(spec, list): return {'type':'array','items':schema_from_spec(spec[0])}
    return {'type':['string','number','boolean','null']}
