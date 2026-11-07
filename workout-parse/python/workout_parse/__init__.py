"""
workout-parse: High-performance workout file parser.

This module provides a Python interface to the Rust workout parser,
along with adapter functions for seamless integration with the existing backend.

Terrain-Adaptive Climb Detection:
- classify_terrain: Classify terrain type from elevation profile
- detect_climbs_adaptive: Detect climbs with terrain-optimized thresholds
"""

from .workout_parse import (
    # Core functions
    parse_file,
    parse_bytes,
    parse_file_bytes,
    canonicalize_ride,
    hash_canonical_ride,
    compute_metrics,
    compute_training_metrics,
    training_timeline,
    effort_spans_ms,
    compute_metrics_in_spans,
    compute_segment_power_metrics_in_spans,
    calculate_tss_from_power,
    compute_segment_power_metrics,
    compute_threshold_power_anchors,
    # H3 tile functions (new)
    get_h3_cells,
    get_h3_strings,
    # Legacy tile function (deprecated)
    get_tiles,
    # Climb detection
    detect_climbs,
    detect_climbs_adaptive,
    detect_climbs_persistence,
    match_signatures_v2,
    match_climb_pair,
    find_best_vault_match,
    compute_persistence_pairs,
    # Terrain classification
    classify_terrain,
    # Polyline encoding/decoding
    py_encode_polyline,
    py_decode_polyline,
    py_encode_gps_track,
    py_decode_gps_track,
    # Classes
    ParsedActivity,
    ComputedMetrics,
    TrainingMetrics,
    H3Cell,
    ClimbPattern,
    ClimbV2,
    TerrainMetrics,
    TerrainClassification,
    # Legacy class (deprecated)
    Tile,
    # Exceptions
    ParseError,
    DecompressionLimitExceeded,
    DurationLimitExceeded,
    # Constants
    CURRENT_PARSER_VERSION,
    PARSER_VERSION_V1,
    PARSER_VERSION_V2,
    PARSER_VERSION_V3,
    PARSER_VERSION_V4,
    PARSER_VERSION_V5,
    METRICS_VERSION,
    TRAINING_ENGINE_VERSION,
    MISSING_U8,
    MISSING_U16,
    MISSING_I32,
    MISSING_I64,
    DEFAULT_H3_RESOLUTION,
)

__all__ = [
    # Core functions
    "parse_file",
    "parse_bytes",
    "parse_file_bytes",
    "canonicalize_ride",
    "hash_canonical_ride",
    "compute_metrics",
    "compute_training_metrics",
    "training_timeline",
    "calculate_tss_from_power",
    "compute_segment_power_metrics",
    "compute_threshold_power_anchors",
    # H3 tile functions
    "get_h3_cells",
    "get_h3_strings",
    "get_tiles",  # deprecated
    # Climb detection
    "detect_climbs",
    "detect_climbs_adaptive",
    "detect_climbs_persistence",
    "match_signatures_v2",
    "match_climb_pair",
    "find_best_vault_match",
    "compute_persistence_pairs",
    # Terrain classification
    "classify_terrain",
    # Polyline encoding/decoding
    "py_encode_polyline",
    "py_decode_polyline",
    "py_encode_gps_track",
    "py_decode_gps_track",
    # Classes
    "ParsedActivity",
    "ComputedMetrics",
    "TrainingMetrics",
    "H3Cell",
    "ClimbPattern",
    "ClimbV2",
    "TerrainMetrics",
    "TerrainClassification",
    "Tile",  # deprecated
    # Exceptions
    "ParseError",
    "DecompressionLimitExceeded",
    "DurationLimitExceeded",
    # Constants
    "CURRENT_PARSER_VERSION",
    "PARSER_VERSION_V1",
    "PARSER_VERSION_V2",
    "PARSER_VERSION_V3",
    "PARSER_VERSION_V4",
    "PARSER_VERSION_V5",
    "METRICS_VERSION",
    "TRAINING_ENGINE_VERSION",
    "MISSING_U8",
    "MISSING_U16",
    "MISSING_I32",
    "MISSING_I64",
    "DEFAULT_H3_RESOLUTION",
]

__version__ = "0.1.0"
