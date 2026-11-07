import json
from types import SimpleNamespace

import pytest

from app.services.climb_lab import (
    CLIMB_LAB_SCAN_PRESETS,
    RIDEABLE_OSM_HIGHWAYS,
    ROAD_SCAN_OSM_HIGHWAYS,
    apply_climb_lab_review_action,
    build_canon_climb_publish_payload,
    build_climb_lab_bounded_scan_summary,
    build_climb_lab_compiler_candidate_summary,
    build_climb_lab_candidate_pipeline_summary,
    build_climb_lab_candidate_review_summary,
    build_climb_lab_calibration_inventory,
    build_climb_lab_elevation_signal_summary,
    build_climb_lab_review_candidate_map_detail,
    build_climb_lab_road_graph_edges,
    build_climb_lab_road_graph_summary,
    build_climb_lab_road_edge_signal_summary,
    build_climb_lab_review_state_summary,
    clear_climb_lab_scan_cache,
    clear_climb_lab_review_state,
    detect_elevation_signals,
    load_climb_lab_review_state,
    record_climb_lab_review_decision,
    score_road_edge_climb_signal,
    summarize_activity_directory,
    summarize_activity_elevation_signals,
    summarize_activity_file,
    string_road_edge_signals,
)


@pytest.fixture(autouse=True)
def _isolated_climb_lab_review_state(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "CLIMB_LAB_REVIEW_STATE_PATH",
        str(tmp_path / "climb_lab_review_state.json"),
    )
    clear_climb_lab_review_state(remove_file=True)
    yield
    clear_climb_lab_review_state(remove_file=True)


def _compiler_candidate_fixture() -> dict:
    return {
        "candidate_fingerprint": "a" * 64,
        "legacy_candidate_fingerprints": ["f" * 64],
        "display_name": "Levering Street: start gate to finish gate",
        "route_name": "Levering Street",
        "direction": "ascending",
        "centerline_polyline": "encoded-polyline-secret",
        "centerline_wkt": "LINESTRING(-75.22 40.02,-75.21 40.03)",
        "corridor_wkt": "MULTIPOLYGON(((-75.22 40.02,-75.21 40.02,-75.21 40.03,-75.22 40.02)))",
        "corridor_half_width_m": 25.0,
        "gate_start_wkt": "LINESTRING(-75.221 40.020,-75.219 40.020)",
        "gate_end_wkt": "LINESTRING(-75.211 40.030,-75.209 40.030)",
        "canonical_profile": [
            {"dist_m": 0.0, "elev_m": 12.0},
            {"dist_m": 100.0, "elev_m": 20.0},
        ],
        "length_m": 100.0,
        "vert_m": 8.0,
        "avg_gradient_pct": 8.0,
        "max_gradient_pct": 10.5,
        "worthiness_score": 88.0,
        "confidence": "high",
        "dem_source": "USGS 3DEP 10m local profile export",
        "compiler_version": "canon-compile-v0.2.0",
        "osm_way_refs": [123456789],
        "odbl_source": "OpenStreetMap contributors",
        "odbl_extract_at": "2026-07-05T00:00:00Z",
        "provenance": {
            "compiler": "fixture",
            "canonical_profile_hash": {
                "algorithm": "blake3_canonical_profile_v1",
                "value": "1" * 64,
            },
        },
        "low_confidence_flags": [],
        "corridor_cells": [
            {
                "h3_resolution": 10,
                "tile_id": "8a2a1342b5a7fff",
                "coverage_role": "corridor",
            }
        ],
    }


def _applied_compiler_report(*candidates: dict) -> dict:
    return {
        "ratified_boundaries": {
            "mode": "applied",
            "model": "canon_ratified_boundaries_v1",
        },
        "candidates": list(candidates),
    }


def test_summarize_activity_directory_uses_metadata_only(tmp_path) -> None:
    activities = tmp_path / "Activities"
    activities.mkdir()
    (activities / "2026-06-09-17-52-38.fit").write_bytes(b"fit-data")
    (activities / "2025-01-01-10-00-00.gpx").write_text("<gpx />")
    (activities / "notes.txt").write_text("ignored")

    summary = summarize_activity_directory(
        source_id="test",
        label="Test activities",
        path=activities,
    )

    assert summary["available"] is True
    assert summary["privacy_mode"] == "metadata_only"
    assert summary["file_count"] == 2
    assert summary["extensions"] == {"fit": 1, "gpx": 1}
    assert summary["years"] == {"2025": 1, "2026": 1}
    assert summary["date_range"] == {"start": "2025-01-01", "end": "2026-06-09"}
    assert summary["first_file"] == "2025-01-01-10-00-00.gpx"
    assert summary["last_file"] == "2026-06-09-17-52-38.fit"
    assert summary["summary"] == "Extra local corpus source. Useful for expanding calibration coverage."
    assert [row["name"] for row in summary["recent_files"]] == [
        "2025-01-01-10-00-00.gpx",
        "2026-06-09-17-52-38.fit",
    ]


def test_summarize_activity_directory_handles_missing_source(tmp_path) -> None:
    summary = summarize_activity_directory(
        source_id="missing",
        label="Missing activities",
        path=tmp_path / "missing",
    )

    assert summary["available"] is False
    assert summary["file_count"] == 0
    assert summary["total_bytes"] == 0
    assert summary["summary"] == "Available, but no activity files were found here."
    assert summary["recent_files"] == []


def test_summarize_activity_file_returns_ride_summary_without_coordinates(tmp_path) -> None:
    activity_path = tmp_path / "2026-06-09-17-52-38.fit"
    activity_path.write_bytes(b"fit-data")

    def fake_parser(path):
        assert path == activity_path
        return SimpleNamespace(
            sport='string("cycling")',
            time_ms=[0, 60_000, 120_000, 180_000],
            total_elapsed_s=1800,
            lat_e7=[400000000, 400000100, 400000200],
            lon_e7=[-1050000000, -1050000100, -1050000200],
            elevation_m=[100, 110, 105, 130],
            pwr_w=[120, 160],
            hr_bpm=[138, 141],
        )

    summary = summarize_activity_file(activity_path, parser=fake_parser)

    assert summary["status"] == "parsed"
    assert summary["activity_date"] == "2026-06-09"
    assert summary["privacy_mode"] == "no_coordinates"
    assert summary["sport"] == "cycling"
    assert summary["sample_count"] == 4
    assert summary["duration_label"] == "30m"
    assert summary["has_gps"] is True
    assert summary["has_elevation"] is True
    assert summary["has_power"] is True
    assert summary["has_hr"] is True
    assert summary["elevation_min_m"] == 100
    assert summary["elevation_max_m"] == 130
    assert summary["naive_gain_m"] == 35
    assert "lat_e7" not in summary
    assert "lon_e7" not in summary
    assert "samples" not in summary


def test_build_calibration_inventory_bounds_and_isolates_parse_errors(
    monkeypatch,
    tmp_path,
) -> None:
    activities = tmp_path / "Activities"
    activities.mkdir()
    good = activities / "2026-06-10-10-00-00.fit"
    broken = activities / "2026-06-09-10-00-00.fit"
    good.write_bytes(b"fit-data")
    broken.write_bytes(b"bad-fit-data")
    monkeypatch.setenv("CLIMB_LAB_GARMIN_ACTIVITIES_DIR", str(activities))

    def fake_parser(path):
        if path == broken:
            raise ValueError("corrupt fixture")
        return SimpleNamespace(
            sport="cycling",
            time_ms=[0, 60_000, 120_000],
            total_elapsed_s=900,
            lat_e7=[400000000],
            lon_e7=[-1050000000],
            elevation_m=[1200, 1400, 1555],
            pwr_w=[],
            hr_bpm=None,
        )

    inventory = build_climb_lab_calibration_inventory(
        source_id="garmin_device",
        limit=10,
        parser=fake_parser,
    )

    assert inventory["scope"] == "local_dev_only"
    assert inventory["privacy_mode"] == "no_coordinates"
    assert inventory["available"] is True
    assert inventory["totals"]["files_considered"] == 2
    assert inventory["totals"]["rides_returned"] == 2
    assert inventory["totals"]["parsed"] == 1
    assert inventory["totals"]["errors"] == 1
    assert inventory["totals"]["with_gps"] == 1
    assert inventory["totals"]["with_elevation"] == 1
    assert inventory["totals"]["gain_candidates"] == 1
    assert inventory["totals"]["naive_gain_m"] == 355
    assert inventory["rides"][0]["name"] == good.name
    assert inventory["rides"][0]["gain_band"] == "calibration"
    assert inventory["rides"][1]["status"] == "error"
    assert all("lat_e7" not in ride for ride in inventory["rides"])
    assert all("lon_e7" not in ride for ride in inventory["rides"])


def test_calibration_inventory_reuses_and_invalidates_cached_summaries(
    monkeypatch,
    tmp_path,
) -> None:
    activities = tmp_path / "Activities"
    activities.mkdir()
    activity_path = activities / "2026-06-10-10-00-00.fit"
    activity_path.write_bytes(b"fit-data")
    monkeypatch.setenv("CLIMB_LAB_GARMIN_ACTIVITIES_DIR", str(activities))
    clear_climb_lab_scan_cache()
    calls = []

    def fake_parser(path):
        calls.append(path)
        return SimpleNamespace(
            sport="cycling",
            time_ms=[0, 60_000, 120_000],
            total_elapsed_s=900,
            lat_e7=[400000000],
            lon_e7=[-1050000000],
            elevation_m=[1200, 1400, 1555],
            pwr_w=[],
            hr_bpm=None,
        )

    first = build_climb_lab_calibration_inventory(
        source_id="garmin_device",
        limit=1,
        parser=fake_parser,
    )
    second = build_climb_lab_calibration_inventory(
        source_id="garmin_device",
        limit=1,
        parser=fake_parser,
    )
    activity_path.write_bytes(b"changed-fit-data")
    third = build_climb_lab_calibration_inventory(
        source_id="garmin_device",
        limit=1,
        parser=fake_parser,
    )

    assert len(calls) == 2
    assert first["cache"]["misses"] == 1
    assert first["cache"]["hits"] == 0
    assert first["rides"][0]["cache_status"] == "miss"
    assert second["cache"]["hits"] == 1
    assert second["cache"]["misses"] == 0
    assert second["rides"][0]["cache_status"] == "hit"
    assert third["cache"]["misses"] == 1
    assert third["rides"][0]["cache_status"] == "miss"


def test_detect_elevation_signals_returns_derived_intervals_only() -> None:
    activity = SimpleNamespace(
        sport="cycling",
        time_ms=[0, 60_000, 120_000, 180_000, 240_000, 300_000, 360_000],
        dist_m=[0, 300, 700, 1200, 1650, 2100, 2600],
        elevation_m=[100, 108, 128, 160, 154, 174, 190],
        lat_e7=[400000000] * 7,
        lon_e7=[-1050000000] * 7,
    )

    signals = detect_elevation_signals(
        activity,
        ride_name="fixture.fit",
        ride_date="2026-06-10",
        min_gain_m=40,
        min_distance_m=300,
        min_avg_grade_pct=2,
        max_signals=3,
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal["ride_file"] == "fixture.fit"
    assert signal["activity_date"] == "2026-06-10"
    assert signal["gain_m"] >= 50
    assert signal["distance_m"] >= 1500
    assert signal["avg_grade_pct"] >= 2
    assert signal["start_pct"] >= 0
    assert signal["end_pct"] <= 100
    assert signal["confidence"] in {"exploratory", "medium", "high"}
    assert "lat_e7" not in signal
    assert "lon_e7" not in signal
    assert "samples" not in signal


def test_build_elevation_signal_summary_bounds_and_isolates_errors(
    monkeypatch,
    tmp_path,
) -> None:
    activities = tmp_path / "Activities"
    activities.mkdir()
    good = activities / "2026-06-10-10-00-00.fit"
    broken = activities / "2026-06-09-10-00-00.fit"
    good.write_bytes(b"fit-data")
    broken.write_bytes(b"bad-fit-data")
    monkeypatch.setenv("CLIMB_LAB_GARMIN_ACTIVITIES_DIR", str(activities))

    def fake_parser(path):
        if path == broken:
            raise ValueError("corrupt fixture")
        return SimpleNamespace(
            sport='string("cycling")',
            time_ms=[0, 60_000, 120_000, 180_000, 240_000],
            dist_m=[0, 400, 900, 1500, 2200],
            elevation_m=[100, 114, 140, 174, 205],
            lat_e7=[400000000] * 5,
            lon_e7=[-1050000000] * 5,
        )

    summary = build_climb_lab_elevation_signal_summary(
        source_id="garmin_device",
        file_limit=10,
        signal_limit=5,
        min_gain_m=40,
        parser=fake_parser,
    )

    assert summary["scope"] == "local_dev_only"
    assert summary["privacy_mode"] == "no_coordinates_no_raw_trace"
    assert summary["totals"]["files_considered"] == 2
    assert summary["totals"]["files_scanned"] == 2
    assert summary["totals"]["parsed"] == 1
    assert summary["totals"]["errors"] == 1
    assert summary["totals"]["rides_with_signals"] == 1
    assert summary["totals"]["signals_returned"] == 1
    assert summary["signals"][0]["ride_file"] == good.name
    assert summary["rides"][0]["sport"] == "cycling"
    assert summary["rides"][1]["status"] == "error"
    assert all("lat_e7" not in signal for signal in summary["signals"])
    assert all("lon_e7" not in signal for signal in summary["signals"])


def test_elevation_signal_summary_cache_includes_scan_parameters(
    monkeypatch,
    tmp_path,
) -> None:
    activities = tmp_path / "Activities"
    activities.mkdir()
    activity_path = activities / "2026-06-10-10-00-00.fit"
    activity_path.write_bytes(b"fit-data")
    monkeypatch.setenv("CLIMB_LAB_GARMIN_ACTIVITIES_DIR", str(activities))
    clear_climb_lab_scan_cache()
    calls = []

    def fake_parser(path):
        calls.append(path)
        return SimpleNamespace(
            sport="cycling",
            time_ms=[0, 60_000, 120_000, 180_000, 240_000],
            dist_m=[0, 400, 900, 1500, 2200],
            elevation_m=[100, 114, 140, 174, 205],
            lat_e7=[400000000] * 5,
            lon_e7=[-1050000000] * 5,
        )

    first = build_climb_lab_elevation_signal_summary(
        source_id="garmin_device",
        file_limit=1,
        signal_limit=5,
        min_gain_m=40,
        parser=fake_parser,
    )
    second = build_climb_lab_elevation_signal_summary(
        source_id="garmin_device",
        file_limit=1,
        signal_limit=5,
        min_gain_m=40,
        parser=fake_parser,
    )
    third = build_climb_lab_elevation_signal_summary(
        source_id="garmin_device",
        file_limit=1,
        signal_limit=5,
        min_gain_m=80,
        parser=fake_parser,
    )

    assert len(calls) == 2
    assert first["cache"]["misses"] == 1
    assert first["rides"][0]["cache_status"] == "miss"
    assert second["cache"]["hits"] == 1
    assert second["rides"][0]["cache_status"] == "hit"
    assert third["cache"]["misses"] == 1
    assert third["rides"][0]["cache_status"] == "miss"


def test_summarize_activity_elevation_signals_handles_missing_series(tmp_path) -> None:
    activity_path = tmp_path / "2026-06-11-10-00-00.fit"
    activity_path.write_bytes(b"fit-data")

    summary = summarize_activity_elevation_signals(
        activity_path,
        parser=lambda _path: SimpleNamespace(
            sport="cycling",
            time_ms=[0, 60_000],
            dist_m=None,
            elevation_m=[100, 140],
        ),
    )

    assert summary["status"] == "parsed"
    assert summary["privacy_mode"] == "no_coordinates_no_raw_trace"
    assert summary["signal_count"] == 0
    assert summary["signals"] == []


def test_score_road_edge_climb_signal_reports_edge_span_without_raw_profile() -> None:
    edge = {
        "edge_id": "edge-1",
        "road_name": "Test Road",
        "from_intersection": "Bottom",
        "to_intersection": "Top",
        "samples": [
            {"distance_m": 0, "elevation_m": 100},
            {"distance_m": 200, "elevation_m": 118},
            {"distance_m": 500, "elevation_m": 145},
            {"distance_m": 800, "elevation_m": 160},
        ],
    }

    signal = score_road_edge_climb_signal(edge)

    assert signal["edge_id"] == "edge-1"
    assert signal["direction"] == "forward"
    assert signal["from_intersection"] == "Bottom"
    assert signal["to_intersection"] == "Top"
    assert signal["climb_start_pct"] == 0
    assert signal["climb_end_pct"] == 100
    assert signal["climb_pct"] == 100
    assert signal["gain_m"] == 60
    assert signal["avg_grade_pct"] == 7.5
    assert signal["signal_band"] == "climb_bearing"
    assert signal["is_climb_bearing"] is True
    assert "samples" not in signal
    assert "elevation_m" not in signal


def test_score_road_edge_climb_signal_reverse_direction_rejects_descent() -> None:
    edge = {
        "edge_id": "edge-1",
        "road_name": "Test Road",
        "from_intersection": "Bottom",
        "to_intersection": "Top",
        "samples": [
            {"distance_m": 0, "elevation_m": 100},
            {"distance_m": 400, "elevation_m": 135},
            {"distance_m": 800, "elevation_m": 160},
        ],
    }

    signal = score_road_edge_climb_signal(edge, direction="reverse")

    assert signal["direction"] == "reverse"
    assert signal["from_intersection"] == "Top"
    assert signal["to_intersection"] == "Bottom"
    assert signal["signal_band"] == "low"
    assert signal["is_climb_bearing"] is False
    assert signal["gain_m"] == 0


def test_string_road_edge_signals_joins_adjacent_same_road_edges() -> None:
    first = score_road_edge_climb_signal(
        {
            "edge_id": "edge-a",
            "road_name": "Linden Drive",
            "from_intersection": "A",
            "to_intersection": "B",
            "samples": [
                {"distance_m": 0, "elevation_m": 100},
                {"distance_m": 500, "elevation_m": 145},
            ],
        }
    )
    second = score_road_edge_climb_signal(
        {
            "edge_id": "edge-b",
            "road_name": "Linden Drive",
            "from_intersection": "B",
            "to_intersection": "C",
            "samples": [
                {"distance_m": 0, "elevation_m": 145},
                {"distance_m": 400, "elevation_m": 181},
            ],
        }
    )

    strings = string_road_edge_signals([first, second])

    assert len(strings) == 1
    assert strings[0]["edge_ids"] == ["edge-a", "edge-b"]
    assert strings[0]["from_intersection"] == "A"
    assert strings[0]["to_intersection"] == "C"
    assert strings[0]["gain_m"] == 81
    assert "same_road_name_continuity" in strings[0]["reasons"]


def test_road_graph_edges_split_named_ways_at_intersections() -> None:
    graph = {
        "nodes": [
            {"id": "a", "name": "Bottom", "lat": 40.0, "lon": -105.0, "elevation_m": 100},
            {"id": "b", "lat": 40.0, "lon": -104.999, "elevation_m": 120},
            {"id": "c", "name": "Middle", "lat": 40.0, "lon": -104.998, "elevation_m": 150},
            {"id": "d", "name": "Top", "lat": 40.0, "lon": -104.997, "elevation_m": 180},
            {"id": "x", "lat": 40.001, "lon": -104.998, "elevation_m": 152},
        ],
        "ways": [
            {
                "id": "main",
                "tags": {"highway": "residential", "name": "Test Road"},
                "nodes": ["a", "b", "c", "d"],
            },
            {
                "id": "cross",
                "tags": {"highway": "residential", "name": "Cross Street"},
                "nodes": ["x", "c"],
            },
        ],
    }

    edges = build_climb_lab_road_graph_edges(graph)
    test_edges = [edge for edge in edges if edge["road_name"] == "Test Road"]

    assert len(test_edges) == 2
    assert test_edges[0]["from_intersection"] == "Bottom"
    assert test_edges[0]["to_intersection"] == "Middle"
    assert test_edges[0]["node_count"] == 3
    assert test_edges[0]["samples"][0]["distance_m"] == 0
    assert test_edges[0]["samples"][-1]["distance_m"] > 150
    assert test_edges[1]["from_intersection"] == "Middle"
    assert test_edges[1]["to_intersection"] == "Top"


def test_road_graph_edges_ignore_nameless_and_nonrideable_ways() -> None:
    graph = {
        "nodes": [
            {"id": "a", "lat": 40.0, "lon": -105.0, "elevation_m": 100},
            {"id": "b", "lat": 40.0, "lon": -104.999, "elevation_m": 110},
            {"id": "c", "lat": 40.0, "lon": -104.998, "elevation_m": 120},
        ],
        "ways": [
            {"id": "nameless", "tags": {"highway": "residential"}, "nodes": ["a", "b"]},
            {
                "id": "steps",
                "tags": {"highway": "steps", "name": "Trail Steps"},
                "nodes": ["b", "c"],
            },
        ],
    }

    assert build_climb_lab_road_graph_edges(graph) == []


def test_road_graph_summary_redacts_coordinates_and_reports_readiness() -> None:
    summary = build_climb_lab_road_graph_summary()
    encoded = json.dumps(summary)

    assert summary["scope"] == "local_dev_only"
    assert summary["source"] == "fixture_osm_like_road_graph"
    assert summary["privacy_mode"] == "no_coordinates_no_raw_trace"
    assert summary["totals"]["normalized_edges"] >= 4
    assert summary["totals"]["elevation_ready_edges"] == summary["totals"]["normalized_edges"]
    assert summary["edges"][0]["sample_distances_m"][0] == 0
    assert "lat" not in encoded
    assert "lon" not in encoded
    assert "latitude" not in encoded
    assert "longitude" not in encoded
    assert "samples" not in encoded


def test_road_edge_signal_summary_stays_fixture_and_privacy_bounded() -> None:
    summary = build_climb_lab_road_edge_signal_summary()
    encoded = json.dumps(summary)

    assert summary["scope"] == "local_dev_only"
    assert summary["source"] == "fixture_osm_like_road_graph"
    assert summary["privacy_mode"] == "no_coordinates_no_raw_trace"
    assert summary["totals"]["fixture_edges"] >= 4
    assert summary["totals"]["directed_edges_scored"] == summary["totals"]["fixture_edges"] * 2
    assert summary["totals"]["climb_bearing_edges"] >= 2
    assert summary["totals"]["candidate_strings"] == 1
    assert summary["candidate_strings"][0]["road_names"] == ["Linden Drive"]
    assert "samples" not in encoded
    assert "latitude" not in encoded
    assert "longitude" not in encoded
    assert "lat_e7" not in encoded
    assert "lon_e7" not in encoded


def test_candidate_pipeline_materializes_lab_results() -> None:
    summary = build_climb_lab_candidate_pipeline_summary()

    assert summary["scope"] == "local_dev_only"
    assert summary["pipeline_status"] == "produced_fixture_candidates"
    assert summary["model"] == "road_graph_to_candidate_climbs_pipeline_v0"
    assert summary["totals"]["road_edges"] >= 4
    assert summary["totals"]["candidate_strings"] == 1
    assert summary["totals"]["candidate_climbs"] >= 2
    assert summary["totals"]["promoted_climbs"] == 0
    assert summary["top_candidate_id"] == summary["candidates"][0]["candidate_id"]
    assert summary["candidates"][0]["display_name"] == (
        "Linden Drive: Creek Road to Ridgecrest Road"
    )
    assert summary["candidates"][0]["candidate_type"] in {
        "single_road_edge",
        "strung_road_edges",
    }
    assert summary["candidates"][0]["result"] == "candidate_climb_ready_for_review"
    assert "open_candidate" in summary["candidates"][0]["next_review_actions"]


def test_candidate_pipeline_summary_redacts_raw_inputs() -> None:
    summary = build_climb_lab_candidate_pipeline_summary()
    encoded = json.dumps(summary)

    assert summary["privacy_mode"] == "no_coordinates_no_raw_trace"
    assert "latitude" not in encoded
    assert "longitude" not in encoded
    assert "lat_e7" not in encoded
    assert "lon_e7" not in encoded
    assert "samples" not in encoded
    assert "elevation_m" not in encoded


def test_bounded_scan_summary_materializes_candidates_from_overpass_payload() -> None:
    payload = {
        "elements": [
            {"type": "node", "id": 1, "lat": 40.0, "lon": -105.0},
            {"type": "node", "id": 2, "lat": 40.0, "lon": -104.999},
            {"type": "node", "id": 3, "lat": 40.0, "lon": -104.998},
            {"type": "node", "id": 4, "lat": 40.001, "lon": -104.999},
            {
                "type": "way",
                "id": 10,
                "tags": {"highway": "residential", "name": "Test Climb Road"},
                "nodes": [1, 2, 3],
            },
            {
                "type": "way",
                "id": 11,
                "tags": {"highway": "residential", "name": "Cross Street"},
                "nodes": [4, 2],
            },
        ],
    }

    def fake_elevation_lookup(nodes):
        elevations = {"1": 100, "2": 150, "3": 205, "4": 152}
        return {str(node["id"]): elevations[str(node["id"])] for node in nodes}

    summary = build_climb_lab_bounded_scan_summary(
        preset_id="boulder_foothills_north",
        max_ways=10,
        max_candidates=5,
        overpass_payload=payload,
        elevation_lookup=fake_elevation_lookup,
    )

    assert summary["pipeline_status"] == "produced_bounded_scan_candidates"
    assert summary["source"] == "overpass_osm_live"
    assert summary["cache_status"] == "fixture"
    assert summary["totals"]["source_ways"] == 2
    assert summary["totals"]["selected_ways"] == 2
    assert summary["totals"]["selected_elevation_nodes"] == 4
    assert summary["totals"]["elevation_attached_nodes"] == 4
    assert summary["totals"]["elevation_status"] == "fixture"
    assert summary["totals"]["selection_strategy"] == (
        "ranked_named_roads_simplified_to_elevation_budget"
    )
    assert summary["totals"]["candidate_climbs"] >= 1
    assert summary["candidates"][0]["display_name"] == (
        "Test Climb Road: west lower junction to east upper end"
    )
    assert summary["candidates"][0]["candidate_type"] in {
        "single_road_edge",
        "strung_road_edges",
    }


def test_bounded_scan_summary_redacts_raw_scan_inputs() -> None:
    payload = {
        "elements": [
            {"type": "node", "id": 1, "lat": 40.0, "lon": -105.0},
            {"type": "node", "id": 2, "lat": 40.0, "lon": -104.999},
            {
                "type": "way",
                "id": 10,
                "tags": {"highway": "residential", "name": "Short Climb Road"},
                "nodes": [1, 2],
            },
        ],
    }

    summary = build_climb_lab_bounded_scan_summary(
        overpass_payload=payload,
        elevation_lookup=lambda nodes: {str(node["id"]): 100 + idx * 50 for idx, node in enumerate(nodes)},
    )
    encoded = json.dumps(summary)

    assert summary["privacy_mode"] == "no_coordinates_no_raw_trace"
    assert "latitude" not in encoded
    assert "longitude" not in encoded
    assert "lat_e7" not in encoded
    assert "lon_e7" not in encoded
    assert "samples" not in encoded
    assert "elevation_m" not in encoded
    assert "node:1" not in encoded
    assert "node:2" not in encoded


def test_philadelphia_presets_and_scan_highways_match_canon_launch_scope() -> None:
    assert "philadelphia_manayunk_wall" in CLIMB_LAB_SCAN_PRESETS
    assert "philadelphia_wissahickon" in CLIMB_LAB_SCAN_PRESETS
    assert "cycleway" in ROAD_SCAN_OSM_HIGHWAYS
    assert "service" in ROAD_SCAN_OSM_HIGHWAYS
    assert "track" not in ROAD_SCAN_OSM_HIGHWAYS
    assert "path" not in ROAD_SCAN_OSM_HIGHWAYS
    assert "road" not in ROAD_SCAN_OSM_HIGHWAYS
    assert ROAD_SCAN_OSM_HIGHWAYS == RIDEABLE_OSM_HIGHWAYS


def test_candidate_review_summary_targets_canon_climbs_without_raw_geometry() -> None:
    pipeline = build_climb_lab_candidate_pipeline_summary()
    review = build_climb_lab_candidate_review_summary(pipeline)
    encoded = json.dumps(review)

    assert review["model"] == "canon_ratification_review_surface_v0"
    assert review["schema_status"] == "canon_schema_v1_available"
    assert review["publish_contract"] == {
        "target_table": "canon_climbs",
        "initial_status": "ratified",
        "initial_version": 1,
        "schema_gate": "boulderroller-v2-4crx.8",
    }
    assert review["totals"]["candidate_climbs"] >= 1
    candidate = review["candidates"][0]
    assert candidate["review_state"] == "needs_review"
    assert {action["id"] for action in candidate["review_actions"]} == {
        "trim_start",
        "trim_finish",
        "merge_through_intersection",
        "suppress",
        "approve",
    }
    assert candidate["canon_publish_preview"]["target_table"] == "canon_climbs"
    assert candidate["canon_publish_preview"]["version"] == 1
    assert candidate["canon_publish_preview"]["publish_status"] == (
        "blocked_missing_canon_publish_payload"
    )
    assert "centerline_wkt" in candidate["canon_publish_preview"]["missing_fields"]
    assert "latitude" not in encoded
    assert "longitude" not in encoded
    assert "lat_e7" not in encoded
    assert "lon_e7" not in encoded
    assert "samples" not in encoded
    assert "elevation_m" not in encoded


def test_candidate_review_approve_action_records_schema_gated_publish_state() -> None:
    result = apply_climb_lab_review_action(
        candidate_id="climblab-test-candidate",
        action_id="approve",
        note="local rider recognizes this climb",
    )

    assert result["status"] == "recorded"
    assert result["review_state"] == "approved_for_canon_climbs_v1"
    assert result["publish_status"] == "blocked_missing_canon_publish_payload"
    assert result["target_table"] == "canon_climbs"
    assert result["target_version"] == 1
    assert "centerline_wkt" in result["missing_fields"]

    review = build_climb_lab_candidate_review_summary(
        {
            "source": "fixture",
            "area_label": "fixture",
            "candidates": [
                {
                    "candidate_id": "climblab-test-candidate",
                    "display_name": "Test Road: start to finish",
                    "road_names": ["Test Road"],
                    "from_intersection": "start",
                    "to_intersection": "finish",
                    "distance_m": 1200,
                    "gain_m": 88,
                    "avg_grade_pct": 7.3,
                    "confidence": "high",
                    "review_priority": "high",
                }
            ],
        }
    )
    assert review["totals"]["approved_for_canon_climbs_v1"] == 1
    assert review["candidates"][0]["review_state"] == "approved_for_canon_climbs_v1"


def test_compiler_candidates_are_reviewable_without_leaking_raw_geometry() -> None:
    summary = build_climb_lab_compiler_candidate_summary(
        _applied_compiler_report(_compiler_candidate_fixture()),
        source_label="fixture-compiler-report.json",
    )
    review = build_climb_lab_candidate_review_summary(summary)
    encoded = json.dumps(review)

    assert review["source"] == "canon_compile_report"
    assert review["totals"]["publish_ready_candidates"] == 1
    candidate = review["candidates"][0]
    assert candidate["candidate_id"] == f"canon-{'a' * 16}"
    assert candidate["candidate_type"] == "compiled_canon_candidate"
    assert candidate["road_names"] == ["Levering Street"]
    assert candidate["canon_publish_preview"]["publish_status"] == (
        "ready_for_canon_climbs_v1_insert"
    )
    assert candidate["canon_publish_preview"]["corridor_cell_count"] == 1
    assert "encoded-polyline-secret" not in encoded
    assert "LINESTRING" not in encoded
    assert "MULTIPOLYGON" not in encoded
    assert "\"canonical_profile\":" not in encoded
    assert "dist_m" not in encoded
    assert "elev_m" not in encoded


def test_diagnostic_compiler_report_is_reviewable_but_not_publishable() -> None:
    report = _applied_compiler_report(_compiler_candidate_fixture())
    report["ratified_boundaries"]["mode"] = "diagnostic_skip"

    summary = build_climb_lab_compiler_candidate_summary(report)
    candidate = summary["candidates"][0]
    review_candidate = build_climb_lab_candidate_review_summary(summary)["candidates"][0]

    assert summary["pipeline_status"] == "diagnostic_report_loaded_non_publishable"
    assert summary["totals"]["publish_ready_candidates"] == 0
    assert review_candidate["canon_publish_preview"]["publish_status"] == (
        "blocked_missing_canon_publish_payload"
    )
    with pytest.raises(ValueError, match="compiler_run_mode=applied"):
        build_canon_climb_publish_payload(candidate)


def test_compiler_candidate_map_detail_exposes_single_candidate_line_and_profile() -> None:
    candidate = build_climb_lab_compiler_candidate_summary(
        _applied_compiler_report(_compiler_candidate_fixture()),
        source_label="fixture-compiler-report.json",
    )["candidates"][0]

    detail = build_climb_lab_review_candidate_map_detail(candidate)
    encoded = json.dumps(detail)

    assert detail["privacy_mode"] == "single_candidate_public_osm_geometry_no_raw_trace"
    assert detail["candidate"]["candidate_id"] == f"canon-{'a' * 16}"
    assert detail["geometry"] == {
        "status": "ready",
        "encoding": "google_polyline",
        "centerline_polyline": "encoded-polyline-secret",
    }
    assert detail["profile"]["status"] == "ready"
    assert detail["profile"]["points"] == [
        {"dist_m": 0.0, "elev_m": 12.0},
        {"dist_m": 100.0, "elev_m": 20.0},
    ]
    assert "LINESTRING" not in encoded
    assert "MULTIPOLYGON" not in encoded
    assert "gate_start_wkt" not in encoded
    assert "\"lat\"" not in encoded
    assert "\"lon\"" not in encoded


def test_review_decision_persists_without_geometry() -> None:
    candidate = build_climb_lab_compiler_candidate_summary(
        _applied_compiler_report(_compiler_candidate_fixture()),
        source_label="fixture-compiler-report.json",
    )["candidates"][0]

    result = record_climb_lab_review_decision(
        candidate_id=candidate["candidate_id"],
        decision="needs_work",
        note="start gate should move uphill",
        candidate=candidate,
        reviewed_by="test-reviewer",
    )
    state = load_climb_lab_review_state()
    state_summary = build_climb_lab_review_state_summary()
    review = build_climb_lab_candidate_review_summary(
        {
            "source": "fixture",
            "area_label": "fixture",
            "candidates": [candidate],
        }
    )
    encoded = json.dumps(state_summary)

    assert result["status"] == "recorded"
    assert result["review_state"] == "needs_work"
    assert state["candidates"][candidate["candidate_id"]]["note"] == (
        "start gate should move uphill"
    )
    assert state_summary["totals"]["needs_work"] == 1
    assert review["totals"]["needs_work"] == 1
    assert review["candidates"][0]["review_decision"] == "needs_work"
    assert "encoded-polyline-secret" not in encoded
    assert "LINESTRING" not in encoded
    assert "MULTIPOLYGON" not in encoded
    assert "\"canonical_profile\"" not in encoded
    assert "\"lat\"" not in encoded
    assert "\"lon\"" not in encoded


def test_review_summary_carries_decision_when_compiler_boundary_changes() -> None:
    old_candidate = build_climb_lab_compiler_candidate_summary(
        _applied_compiler_report(_compiler_candidate_fixture()),
        source_label="fixture-compiler-report.json",
    )["candidates"][0]
    record_climb_lab_review_decision(
        candidate_id=old_candidate["candidate_id"],
        decision="approve",
        note="local rider accepts the line",
        candidate=old_candidate,
        reviewed_by="test-reviewer",
    )
    changed_payload = {
        **_compiler_candidate_fixture(),
        "candidate_fingerprint": "b" * 64,
        "legacy_candidate_fingerprints": ["a" * 64],
        "length_m": 130.0,
        "canonical_profile": [
            {"dist_m": 0.0, "elev_m": 12.0},
            {"dist_m": 70.0, "elev_m": 18.0},
            {"dist_m": 130.0, "elev_m": 24.0},
        ],
    }
    changed_candidate = build_climb_lab_compiler_candidate_summary(
        _applied_compiler_report(changed_payload),
        source_label="fixture-compiler-report-v2.json",
    )["candidates"][0]

    review = build_climb_lab_candidate_review_summary(
        {
            "source": "fixture",
            "area_label": "fixture",
            "candidates": [changed_candidate],
        }
    )
    candidate = review["candidates"][0]

    assert candidate["candidate_id"] == f"canon-{'b' * 16}"
    assert candidate["review_decision"] == "approve"
    assert candidate["review_state"] == "approved_for_review"
    assert candidate["review_carry"]["status"] == "boundary_changed"
    assert candidate["review_carry"]["requires_recheck"] is True
    assert candidate["review_carry"]["source_candidate_id"] == f"canon-{'a' * 16}"
    assert review["totals"]["boundary_changed_candidates"] == 1
    assert review["totals"]["new_candidates"] == 0
    assert review["totals"]["next_recheck_candidates"] == 1
    assert review["review_queue"] == {
        "strategy": "needs_work_then_boundary_changed_then_new_by_calibrated_worthiness",
        "candidate_count": 1,
        "candidate_ids": [changed_candidate["candidate_id"]],
    }


def test_review_carry_prefers_exact_legacy_fingerprint_over_route_name() -> None:
    decoy_payload = {
        **_compiler_candidate_fixture(),
        "candidate_fingerprint": "0" * 64,
        "legacy_candidate_fingerprints": ["e" * 64],
        "osm_way_refs": [999],
    }
    decoy = build_climb_lab_compiler_candidate_summary(
        _applied_compiler_report(decoy_payload),
        source_label="fixture-decoy.json",
    )["candidates"][0]
    correct = build_climb_lab_compiler_candidate_summary(
        _applied_compiler_report(_compiler_candidate_fixture()),
        source_label="fixture-v2.json",
    )["candidates"][0]
    record_climb_lab_review_decision(
        candidate_id=decoy["candidate_id"],
        decision="approve",
        note="same route, different candidate",
        candidate=decoy,
        reviewed_by="test-reviewer",
    )
    record_climb_lab_review_decision(
        candidate_id=correct["candidate_id"],
        decision="needs_work",
        note="the exact v2 candidate",
        candidate=correct,
        reviewed_by="test-reviewer",
    )

    v3_payload = {
        **_compiler_candidate_fixture(),
        "candidate_fingerprint": "b" * 64,
        "legacy_candidate_fingerprints": ["a" * 64],
    }
    v3_candidate = build_climb_lab_compiler_candidate_summary(
        _applied_compiler_report(v3_payload),
        source_label="fixture-v3.json",
    )["candidates"][0]
    review = build_climb_lab_candidate_review_summary(
        {
            "source": "fixture",
            "area_label": "fixture",
            "candidates": [v3_candidate],
        }
    )
    candidate = review["candidates"][0]

    assert candidate["review_decision"] == "needs_work"
    assert candidate["review_carry"]["source_candidate_id"] == f"canon-{'a' * 16}"
    assert candidate["review_carry"]["status"] == "boundary_changed"
    assert candidate["review_carry"]["requires_recheck"] is True


def test_review_carry_does_not_guess_when_explicit_lineage_has_no_match() -> None:
    decoy_payload = {
        **_compiler_candidate_fixture(),
        "candidate_fingerprint": "0" * 64,
        "osm_way_refs": [999],
    }
    decoy = build_climb_lab_compiler_candidate_summary(
        _applied_compiler_report(decoy_payload),
        source_label="fixture-decoy.json",
    )["candidates"][0]
    record_climb_lab_review_decision(
        candidate_id=decoy["candidate_id"],
        decision="approve",
        note="same route, no lineage relationship",
        candidate=decoy,
        reviewed_by="test-reviewer",
    )

    candidate_payload = {
        **_compiler_candidate_fixture(),
        "candidate_fingerprint": "b" * 64,
        "legacy_candidate_fingerprints": ["e" * 64],
    }
    candidate = build_climb_lab_compiler_candidate_summary(
        _applied_compiler_report(candidate_payload),
        source_label="fixture-unmatched-lineage.json",
    )["candidates"][0]
    review = build_climb_lab_candidate_review_summary(
        {
            "source": "fixture",
            "area_label": "fixture",
            "candidates": [candidate],
        }
    )
    reviewed = review["candidates"][0]

    assert reviewed["review_decision"] == "pending"
    assert reviewed["review_carry"]["status"] == "new"
    assert reviewed["review_carry"]["requires_recheck"] is True
    assert "source_candidate_id" not in reviewed["review_carry"]


def test_review_carry_rejects_ambiguous_route_only_matches() -> None:
    for fingerprint, way_ref, decision in [
        ("0" * 64, 998, "approve"),
        ("1" * 64, 999, "needs_work"),
    ]:
        prior_payload = {
            **_compiler_candidate_fixture(),
            "candidate_fingerprint": fingerprint,
            "legacy_candidate_fingerprints": [],
            "osm_way_refs": [way_ref],
        }
        prior = build_climb_lab_compiler_candidate_summary(
            _applied_compiler_report(prior_payload),
            source_label=f"fixture-{way_ref}.json",
        )["candidates"][0]
        record_climb_lab_review_decision(
            candidate_id=prior["candidate_id"],
            decision=decision,
            note="same route, distinct historical candidate",
            candidate=prior,
            reviewed_by="test-reviewer",
        )

    candidate_payload = {
        **_compiler_candidate_fixture(),
        "candidate_fingerprint": "b" * 64,
        "legacy_candidate_fingerprints": [],
        "osm_way_refs": [1000],
    }
    candidate = build_climb_lab_compiler_candidate_summary(
        _applied_compiler_report(candidate_payload),
        source_label="fixture-ambiguous-route.json",
    )["candidates"][0]
    review = build_climb_lab_candidate_review_summary(
        {
            "source": "fixture",
            "area_label": "fixture",
            "candidates": [candidate],
        }
    )
    reviewed = review["candidates"][0]

    assert reviewed["review_decision"] == "pending"
    assert reviewed["review_carry"]["status"] == "new"
    assert reviewed["review_carry"]["requires_recheck"] is True
    assert "source_candidate_id" not in reviewed["review_carry"]


def test_review_requires_recheck_when_profile_hash_changes_under_stable_identity() -> None:
    original = build_climb_lab_compiler_candidate_summary(
        _applied_compiler_report(_compiler_candidate_fixture()),
        source_label="fixture-profile-v1.json",
    )["candidates"][0]
    record_climb_lab_review_decision(
        candidate_id=original["candidate_id"],
        decision="approve",
        note="profile v1 reviewed",
        candidate=original,
        reviewed_by="test-reviewer",
    )

    changed_payload = {
        **_compiler_candidate_fixture(),
        "provenance": {
            "compiler": "fixture",
            "canonical_profile_hash": {
                "algorithm": "blake3_canonical_profile_v1",
                "value": "2" * 64,
            },
        },
    }
    changed = build_climb_lab_compiler_candidate_summary(
        _applied_compiler_report(changed_payload),
        source_label="fixture-profile-v2.json",
    )["candidates"][0]
    review = build_climb_lab_candidate_review_summary(
        {
            "source": "fixture",
            "area_label": "fixture",
            "candidates": [changed],
        }
    )
    candidate = review["candidates"][0]

    assert candidate["candidate_id"] == original["candidate_id"]
    assert candidate["review_decision"] == "approve"
    assert candidate["review_carry"]["status"] == "boundary_changed"
    assert candidate["review_carry"]["requires_recheck"] is True


def test_compiler_approval_builds_publish_payload_and_calls_publisher() -> None:
    candidate = build_climb_lab_compiler_candidate_summary(
        _applied_compiler_report(_compiler_candidate_fixture()),
    )["candidates"][0]
    published_payloads = []

    def publisher(payload: dict) -> dict:
        published_payloads.append(payload)
        return {
            "canon_climb_id": "11111111-1111-1111-1111-111111111111",
            "canon_id": "22222222-2222-2222-2222-222222222222",
            "version": 1,
            "status": "ratified",
            "corridor_cell_count": 1,
        }

    result = apply_climb_lab_review_action(
        candidate_id=candidate["candidate_id"],
        action_id="approve",
        note="ratified from compiler report",
        candidate=candidate,
        publisher=publisher,
        ratified_by="test-reviewer",
    )

    assert result["status"] == "recorded"
    assert result["publish_status"] == "published_to_canon_climbs_v1"
    assert result["publish_result"]["status"] == "ratified"
    assert len(published_payloads) == 1
    payload = published_payloads[0]
    assert payload["target_table"] == "canon_climbs"
    assert payload["target_version"] == 1
    assert payload["climb"]["candidate_fingerprint"] == "a" * 64
    assert payload["climb"]["legacy_candidate_fingerprints"] == ["f" * 64]
    assert payload["climb"]["corridor_half_width_m"] == 25.0
    assert payload["climb"]["ratified_by"] == "test-reviewer"
    assert payload["corridor_cells"][0]["tile_id"] == "8a2a1342b5a7fff"


def test_non_approval_review_actions_do_not_call_publisher() -> None:
    candidate = build_climb_lab_compiler_candidate_summary(
        _applied_compiler_report(_compiler_candidate_fixture()),
    )["candidates"][0]
    published_payloads = []

    def publisher(payload: dict) -> dict:
        published_payloads.append(payload)
        raise AssertionError("non-approval actions must not publish")

    result = apply_climb_lab_review_action(
        candidate_id=candidate["candidate_id"],
        action_id="suppress",
        note="too redundant for the launch set",
        candidate=candidate,
        publisher=publisher,
        ratified_by="test-reviewer",
    )

    assert result["status"] == "recorded"
    assert result["review_state"] == "suppressed"
    assert "publish_status" not in result
    assert published_payloads == []


def test_publish_payload_rejects_scan_only_candidate() -> None:
    try:
        build_canon_climb_publish_payload(
            {
                "candidate_id": "scan-only",
                "display_name": "Scan Only",
            }
        )
    except ValueError as exc:
        assert "centerline_wkt" in str(exc)
    else:
        raise AssertionError("scan-only candidate should not build publish payload")
