//! Regressions for Claude's 20 October finish-rule review.
use super::tests::{fixture, run, set_tags};
use super::*;

#[test]
fn straight_junction_ten_metres_beyond_sampled_end_moves_finish() {
    let (c, mut g) = fixture();
    g.nodes.get_mut(&30).unwrap().lat += 10.0 / 111_320.0;
    set_tags(&mut g, 30, &[("highway", "traffic_signals")]);
    assert!((c.length_m - run(&c, &g).length_m - 17.0).abs() < 0.03);
}

#[test]
fn straight_junction_thirteen_metres_beyond_sampled_end_is_unchanged() {
    let (c, mut g) = fixture();
    g.nodes.get_mut(&30).unwrap().lat += 13.0 / 111_320.0;
    set_tags(&mut g, 30, &[("highway", "traffic_signals")]);
    assert_eq!(run(&c, &g).centerline_wkt, c.centerline_wkt);
}

#[test]
fn control_beyond_sampled_end_still_qualifies_its_on_span_junction() {
    let (c, mut g) = fixture();
    let mut node = g.nodes[&30].clone();
    node.lat += 20.0 / 111_320.0;
    node.tags.insert("highway".into(), "traffic_signals".into());
    g.nodes.insert(31, node);
    g.ways.get_mut(&1).unwrap().nodes.push(31);
    assert!((c.length_m - run(&c, &g).length_m - 27.0).abs() < 0.03);
}

#[test]
fn cut_below_either_compiler_minimum_preserves_original_and_flags_review() {
    for (length_scale, rise) in [(1.0 / 3.0, 30.0), (1.0, 8.5)] {
        let (mut c, mut g) = fixture();
        let mut points = source_points(&c).unwrap();
        for (i, p) in points.iter_mut().enumerate() {
            p.lat = 40.0 + (p.lat - 40.0) * length_scale;
            p.elev_m = 50.0 + i as f64 * rise / 30.0;
            g.nodes.get_mut(&(i as i64)).unwrap().lat = p.lat;
        }
        replace_profile(&mut c, &mut points);
        c.vert_m = rise;
        set_tags(&mut g, 30, &[("highway", "traffic_signals")]);
        let out = run(&c, &g);
        assert_eq!(out.centerline_wkt, c.centerline_wkt);
        assert_eq!(out.candidate_fingerprint, c.candidate_fingerprint);
        assert_eq!(out.gate_end_wkt, c.gate_end_wkt);
        assert!(out.provenance["finish_rule_unresolved"]["reason"]
            .as_str()
            .unwrap()
            .contains("finish rule would leave climb below minimums"));
    }
}

#[test]
fn distant_ambiguous_control_is_not_an_unresolved_climb() {
    let (c, _) = fixture();
    let mut points = source_points(&c).unwrap();
    points.extend(points[27..].to_vec());
    rebase_distances(&mut points);
    for offset in [1.1, 186.5] {
        let node = Node {
            lat: points.last().unwrap().lat,
            lon: -75.0 + offset / (111_320.0 * 40f64.to_radians().cos()),
            tags: Tags::new(),
        };
        assert!(
            locate(&node, &points)
                .expect("off-span ambiguity is irrelevant")
                .1
                > 1.0
        );
    }
}

#[test]
fn predecessor_identity_alone_cannot_admit_another_finish_position() {
    let (mut c, mut g) = fixture();
    let d = &decisions().decisions[0];
    c.candidate_fingerprint = d.candidate_fingerprint.clone();
    c.display_name = d.display_name.clone();
    set_tags(&mut g, 30, &[("highway", "traffic_signals")]);
    let out = run(&c, &g);
    assert_eq!(
        out.provenance["finish_gate_rule"]["admission"],
        "proposed by rule, not admitted"
    );
    assert!(out.provenance["finish_gate_rule"]["founder_approval"].is_null());
}

#[test]
fn position_approval_and_west_school_covering_note_are_bounded() {
    for d in &decisions().decisions {
        let point = |p: &ApprovedPosition, offset: f64| CanonProfilePoint {
            lat: p.lat + offset / 111_195.0,
            lon: p.lon,
            elev_m: 0.0,
            dist_m: 0.0,
        };
        assert!(approved_finish(
            d,
            d.junction_node_id,
            &point(&d.approved_position, 0.49)
        ));
        assert!(!approved_finish(
            d,
            d.junction_node_id + 1,
            &point(&d.approved_position, 0.0)
        ));
        assert!(!approved_finish(
            d,
            d.junction_node_id,
            &point(&d.approved_position, 3.0)
        ));
        if let Some(note) = &d.covering_note {
            assert_eq!(d.display_name, "West School House Lane");
            assert!((note.position.setback_from_junction_m - 33.79).abs() < 0.01);
            assert!(approved_finish(
                d,
                d.junction_node_id,
                &point(&note.position, 0.0)
            ));
            assert!(!approved_finish(
                d,
                d.junction_node_id,
                &point(&note.position, 1.5)
            ));
        } else {
            assert!(!approved_finish(
                d,
                d.junction_node_id,
                &point(&d.approved_position, 0.51)
            ));
        }
    }
}

#[test]
fn black_rock_re_evidences_only_the_exact_unchanged_start_gate() {
    let (mut c, mut g) = fixture();
    let d = decisions()
        .decisions
        .iter()
        .find(|d| d.display_name == "Black Rock Road")
        .unwrap();
    let revision = d.start_gate_revision.as_ref().unwrap();
    c.candidate_fingerprint = d.candidate_fingerprint.clone();
    c.display_name = d.display_name.clone();
    c.gate_start_wkt = revision["gate_start_wkt"].as_str().unwrap().into();
    c.provenance["capture_tolerance_revision"] =
        json!({"revision_id":revision["predecessor_revision_id"]});
    set_tags(&mut g, 30, &[("highway", "traffic_signals")]);
    let out = run(&c, &g);
    let active = &out.provenance["capture_tolerance_revision"];
    assert_eq!(active["scope"], "start_gate_only");
    assert_eq!(active["status"], "active_re_evidenced");
    assert_eq!(active["gate_start_half_extent_m"], 30.0);
    assert_eq!(active["record_continuity_policy"], "new_record_board");
    assert_eq!(active["candidate_fingerprint"], out.candidate_fingerprint);
    assert_eq!(out.gate_start_wkt, c.gate_start_wkt);
    assert!((symmetric_gate_half_extent_m(&out.gate_end_wkt).unwrap() - 25.0).abs() < 0.02);
    c.gate_start_wkt = resize_symmetric_gate(&c.gate_start_wkt, 25.0).unwrap();
    assert!(run(&c, &g)
        .provenance
        .get("capture_tolerance_revision")
        .is_none());
}

#[test]
fn every_control_kind_has_fifteen_metres_clearance() {
    for tags in [
        vec![("highway", "traffic_signals")],
        vec![("crossing", "traffic_signals")],
        vec![("highway", "stop"), ("stop", "all")],
        vec![("highway", "stop"), ("direction", "forward")],
        vec![("highway", "give_way"), ("direction", "forward")],
        vec![("railway", "level_crossing")],
    ] {
        let (c, mut g) = fixture();
        set_tags(&mut g, 28, &tags);
        let out = run(&c, &g);
        assert!((c.length_m - out.length_m - 35.0).abs() < 0.03, "{tags:?}");
    }
}

#[test]
fn cutting_rechecks_controls_until_every_nearby_control_is_cleared() {
    let (c, mut g) = fixture();
    for id in [30, 26, 25] {
        set_tags(&mut g, id, &[("highway", "traffic_signals")]);
    }
    let out = run(&c, &g);
    assert!((c.length_m - out.length_m - 65.0).abs() < 0.03);
}

#[test]
fn iterative_cut_clears_painted_line_outside_initial_junction_window() {
    let (c, mut g) = fixture();
    set_tags(&mut g, 28, &[("highway", "traffic_signals")]);
    let lat = (g.nodes[&25].lat + g.nodes[&26].lat) / 2.0;
    for (id, lon) in [(100, -75.0001), (101, -74.9999)] {
        g.nodes.insert(
            id,
            Node {
                lat,
                lon,
                tags: Tags::new(),
            },
        );
    }
    g.stop_lines.push(Way {
        id: 9,
        nodes: vec![100, 101],
        tags: Tags::from([("road_marking".into(), "stop_line".into())]),
    });
    assert!((c.length_m - run(&c, &g).length_m - 60.0).abs() < 0.03);
}

#[test]
fn off_centreline_control_is_not_on_the_climb() {
    let (c, mut g) = fixture();
    set_tags(&mut g, 28, &[("highway", "stop"), ("stop", "all")]);
    g.nodes.get_mut(&28).unwrap().lon += 2.0 / (111_320.0 * 40f64.to_radians().cos());
    assert_eq!(run(&c, &g).length_m, c.length_m);
}

#[test]
fn nearby_control_with_a_long_way_detour_is_not_adjacent() {
    let (c, mut g) = fixture();
    set_tags(&mut g, 28, &[("highway", "stop"), ("stop", "all")]);
    let mut detour = g.nodes[&29].clone();
    detour.lon -= 0.001;
    g.nodes.insert(100, detour);
    g.ways.get_mut(&1).unwrap().nodes.insert(29, 100);
    assert_eq!(run(&c, &g).length_m, c.length_m);
}

#[test]
fn junction_twenty_metres_from_finish_is_outside_window() {
    let (c, mut g) = fixture();
    g.junctions = BTreeSet::from([28]);
    set_tags(&mut g, 28, &[("highway", "stop"), ("stop", "all")]);
    assert_eq!(run(&c, &g).length_m, c.length_m);
}

#[test]
fn all_way_stop_on_another_road_is_not_an_own_road_control() {
    let (c, mut g) = fixture();
    let mut n = g.nodes[&29].clone();
    n.tags = Tags::from([
        ("highway".into(), "stop".into()),
        ("stop".into(), "all".into()),
    ]);
    g.nodes.insert(99, n);
    g.ways.insert(
        2,
        Way {
            id: 2,
            nodes: vec![99, 30],
            tags: Tags::new(),
        },
    );
    assert_eq!(run(&c, &g).length_m, c.length_m);
}

#[test]
fn unknown_stop_and_give_way_never_inherit_backward_direction() {
    for kind in ["stop", "give_way"] {
        let (c, mut g) = fixture();
        g.ways.get_mut(&1).unwrap().nodes.reverse();
        set_tags(&mut g, 30, &[("highway", kind)]);
        assert_eq!(run(&c, &g).length_m, c.length_m);
    }
}

#[test]
fn nearby_junction_on_unused_road_arm_does_not_move_finish() {
    let (c, mut g) = fixture();
    let mut n = g.nodes[&30].clone();
    n.lon += 5.0 / (111_320.0 * 40f64.to_radians().cos());
    n.tags.insert("highway".into(), "traffic_signals".into());
    g.nodes.insert(99, n);
    g.ways.get_mut(&1).unwrap().nodes.push(99);
    g.junctions = BTreeSet::from([99]);
    assert_eq!(run(&c, &g).length_m, c.length_m);
}

#[test]
fn boundary_change_supersedes_end_override_but_keeps_start() {
    let (mut c, mut g) = fixture();
    c.gate_start_wkt = resize_symmetric_gate(&c.gate_start_wkt, 30.0).unwrap();
    c.gate_end_wkt = resize_symmetric_gate(&c.gate_end_wkt, 35.0).unwrap();
    c.provenance["capture_tolerance_revision"] = json!({
        "revision_id":"black-rock-test", "record_continuity_policy":CAPTURE_RECORD_CONTINUITY_POLICY,
        "unchanged_identity_fields":["measured_span","candidate_fingerprint"],
        "revised_geometry_policy":{"gate_start_half_extent_m":30,"gate_end_half_extent_m":35}
    });
    let source = serde_json::to_vec(&c).unwrap();
    set_tags(&mut g, 30, &[("highway", "traffic_signals")]);
    let out = run(&c, &g);
    assert!((symmetric_gate_half_extent_m(&out.gate_end_wkt).unwrap() - 25.0).abs() < 0.02);
    assert_eq!(out.gate_start_wkt, c.gate_start_wkt);
    assert!(out.provenance.get("capture_tolerance_revision").is_none());
    assert_eq!(
        out.provenance["superseded_capture_tolerance_revision"]["revision"]["revision_id"],
        "black-rock-test"
    );
    assert_eq!(serde_json::to_vec(&c).unwrap(), source);
}

fn replace_profile(c: &mut CanonCandidate, points: &mut [CanonProfilePoint]) {
    rebase_distances(points);
    c.centerline_wkt = line_string_wkt(points);
    c.canonical_profile = points
        .iter()
        .map(|p| CanonProfileSample {
            dist_m: round2(p.dist_m),
            elev_m: round2(p.elev_m),
        })
        .collect();
    c.length_m = round2(points.last().unwrap().dist_m);
    c.max_gradient_pct = round3(max_gradient_pct(points));
    c.provenance["compiler_profile_points"] = json!(points);
}

#[test]
fn kept_grades_use_unrounded_profile_points() {
    let (mut c, mut g) = fixture();
    let mut points = line_string_profile_points(&c.centerline_wkt).unwrap();
    for (i, p) in points.iter_mut().enumerate() {
        p.lat += i as f64 * 0.000000031;
        p.elev_m = 50.0031 + i as f64 * 1.0037;
    }
    replace_profile(&mut c, &mut points);
    for (i, p) in points.iter().enumerate() {
        g.nodes.get_mut(&(i as i64)).unwrap().lat = p.lat;
    }
    set_tags(&mut g, 30, &[("highway", "traffic_signals")]);
    assert_eq!(run(&c, &g).max_gradient_pct, c.max_gradient_pct);
}

#[test]
fn neill_submetre_cut_snaps_and_gate_is_perpendicular_to_final_segment() {
    let (mut c, _) = fixture();
    // Retained Neill Drive tail: the original 27m cut leaves a 0.32m
    // final segment, whose gate angle was 91.8 degrees.
    let mut points: Vec<_> = [
        (40.0066423, -75.2089061, 59.77),
        (40.0066488, -75.2089147, 59.81),
        (40.006712, -75.2089982, 60.25),
        (40.0067753, -75.2090817, 60.73),
        (40.0068385, -75.2091652, 61.22),
        (40.0069017, -75.2092487, 61.56),
        (40.006918, -75.2092688, 61.7),
        (40.0069834, -75.2093494, 62.13),
        (40.0070158, -75.2093872, 62.39),
        (40.0070828, -75.2094654, 62.83),
    ]
    .into_iter()
    .map(|(lat, lon, elev_m)| CanonProfilePoint {
        lat,
        lon,
        elev_m,
        dist_m: 0.0,
    })
    .collect();
    // The retained tail alone is below compiler minimums. Add an uphill
    // approach without changing any of the terminal geometry under test.
    let mut approach = points[0].clone();
    approach.lat -= 200.0 / 111_195.0;
    approach.elev_m -= 20.0;
    points.insert(0, approach);
    replace_profile(&mut c, &mut points);
    let target = points.last().unwrap().dist_m - 27.0;
    let k = points.partition_point(|p| p.dist_m < target);
    assert!((target - points[k - 1].dist_m - 0.32).abs() < 0.03);
    let mut g = FinishControlGraph {
        nodes: points
            .iter()
            .enumerate()
            .map(|(i, p)| {
                (
                    i as i64,
                    Node {
                        lat: p.lat,
                        lon: p.lon,
                        tags: Tags::new(),
                    },
                )
            })
            .collect(),
        ways: BTreeMap::from([(
            1,
            Way {
                id: 1,
                nodes: (0..points.len() as i64).collect(),
                tags: Tags::new(),
            },
        )]),
        junctions: BTreeSet::from([10]),
        stop_lines: vec![],
    };
    set_tags(&mut g, 10, &[("highway", "traffic_signals")]);
    let out = run(&c, &g);
    let tail = line_string_profile_points(&out.centerline_wkt).unwrap();
    let a = &tail[tail.len() - 2];
    let b = tail.last().unwrap();
    assert!(haversine_m(a.lat, a.lon, b.lat, b.lon) >= 1.0);
    let gate = line_string_profile_points(&out.gate_end_wkt).unwrap();
    let cos = b.lat.to_radians().cos();
    let u = ((b.lon - a.lon) * cos, b.lat - a.lat);
    let v = ((gate[1].lon - gate[0].lon) * cos, gate[1].lat - gate[0].lat);
    let angle = ((u.0 * v.0 + u.1 * v.1) / (u.0.hypot(u.1) * v.0.hypot(v.1)))
        .acos()
        .to_degrees();
    assert!((angle - 90.0).abs() < 0.1, "gate angle {angle}");
}

#[test]
fn snapping_skips_a_run_of_submetre_terminal_vertices() {
    let (mut c, mut g) = fixture();
    let mut points = line_string_profile_points(&c.centerline_wkt).unwrap();
    for (i, p) in points.iter_mut().enumerate() {
        p.elev_m = 50.0 + i as f64;
    }
    // Cut is near273m. Insert turned points at272.4m and272.7m so
    // snapping to just the nearest vertex still leaves a tiny last leg.
    let lat = 40.0 + 272.4 / 111_195.0;
    points.insert(
        28,
        CanonProfilePoint {
            dist_m: 0.0,
            lat,
            lon: -75.0,
            elev_m: 77.24,
        },
    );
    points.insert(
        29,
        CanonProfilePoint {
            dist_m: 0.0,
            lat,
            lon: -75.0 + 0.3 / (111_320.0 * 40f64.to_radians().cos()),
            elev_m: 77.27,
        },
    );
    replace_profile(&mut c, &mut points);
    // Keep the junction at the actual end; default target is still within
    // one metre of the turned sub-metre pair.
    set_tags(&mut g, 30, &[("highway", "traffic_signals")]);
    let out = run(&c, &g);
    let tail = line_string_profile_points(&out.centerline_wkt).unwrap();
    let a = &tail[tail.len() - 2];
    let b = tail.last().unwrap();
    assert!(haversine_m(a.lat, a.lon, b.lat, b.lon) >= 1.0);
}

#[test]
fn ambiguous_control_flags_only_its_climb_and_compilation_continues() {
    let (mut c, mut g) = fixture();
    let mut points = line_string_profile_points(&c.centerline_wkt).unwrap();
    // A repeated terminal arm gives two equally plausible progress values.
    let tail = points[27..].to_vec();
    points.extend(tail);
    for (i, p) in points.iter_mut().enumerate() {
        p.elev_m = 50.0 + i as f64;
    }
    replace_profile(&mut c, &mut points);
    set_tags(&mut g, 30, &[("highway", "traffic_signals")]);
    let mut candidates = vec![c.clone()];
    apply_finish_gate_rule(&mut candidates, &g).expect("ambiguity is a per-climb review flag");
    assert_eq!(candidates[0].centerline_wkt, c.centerline_wkt);
    assert!(candidates[0]
        .low_confidence_flags
        .iter()
        .any(|f| f == "finish_rule_unresolved"));
    assert!(candidates[0].provenance["finish_rule_unresolved"]["reason"]
        .as_str()
        .unwrap()
        .contains(&c.display_name));
}

// Minimal raw protobuf writer for a real PBF reader test. No mock graph reader.
fn varint(mut n: u64) -> Vec<u8> {
    let mut b = vec![];
    while n >= 128 {
        b.push((n as u8 & 127) | 128);
        n >>= 7;
    }
    b.push(n as u8);
    b
}
fn int(field: u64, n: u64) -> Vec<u8> {
    [varint(field << 3), varint(n)].concat()
}
fn bytes(field: u64, b: &[u8]) -> Vec<u8> {
    [varint((field << 3) | 2), varint(b.len() as u64), b.to_vec()].concat()
}
fn zig(n: i64) -> u64 {
    ((n << 1) ^ (n >> 63)) as u64
}
fn pbf_fixture(other_name: &str, other_layer: &str) -> std::path::PathBuf {
    let strings = [
        "",
        "highway",
        "residential",
        "name",
        "Neill Drive",
        other_name,
        "traffic_signals",
        "layer",
        other_layer,
    ];
    let table: Vec<u8> = strings
        .iter()
        .flat_map(|s| bytes(1, s.as_bytes()))
        .collect();
    let mut nodes = vec![];
    for id in 0..=31 {
        let mut n = [
            int(1, zig(id)),
            int(8, zig((40.0 * 1e7 + id as f64 * 900.0) as i64)),
            int(9, zig(-750000000)),
        ]
        .concat();
        if id == 30 {
            n.extend(bytes(2, &[1]));
            n.extend(bytes(3, &[6]));
        }
        nodes.extend(bytes(1, &n));
    }
    let mut ways = vec![];
    for (id, refs, name) in [(1, (0..=30).collect::<Vec<i64>>(), 4), (2, vec![30, 31], 5)] {
        let mut w = [
            int(1, id),
            bytes(2, &[1, 3, 7]),
            bytes(3, &[2, name, if id == 1 { 0 } else { 8 }]),
        ]
        .concat();
        let mut prior = 0;
        let refs: Vec<u8> = refs
            .into_iter()
            .flat_map(|n| {
                let v = varint(zig(n - prior));
                prior = n;
                v
            })
            .collect();
        w.extend(bytes(8, &refs));
        ways.extend(bytes(3, &w));
    }
    let block = [bytes(1, &table), bytes(2, &nodes), bytes(2, &ways)].concat();
    let blob = bytes(1, &block);
    let header = [bytes(1, b"OSMData"), int(3, blob.len() as u64)].concat();
    static SEQ: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let path = std::env::temp_dir().join(format!(
        "finish-rule-{}-{}.pbf",
        std::process::id(),
        SEQ.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ));
    std::fs::write(
        &path,
        [(header.len() as u32).to_be_bytes().to_vec(), header, blob].concat(),
    )
    .unwrap();
    path
}

#[test]
fn pbf_reader_requires_differently_named_same_layer_road() {
    let (c, _) = fixture();
    for (name, layer, junction) in [
        ("Neill Drive", "", false),
        ("Cross Street", "", true),
        ("Cross Street", "1", false),
    ] {
        let path = pbf_fixture(name, layer);
        let graph = read_finish_control_graph(&path, std::slice::from_ref(&c)).unwrap();
        std::fs::remove_file(path).unwrap();
        assert_eq!(graph.junctions.contains(&30), junction, "{name}/{layer}");
        assert_eq!(graph.nodes[&30].tags["highway"], "traffic_signals");
    }
}

#[test]
fn approved_stop_spots_clear_both_amended_finishes() {
    // Retained compiler approach coordinates, extended upstream for a unit
    // fixture; stop positions are the consented, published aggregates only.
    for (name, way_id, stop_lat, stop_lon, requested, tail) in [
        (
            "Wises Mill Road",
            1218053063,
            40.05383,
            -75.23099,
            30.0,
            [
                (40.0539326, -75.2307995, 93.24374832307235),
                (40.05393, -75.2308048, 93.32774498324414),
                (40.05387871466247, -75.23089740948451, 94.59304835488732),
                (40.053826, -75.2309926, 95.31774701759264),
                (40.05380437130122, -75.23103753790078, 95.57282632313076),
                (40.0537565, -75.231137, 96.0086775981926),
            ],
        ),
        (
            "Centennial Road",
            12333811,
            40.02338,
            -75.25527,
            29.0,
            [
                (40.02351991231545, -75.25498856427478, 88.8259216619346),
                (40.02347064154364, -75.25508680951653, 89.78284045098094),
                (40.02342137077182, -75.25518505475826, 90.22433569016005),
                (40.0233721, -75.2552833, 91.05140549568308),
                (40.02336240022769, -75.2553115440682, 91.15001469239778),
                (40.0233256, -75.2554187, 91.42284089574343),
            ],
        ),
    ] {
        let d = decisions()
            .decisions
            .iter()
            .find(|d| d.display_name == name)
            .unwrap();
        let (mut c, mut g) = fixture();
        let (a, b) = (tail[0], tail[1]);
        let extension = 200.0 / haversine_m(a.0, a.1, b.0, b.1);
        let mut points = vec![CanonProfilePoint {
            lat: a.0 + (a.0 - b.0) * extension,
            lon: a.1 + (a.1 - b.1) * extension,
            elev_m: a.2 - 30.0,
            dist_m: 0.0,
        }];
        points.extend(
            tail.into_iter()
                .map(|(lat, lon, elev_m)| CanonProfilePoint {
                    lat,
                    lon,
                    elev_m,
                    dist_m: 0.0,
                }),
        );
        replace_profile(&mut c, &mut points);
        c.candidate_fingerprint = d.candidate_fingerprint.clone();
        c.display_name = name.into();
        c.osm_way_refs = vec![way_id];
        let ids: Vec<_> = (0..points.len())
            .map(|i| {
                if i == points.len() - 1 {
                    d.junction_node_id
                } else {
                    i as i64
                }
            })
            .collect();
        g.nodes = ids
            .iter()
            .zip(&points)
            .map(|(id, p)| {
                (
                    *id,
                    Node {
                        lat: p.lat,
                        lon: p.lon,
                        tags: Tags::new(),
                    },
                )
            })
            .collect();
        g.ways = BTreeMap::from([(
            way_id,
            Way {
                id: way_id,
                nodes: ids,
                tags: Tags::new(),
            },
        )]);
        g.junctions = BTreeSet::from([d.junction_node_id]);
        set_tags(
            &mut g,
            d.junction_node_id,
            &[("highway", "traffic_signals")],
        );
        let stop = Node {
            lat: stop_lat,
            lon: stop_lon,
            tags: Tags::new(),
        };
        let stop_s = locate(&stop, &points).unwrap().0;
        let out = run(&c, &g);
        let rule = &out.provenance["finish_gate_rule"];
        assert!(
            rule["setback_from_junction_m"].as_f64().unwrap() >= requested - 0.001,
            "{name}: founder's amended setback must apply"
        );
        let cut = source_points(&out).unwrap();
        assert!(
            stop_s - cut.last().unwrap().dist_m >= 15.0 - 1e-6,
            "{name}: stop clearance"
        );
        let gate = line_string_profile_points(&out.gate_end_wkt).unwrap();
        let center = Node {
            lat: (gate[0].lat + gate[1].lat) / 2.0,
            lon: (gate[0].lon + gate[1].lon) / 2.0,
            tags: Tags::new(),
        };
        assert!(
            stop_s - locate(&center, &points).unwrap().0 >= 15.0,
            "{name}: serialized gate clearance"
        );
        assert_eq!(rule["founder_approval"]["quote"], "yes shift both back");
        assert_eq!(rule["admission"], "founder_admitted");
        assert_eq!(out.gate_start_wkt, c.gate_start_wkt);
        assert!(approved_finish(d, d.junction_node_id, cut.last().unwrap()));
    }
}
