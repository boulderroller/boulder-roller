"""Synthetic fixtures only; no corpus rows, real tracks or rider identities."""
import math

import numpy as np
import pytest

from tools.stop_map.stop_map import (
    Control, Endpoint, RoadIndex, SnappedStop, Stop, classify_spot,
    cluster_stops, detect_stops, endpoint_exclusion, gate_flags,
    match_control, publish_spots, repeated_endpoints,
)


def ll(east_m=0, north_m=0):
    # Artificial equatorial fixtures, deliberately unrelated to corpus locations.
    return (north_m / 111195.0802, east_m / 111195.0802)


def stop(x=500, duration=5, rider=None, ride="synthetic-ride", heading=90):
    return Stop(ride, rider, 0, 1, duration, [ll(x), ll(x + 0.1)],
                ll(x), heading, False)


def snapped(s=50, rider="synthetic-a", direction=1, way=10, duration=10,
            turnaround=False, ride="synthetic-ride", day="2000-01-01"):
    result = SnappedStop(way, direction, s, duration, rider, ride,
                        (s, 0), 90 if direction == 1 else 270, turnaround)
    result.day = day
    return result


def recurring():
    return [snapped(ride=f"synthetic-{i}", day=f"2000-01-0{i+1}") for i in range(3)]


def test_stop_threshold_is_elapsed_three_seconds_strictly_below_one_mps():
    events = detect_stops([0, 1, 4, 7], [0, 2, 2, 5],
                         [ll(0), ll(2), ll(2), ll(5)], "synthetic-ride")
    assert [(e.first, e.last, e.duration_s) for e in events] == [(1, 2, 3)]


def test_two_seconds_is_not_a_stop_and_final_run_is_flushed():
    assert not detect_stops([0, 2], [0, 0], [ll(), ll()], "synthetic-ride")
    events = detect_stops([0, 4], [0, 0], [ll(), ll()], "synthetic-ride")
    assert len(events) == 1 and events[0].duration_s == 4


@pytest.mark.parametrize("times,distances", [
    ([0, 100], [0, 0]), ([0, 4], [20, 0]),
    ([0, 0], [0, 0]), ([4, 0], [0, 0]),
    ([0, 4], [0, math.nan]),
])
def test_missing_recording_and_invalid_intervals_do_not_become_stops(times, distances):
    assert not detect_stops(times, distances, [ll(), ll()], "synthetic-ride")


def test_movement_or_missing_gps_splits_runs():
    assert not detect_stops([0, 2, 3, 5], [0, 0, 5, 5],
                            [ll()] * 4, "synthetic-ride")
    assert not detect_stops([0, 2, 4], [0, 0, 0],
                            [ll(), (math.nan, 0), ll()], "synthetic-ride")


def test_direction_comes_from_approach_and_identifies_turnaround():
    event = detect_stops([0, 2, 3, 7, 8, 10], [0, 20, 21, 21, 22, 42],
                         [ll(0), ll(20), ll(21), ll(21), ll(20), ll(0)],
                         "synthetic-ride")[0]
    assert event.heading_deg == pytest.approx(90, abs=0.1)
    assert event.turnaround


def test_own_endpoint_filter_checks_all_samples_not_just_median():
    event = stop(450)
    event.samples = [ll(299), ll(450), ll(450)]
    assert endpoint_exclusion(event, [ll()], []) == "own_endpoint"
    assert endpoint_exclusion(stop(301), [ll()], []) is None


def test_repeated_endpoint_requires_different_rides_not_loop_ends():
    points = [Endpoint(ll(), "synthetic-a", "synthetic-rider"),
              Endpoint(ll(1), "synthetic-a", "synthetic-rider")]
    assert repeated_endpoints(points) == []
    points.append(Endpoint(ll(10), "synthetic-b", "synthetic-rider"))
    assert len(repeated_endpoints(points)) == 3


def test_unknown_rider_endpoints_use_conservative_pooled_mask():
    points = [Endpoint(ll(), "synthetic-a", None),
              Endpoint(ll(10), "synthetic-b", None)]
    assert len(repeated_endpoints(points)) == 2
    assert endpoint_exclusion(stop(149), [], [ll()]) == "repeated_endpoint"
    assert endpoint_exclusion(stop(151), [], [ll()]) is None


def test_repeated_points_from_other_riders_also_protect_a_stop():
    points = [Endpoint(ll(), "synthetic-a", "synthetic-x"),
              Endpoint(ll(10), "synthetic-b", "synthetic-x")]
    mask = repeated_endpoints(points)
    assert endpoint_exclusion(stop(100, rider="synthetic-y"), [], mask)


def test_unrelated_known_riders_do_not_create_a_repeat():
    assert not repeated_endpoints([
        Endpoint(ll(), "synthetic-a", "synthetic-x"),
        Endpoint(ll(), "synthetic-b", "synthetic-y"),
    ])


def test_direction_and_road_are_separate_clusters():
    clusters = cluster_stops([snapped(), snapped(direction=-1), snapped(way=11)])
    assert len(clusters) == 3


def test_clusters_have_bounded_diameter_not_a_single_link_chain():
    assert sorted(map(len, cluster_stops([snapped(s=x) for x in [0, 19, 38]]))) == [1, 2]


def test_unknown_identity_and_repeated_rides_cannot_satisfy_recurrence():
    assert publish_spots([[snapped(rider=None) for _ in range(20)]], []) == []
    assert publish_spots([[snapped() for _ in range(20)]], []) == []
    assert publish_spots([[snapped(rider=r) for r in ["synthetic-a", "synthetic-b", None]]], []) == []


def test_blank_identity_tokens_are_not_three_verified_riders():
    assert publish_spots([[snapped(rider=r) for r in [" ", "\t", "\n"]]], []) == []


def test_one_consented_rider_three_rides_three_days_publish_only_aggregates():
    cluster = [snapped(s=10+i, ride=f"synthetic-{i}", day=f"2000-01-0{i+1}", duration=6+i) for i in range(3)]
    published = publish_spots([cluster], [])
    assert len(published) == 1
    row = published[0]
    assert row["rider_count"] == 1
    assert row["ride_count"] == row["stop_count"] == 3
    assert row["median_length_s"] == 7
    assert "median_along_road_m" not in row  # exact way chainage would undo position rounding
    assert "rider" not in row and "ride_id" not in row and "samples" not in row
    assert "day" not in row and "dates" not in row


def test_three_rides_on_two_days_and_one_ride_on_three_days_fail():
    cluster = recurring()
    cluster[2].day = cluster[1].day
    assert publish_spots([cluster], []) == []
    cluster = recurring()
    for s in cluster:
        s.ride = "one-synthetic-ride"
    assert publish_spots([cluster], []) == []


def test_publisher_rechecks_own_endpoint_after_position_rounding():
    from tools.stop_map.stop_map import TO_LL
    cluster = recurring()
    lon, lat = TO_LL.transform(*cluster[0].xy)
    for s in cluster:
        s.own_endpoints = ((lat, lon),)
    assert publish_spots([cluster], []) == []


def test_publisher_uses_junction_context_for_classification_and_matching():
    cluster = recurring()
    row = publish_spots([cluster], [Control(1, 10, 80, "stop", 1)], junctions_by_way={10: [60]})[0]
    assert row["class"] == "likely unmapped control"
    assert row["matched_control"] is None


def test_directional_clusters_are_deterministic_under_permutation():
    stops = [snapped(s=x, direction=d) for x, d in [(0, 1), (19, 1), (38, 1), (0, -1)]]
    describe = lambda c: [[(s.way_id, s.direction, s.along_m) for s in g] for g in c]
    assert describe(cluster_stops(stops)) == describe(cluster_stops(list(reversed(stops))))


@pytest.mark.parametrize("kind", ["traffic_signals", "stop", "all_way_stop",
                                  "give_way", "signalled_crossing", "rail"])
def test_matches_each_kind_on_same_approach(kind):
    match = match_control(snapped(), [Control(1, 10, 90, kind, 1)])
    assert match is not None and match.kind == kind


def test_control_on_other_road_or_opposite_approach_does_not_match():
    assert match_control(snapped(), [Control(1, 11, 51, "stop", 1),
                                      Control(2, 10, 51, "stop", -1)]) is None
    assert match_control(snapped(), [Control(1, 10, 90.1, "stop", 1)]) is None


def test_unknown_facing_stop_is_not_blessed_and_nearest_applicable_wins():
    assert match_control(snapped(), [Control(1, 10, 51, "stop", None)]) is None
    controls = [Control(2, 10, 70, "stop", 1), Control(1, 10, 60, "stop", 1)]
    assert match_control(snapped(), controls).control_id == 1


def test_control_behind_previous_junction_is_not_same_approach():
    assert match_control(snapped(), [Control(1, 10, 70, "stop", 1)], [60]) is None


def test_classification_does_not_call_every_pause_a_traffic_control():
    assert classify_spot([snapped()], Control(1, 10, 60, "stop", 1), 10)[0] == "mapped control"
    assert classify_spot([snapped()], None, 10)[0] == "likely unmapped control"
    assert classify_spot([snapped(duration=300)], None, None)[0] == "not a control"
    assert classify_spot([snapped(turnaround=True)], None, 5)[0] == "not a control"
    assert classify_spot([snapped()], None, None)[0] == "unresolved"


def test_gate_flags_use_direction_and_metres_past_finish():
    line = [(0, 0), (100, 0)]
    assert gate_flags((110, 0), 90, line) == ["finish_0_15m_past"]
    assert gate_flags((116, 0), 90, line) == []
    assert gate_flags((-10, 0), 90, line) == ["start_within_15m"]
    assert gate_flags((50, 0), 90, line) == ["interior_information"]
    assert gate_flags((110, 0), 270, line) == []
    assert gate_flags((110, 20), 90, line) == []


def test_snapping_uses_heading_to_reject_crossing_road():
    index = RoadIndex.from_xy([
        {"osm_way_id": 1, "geometry": [(-100, 0), (100, 0)]},
        {"osm_way_id": 2, "geometry": [(0, -100), (0, 100)]},
    ])
    match, reason = index.snap_xy((0, 1), 90)
    assert reason is None and match["way_id"] == 1 and match["direction"] == 1
    assert index.snap_xy((0, 1000), 90)[1] == "outside_snap_radius"


def test_parallel_roads_and_missing_heading_are_rejected_as_ambiguous():
    index = RoadIndex.from_xy([
        {"osm_way_id": 1, "geometry": [(-100, 0), (100, 0)]},
        {"osm_way_id": 2, "geometry": [(-100, 2), (100, 2)]},
    ])
    assert index.snap_xy((0, 1), 90)[1] == "ambiguous_road"
    assert index.snap_xy((0, 1), None)[1] == "missing_direction"


def test_calendar_days_use_elapsed_stop_time_and_owner_timezone():
    from tools.stop_map.stop_map import calendar_day
    assert calendar_day("2000-01-02T04:59:59Z", 0) == "2000-01-01"
    assert calendar_day("2000-01-02T04:59:59Z", 2) == "2000-01-02"


def test_strict_compiler_debug_transport_retains_only_needed_public_nodes(tmp_path):
    from tools.stop_map.graph_context import read_control_graph
    path = tmp_path / "public.debug"
    path.write_text('FinishControlGraph { nodes: {1: Node { lat: 40.0, lon: -75.0, tags: {"highway": "stop", "name": "Not Node { malicious: 1 }"} }, 2: Node { lat: 40.1, lon: -75.1, tags: {} }}, ways: {10: Way { id: 10, nodes: [1, 2], tags: {"name": "Test"} }}, junctions: {1}, stop_lines: [] }')
    graph = read_control_graph(path, {10}, {1})
    assert set(graph["nodes"]) == {1}
    assert graph["nodes"][1]["tags"]["name"] == "Not Node { malicious: 1 }"
    path.write_text(path.read_text() + " trailing junk")
    with pytest.raises(ValueError):
        read_control_graph(path, {10}, {1})


def test_unknown_direction_control_remains_unresolved_not_unmapped():
    assert classify_spot([snapped()], None, 10, ambiguous_control=True)[0] == "unresolved"


def test_mapped_control_is_retained_even_when_the_rider_turns_around():
    assert classify_spot([snapped(turnaround=True)], Control(1, 10, 60, "stop", 1), 10)[0] == "mapped control"


def test_gate_distance_checks_use_published_point_and_way_membership():
    from tools.stop_map.gate_checks import relation
    assert relation((110, 0), 90, [(0, 0), (100, 0)]) == pytest.approx((110, 0, 100))
    assert relation((110, 20), 90, [(0, 0), (100, 0)]) is None


def test_three_rides_require_three_independent_day_witnesses():
    cluster = [snapped(ride=r, day=d) for r, d in [("A", "2000-01-01"), ("A", "2000-01-02"), ("B", "2000-01-03"), ("C", "2000-01-03")]]
    assert publish_spots([cluster], []) == []


def test_compiler_debug_preserves_escaped_literal_unicode_text():
    from tools.stop_map.graph_context import DebugReader
    assert DebugReader(br'"literal \\u{41}"').value() == r"literal \u{41}"
    assert DebugReader(br'"actual \u{41}"').value() == "actual A"


def branch_context(branch=True):
    from tools.stop_map.graph_context import GraphContext
    rows = [{"osm_way_id": 10, "geometry": [(0, 0), (20, 0), (40, 0)] if branch else [(0, 0), (60, 0), (100, 0)], "osm_node_ids": [1, 2, 3]},
            {"osm_way_id": 11, "geometry": [(20, 0), (20, 50)] if branch else [(100, 0), (150, 0)], "osm_node_ids": [2, 4] if branch else [3, 4]}]
    graph = {"nodes": {n: {"tags": {}} for n in [1, 2, 3, 4]},
             "ways": {r["osm_way_id"]: {"tags": {"name": "Same"}} for r in rows}, "junctions": set()}
    graph["nodes"][3 if branch else 4]["tags"] = {"highway": "stop", "direction": "forward"}
    return GraphContext(graph, RoadIndex.from_xy(rows))


def test_same_name_interior_branch_blocks_matching_beyond_junction():
    context = branch_context()
    observation = snapped(s=10)
    controls, junctions, _ = context.approach(observation)
    assert 20 in junctions
    assert match_control(observation, controls, junctions) is None


def test_gate_accepts_connected_continuation_but_rejects_branch_and_layer():
    from tools.stop_map.gate_checks import same_gate_approach
    context = branch_context(False)
    assert same_gate_approach(11, {10}, context.public_topology())
    context.graph["ways"][11]["tags"]["layer"] = "1"
    assert not same_gate_approach(11, {10}, context.public_topology())
    assert not same_gate_approach(11, {10}, branch_context().public_topology())


def test_bent_continuation_uses_road_distance_not_endpoint_tangent():
    from tools.stop_map.gate_checks import road_distance_to_gate
    topology = branch_context(False).public_topology()
    topology["ways"]["11"]["geometry"] = [(100, 0), (100, 10), (110, 10)]
    topology["ways"]["11"]["nodes"] = [3, 5, 4]
    assert road_distance_to_gate(11, 1, (110, 10), (100, 0), 90, {10}, topology, -1) == pytest.approx(20)


def test_gate_at_junction_is_reachable_from_aligned_departure_but_not_cross_street():
    from tools.stop_map.gate_checks import road_distance_to_gate
    topology = branch_context(False).public_topology()
    topology["ways"]["12"] = {"nodes": [3, 5], "geometry": [(100, 0), (100, 50)], "tags": {"name": "Other"}}
    assert road_distance_to_gate(11, 1, (110, 0), (100, 0), 90, {10}, topology, -1) == pytest.approx(10)
    assert road_distance_to_gate(12, 1, (100, 10), (100, 0), 90, {10}, topology, -1) is None
