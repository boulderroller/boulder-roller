//! Real local Pennsylvania/profile regression. Run explicitly with the retained
//! CANON_TEST_* paths; no network, database, elevation service or publisher.
#![cfg(feature = "osm")]

use serde_json::Value;
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::PathBuf,
    process::Command,
};

#[test]
#[ignore = "requires retained Pennsylvania PBF, local 3DEP profiles and baseline report"]
fn full_finish_compile_2051_is_complete_and_byte_deterministic() {
    let path = |name| PathBuf::from(std::env::var(name).expect(name));
    let pbf = path("CANON_TEST_PBF");
    let profiles = path("CANON_TEST_PROFILES");
    let baseline = path("CANON_TEST_BASELINE");
    let output = path("CANON_TEST_OUTPUT_DIR");
    let reviewed: Value =
        serde_json::from_slice(&fs::read(path("CANON_TEST_REVIEWED")).unwrap()).unwrap();
    let previous: Value =
        serde_json::from_slice(&fs::read(path("CANON_TEST_PREVIOUS")).unwrap()).unwrap();
    let span: Value = serde_json::from_slice(&fs::read(path("CANON_TEST_SPAN")).unwrap()).unwrap();
    let crest_previous: Value = serde_json::from_slice(&fs::read(path("CANON_TEST_CREST_PREVIOUS")).unwrap()).unwrap();
    fn lineage(c: &Value) -> &str {
        if !c["provenance"]["ratified_boundary"]["finish_decision"].is_null() {
            return c["provenance"]["ratified_boundary"]["replaces_candidate_fingerprint"].as_str().unwrap();
        }
        c["provenance"]["finish_gate_rule"]["predecessor_fingerprint"]
            .as_str()
            .unwrap_or_else(|| c["candidate_fingerprint"].as_str().unwrap())
    }
    let previous: BTreeMap<_, _> = previous["candidates"]
        .as_array()
        .unwrap()
        .iter()
        .map(|c| (lineage(c), c))
        .collect();
    let crest_previous: BTreeMap<_, _> = crest_previous["candidates"].as_array().unwrap()
        .iter().map(|c| (lineage(c), c)).collect();
    let reviewed: BTreeMap<_, _> = reviewed["candidates"]
        .as_array()
        .unwrap()
        .iter()
        .map(|c| (lineage(c), c))
        .collect();
    let span_additions: BTreeSet<_> = span["candidates"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|c| {
            !c["provenance"]["finish_gate_rule"].is_null()
                && reviewed[lineage(c)]["provenance"]["finish_gate_rule"].is_null()
        })
        .map(lineage)
        .collect();
    let below_minimums: BTreeSet<_> = span["candidates"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|c| {
            !c["provenance"]["finish_gate_rule"].is_null()
                && (c["length_m"].as_f64().unwrap() < 90.0 || c["vert_m"].as_f64().unwrap() < 8.0)
        })
        .map(lineage)
        .collect();
    assert_eq!(span_additions.len(), 17);
    assert_eq!(below_minimums.len(), 33);
    fs::create_dir_all(&output).unwrap();
    for i in 1..=2 {
        let log = fs::File::create(output.join(format!("full-{i}.log"))).unwrap();
        let status = Command::new(env!("CARGO_BIN_EXE_canon-compile"))
            .args(["--pbf"])
            .arg(&pbf)
            .args(["--elevation-json"])
            .arg(&profiles)
            .args(["--output"])
            .arg(output.join(format!("full-{i}.json")))
            .stdout(log.try_clone().unwrap())
            .stderr(log)
            .status()
            .unwrap();
        assert!(
            status.success(),
            "full compile {i} failed; see its local log"
        );
    }
    let first = fs::read(output.join("full-1.json")).unwrap();
    assert!(
        first == fs::read(output.join("full-2.json")).unwrap(),
        "same local inputs must produce identical bytes"
    );
    let report: Value = serde_json::from_slice(&first).unwrap();
    let base: Value = serde_json::from_slice(&fs::read(baseline).unwrap()).unwrap();
    let old: BTreeMap<_, _> = base["candidates"]
        .as_array()
        .unwrap()
        .iter()
        .map(|c| (c["candidate_fingerprint"].as_str().unwrap(), c))
        .collect();
    let candidates = report["candidates"].as_array().unwrap();
    assert_eq!(candidates.len(), 2051);
    assert_eq!(report["ratified_boundaries"]["mode"], "finish_rule_review");
    let mut moved = 0;
    let mut admitted = 0;
    let mut unresolved = 0;
    let mut new_moves = BTreeSet::new();
    let mut minimum_rejections = BTreeSet::new();
    let mut amended = BTreeSet::new();
    let mut crest_count = 0;
    for c in candidates {
        let rule = &c["provenance"]["finish_gate_rule"];
        let fp = lineage(c);
        let before = old
            .get(fp)
            .expect("every candidate retains its baseline lineage");
        assert_eq!(c["gate_start_wkt"], before["gate_start_wkt"]);
        let crest = &c["provenance"]["ratified_boundary"]["finish_decision"];
        if crest.is_null() {
            let mut retained = (*crest_previous[fp]).clone();
            retained["compiler_version"] = c["compiler_version"].clone();
            assert_eq!(*c, retained, "non-Lafayette candidate changed beyond compiler version: {fp}");
        } else {
            crest_count += 1;
            assert_eq!(c["display_name"], "Lafayette Road");
            assert_eq!(crest["type"], "crest finish (founder-approved)");
            assert!(rule.is_null());
            assert!((c["length_m"].as_f64().unwrap() - 2244.4).abs() < 0.1);
            assert!((c["vert_m"].as_f64().unwrap() - 101.3).abs() < 0.15);
            assert_ne!(c["candidate_fingerprint"], before["candidate_fingerprint"]);
            assert_ne!(c["canonical_profile"], before["canonical_profile"]);
            assert!(c["legacy_candidate_fingerprints"].as_array().unwrap().contains(&before["candidate_fingerprint"]));
        }
        let amendment = &rule["stop_evidence_amendment"];
        let is_amended = matches!(
            c["display_name"].as_str(),
            Some("Wises Mill Road" | "Centennial Road")
        ) && rule["admission"] == "founder_admitted";
        for field in [
            "candidate_fingerprint",
            "centerline_wkt",
            "centerline_polyline",
            "gate_start_wkt",
            "gate_end_wkt",
            "corridor_wkt",
            "corridor_cells",
            "canonical_profile",
            "length_m",
            "vert_m",
            "avg_gradient_pct",
            "max_gradient_pct",
        ] {
            if (crest.is_null() && !is_amended) || field == "gate_start_wkt" {
                assert_eq!(
                    c[field], previous[fp][field],
                    "unexpected round 3 change: {fp}/{field}"
                );
            }
        }
        if is_amended {
            amended.insert(c["display_name"].as_str().unwrap());
            assert_eq!(amendment["approval_quote"], "yes shift both back");
            assert!(rule["observed_stop_clearance_m"].as_f64().unwrap() >= 15.0 - 1e-6);
            assert_ne!(
                c["candidate_fingerprint"],
                previous[fp]["candidate_fingerprint"]
            );
            assert_ne!(c["canonical_profile"], previous[fp]["canonical_profile"]);
            assert!(c["length_m"].as_f64().unwrap() < previous[fp]["length_m"].as_f64().unwrap());
        } else {
            assert!(amendment.is_null());
        }
        if !rule.is_null() {
            moved += 1;
            match rule["admission"].as_str().unwrap() {
                "founder_admitted" => {
                    admitted += 1;
                    assert_eq!(
                        rule["founder_approval"]["quote"],
                        if is_amended {
                            "yes shift both back"
                        } else {
                            "yes all 15"
                        }
                    );
                    assert_eq!(
                        rule["founder_approval"]["authority"],
                        "history/codex-reports-2026-10-20/gate-rule/APPROVALS.json"
                    );
                    for field in [
                        "candidate_fingerprint",
                        "centerline_wkt",
                        "centerline_polyline",
                        "gate_start_wkt",
                        "gate_end_wkt",
                        "corridor_wkt",
                        "corridor_cells",
                        "canonical_profile",
                        "length_m",
                        "vert_m",
                        "avg_gradient_pct",
                        "max_gradient_pct",
                    ] {
                        if !is_amended {
                            assert_eq!(
                                c[field], reviewed[fp][field],
                                "approved geometry changed: {fp}/{field}"
                            );
                        }
                    }
                }
                "proposed by rule, not admitted" => assert!(rule["founder_approval"].is_null()),
                other => panic!("unknown admission {other}"),
            }
            assert!(c["length_m"].as_f64().unwrap() >= 90.0);
            assert!(c["vert_m"].as_f64().unwrap() >= 8.0);
            if reviewed[fp]["provenance"]["finish_gate_rule"].is_null() {
                if c["display_name"] == "Lynnebrook Lane" {
                    assert!(c["provenance"]["finish_rule_unresolved"].is_null());
                } else {
                    new_moves.insert(fp);
                }
            }
        }
        if !c["provenance"]["finish_rule_unresolved"].is_null() {
            unresolved += 1;
            assert_eq!(c["centerline_wkt"], before["centerline_wkt"]);
            assert!(c["provenance"]["finish_rule_unresolved"]["reason"]
                .as_str()
                .unwrap()
                .contains(c["display_name"].as_str().unwrap()));
            if c["provenance"]["finish_rule_unresolved"]["reason"]
                .as_str()
                .unwrap()
                .contains("below minimums")
            {
                minimum_rejections.insert(fp);
            }
        }
        if matches!(
            c["display_name"].as_str(),
            Some("Biddlewoods Road" | "Falls Road / Neill Drive")
        ) {
            assert_eq!(c["centerline_wkt"], before["centerline_wkt"]);
            assert_eq!(c["gate_end_wkt"], before["gate_end_wkt"]);
        }
        if c["display_name"] == "Calumet Street / West Coulter Street" {
            assert_eq!(c["max_gradient_pct"], 54.775);
        }
        if fp == "6e4b229028375d1257a3df2b5ab9c8e863bf297d4c7810e32ed0367d90aad442" {
            assert!(!rule.is_null(), "Rising Sun must be adjusted");
            let finish = c["length_m"].as_f64().unwrap();
            for control in rule["controls"].as_array().unwrap() {
                assert!(control["along_m"].as_f64().unwrap() - finish >= 14.98);
            }
        }
    }
    assert_eq!(
        amended,
        BTreeSet::from(["Wises Mill Road", "Centennial Road"])
    );
    assert_eq!(admitted, 15);
    assert_eq!(crest_count, 1);
    assert_eq!(new_moves, span_additions);
    assert_eq!(minimum_rejections, below_minimums);
    assert_eq!(unresolved, 33);
    assert!(moved > admitted);
    // The retained 57-climb CLI path must apply the same tracked crest decision
    // as a fresh full compile, while preserving every other reviewed candidate.
    for i in 1..=2 {
        let log = fs::File::create(output.join(format!("offline-{i}.log"))).unwrap();
        let status = Command::new(env!("CARGO_BIN_EXE_canon-compile"))
            .arg("--pbf").arg(&pbf).arg("--finish-gates-input").arg(path("CANON_TEST_RETAINED"))
            .arg("--output").arg(output.join(format!("offline-{i}.json")))
            .stdout(log.try_clone().unwrap()).stderr(log).status().unwrap();
        assert!(status.success(), "offline compile {i} failed");
    }
    let offline = fs::read(output.join("offline-1.json")).unwrap();
    assert_eq!(offline, fs::read(output.join("offline-2.json")).unwrap());
    let offline: Value = serde_json::from_slice(&offline).unwrap();
    assert_eq!(offline["candidates"].as_array().unwrap().len(), 57);
    assert_eq!(offline["ratified_boundaries"]["mode"], "finish_rule_review");
    for c in offline["candidates"].as_array().unwrap() {
        let full = candidates.iter().find(|f| lineage(f) == lineage(c)).unwrap();
        let mut expected = full.clone();
        expected["compiler_version"] = c["compiler_version"].clone();
        assert_eq!(*c, expected, "offline/full disagreement for {}", c["display_name"]);
    }
    println!("Full compile: {} candidates; {moved} moved ({admitted} admitted), {unresolved} unresolved; byte-identical.",
        candidates.len());
}
