//! Canon compiler CLI.
//!
//! Runs offline over an OSM PBF and a local elevation profile export. The
//! elevation input is expected to have been produced from local 3DEP tiles or an
//! equivalent local DEM workflow; this binary never calls public elevation APIs.

use std::collections::HashMap;
use std::fs::File;
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};

use clap::Parser;
use workout_parse::canon::finish_gates::{apply_finish_gate_rule, read_finish_control_graph};
use workout_parse::canon::{
    apply_capture_tolerance_overrides, apply_ratified_boundary_decisions, candidate_insert_sql,
    capture_tolerance_overrides_from_json, compile_canon_candidates, launch_canon_osm_config,
    local_profiles_from_json, ratified_boundary_decisions_from_json, CanonCompileConfig,
    CanonCompileReport, LocalElevationProfile, RatifiedBoundaryDecisionSet,
    RatifiedBoundaryResourceDigest, RatifiedBoundaryRunMetadata, CANON_COMPILER_VERSION,
};
use workout_parse::geo_features::OsmParser;

const PHILLY_RATIFIED_BOUNDARIES_V1: &str =
    include_str!("../../resources/philly_ratified_boundaries_v1.json");
const PHILLY_RATIFIED_BOUNDARY_PROFILES_V1: &str =
    include_str!("../../resources/philly_ratified_boundary_3dep_profiles_v1.json");
const PHILLY_CAPTURE_TOLERANCE_OVERRIDES_V1: &str =
    include_str!("../../resources/philly_capture_tolerance_overrides_v1.json");

#[derive(Debug)]
struct LoadedBoundaryDecisions {
    decisions: RatifiedBoundaryDecisionSet,
    resource: RatifiedBoundaryResourceDigest,
}

#[derive(Parser, Debug)]
#[command(name = "canon-compile")]
#[command(about = "Compile climb canon candidates from OSM PBF + local DEM profiles")]
#[command(version = CANON_COMPILER_VERSION)]
struct Args {
    /// Input OSM PBF file path.
    #[arg(long)]
    pbf: PathBuf,

    /// Local elevation profile JSON keyed by OSM way id.
    #[arg(long, required_unless_present = "finish_gates_input")]
    elevation_json: Option<PathBuf>,

    /// Apply finish controls and tracked crest decisions to a retained compiler
    /// report. Local review output only; never ratification or publication.
    #[arg(long, conflicts_with_all = ["elevation_json", "sql_output",
        "ratified_boundary_decisions", "ratified_boundary_elevation_json",
        "skip_ratified_boundaries", "max_candidates"])]
    finish_gates_input: Option<PathBuf>,

    /// Output JSON report path.
    #[arg(short, long)]
    output: PathBuf,

    /// Optional SQL file with canon_climbs upserts for the emitted candidates.
    #[arg(long, conflicts_with = "skip_ratified_boundaries")]
    sql_output: Option<PathBuf>,

    /// DEM source label recorded on candidates.
    #[arg(long, default_value = "USGS 3DEP 10m local profile export")]
    dem_source: String,

    /// OSM extract timestamp recorded on candidates, e.g. 2026-07-05T00:00:00Z.
    #[arg(long)]
    odbl_extract_at: Option<String>,

    /// Minimum road length to retain during OSM extraction.
    #[arg(long, default_value = "50")]
    min_road_length_m: f32,

    /// Minimum candidate vertical gain.
    #[arg(long, default_value = "8")]
    min_vert_m: f64,

    /// Minimum candidate length.
    #[arg(long, default_value = "90")]
    min_candidate_length_m: f64,

    /// Limit emitted candidates after scoring, highest worthiness first.
    #[arg(long)]
    max_candidates: Option<usize>,

    /// Override the embedded Philadelphia ratified-boundary decision file.
    #[arg(long, conflicts_with = "skip_ratified_boundaries")]
    ratified_boundary_decisions: Option<PathBuf>,

    /// Supplemental local DEM profiles for short ways used only by ratified boundaries.
    #[arg(long)]
    ratified_boundary_elevation_json: Option<PathBuf>,

    /// Diagnostic-only generic compile without the launch boundary registry.
    #[arg(long, default_value = "false")]
    skip_ratified_boundaries: bool,

    /// Pretty print JSON output.
    #[arg(long, default_value = "false")]
    pretty: bool,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Args::parse();
    if let Some(input) = &args.finish_gates_input {
        let mut report: serde_json::Value =
            serde_json::from_reader(BufReader::new(File::open(input)?))?;
        let mut candidates: Vec<workout_parse::canon::CanonCandidate> = serde_json::from_value(
            report
                .get("candidates")
                .ok_or("input has no candidates")?
                .clone(),
        )?;
        let mut boundaries = ratified_boundary_decisions_from_json(serde_json::from_str(
            PHILLY_RATIFIED_BOUNDARIES_V1,
        )?)?;
        boundaries.decisions.retain(|d| {
            d.finish_decision.is_some()
                && candidates.iter().any(|c| {
                    c.candidate_fingerprint == d.replaces_candidate_fingerprint
                        || c.display_name == d.display_name
                })
        });
        if !boundaries.decisions.is_empty() {
            let roads = OsmParser::with_config(launch_canon_osm_config(0.0))
                .extract_roads(&args.pbf)?;
            let profiles = local_profiles_from_json(serde_json::from_str(
                PHILLY_RATIFIED_BOUNDARY_PROFILES_V1,
            )?)?;
            let mut retained =
                compile_canon_candidates(&[], &HashMap::new(), &CanonCompileConfig::default());
            retained.candidates = candidates;
            candidates = apply_ratified_boundary_decisions(
                retained,
                &roads,
                &profiles,
                &boundaries,
                &CanonCompileConfig::default(),
            )?
            .candidates;
            report["crest_boundary_run"] = serde_json::json!({
                "decisions": resource_digest("embedded:philly_ratified_boundaries_v1.json", PHILLY_RATIFIED_BOUNDARIES_V1.as_bytes()),
                "profiles": resource_digest("embedded:philly_ratified_boundary_3dep_profiles_v1.json", PHILLY_RATIFIED_BOUNDARY_PROFILES_V1.as_bytes()),
                "applied_decisions": boundaries.decisions.len(),
            });
        }
        let graph = read_finish_control_graph(&args.pbf, &candidates)?;
        apply_finish_gate_rule(&mut candidates, &graph)?;
        report["candidates"] = serde_json::to_value(&candidates)?;
        report["compiler_version"] = serde_json::json!(CANON_COMPILER_VERSION);
        report["ratified_boundaries"]["mode"] = serde_json::json!("finish_rule_review");
        report["finish_gate_run"] = serde_json::json!({
            "mode": "offline_retained_candidates",
            "input_report": file_resource_digest(input)?,
            "road_graph": file_resource_digest(&args.pbf)?,
        });
        let mut writer = BufWriter::new(File::create(&args.output)?);
        serde_json::to_writer_pretty(&mut writer, &report)?;
        writer.flush()?;
        return Ok(());
    }
    let elevation_json = args
        .elevation_json
        .as_ref()
        .ok_or("local elevation JSON is required")?;

    if !elevation_json.exists() {
        return Err(format!(
            "local elevation profile JSON not found: {}",
            elevation_json.display()
        )
        .into());
    }

    let boundary_decisions = load_ratified_boundary_decisions(&args)?;
    let config = launch_canon_osm_config(args.min_road_length_m);
    let parser = OsmParser::with_config(config);
    eprintln!("Canon compiler {CANON_COMPILER_VERSION}");
    eprintln!("PBF:            {}", args.pbf.display());
    eprintln!("Elevation JSON: {}", elevation_json.display());
    eprintln!("DEM source:     {}", args.dem_source);
    if let Some(loaded) = &boundary_decisions {
        eprintln!("Ratified gates: {}", loaded.decisions.decisions.len());
    } else {
        eprintln!("Ratified gates: skipped (diagnostic mode)");
    }
    eprintln!();

    let roads = parser.extract_roads(&args.pbf)?;

    let elevation_file = File::open(elevation_json)?;
    let elevation_value = serde_json::from_reader(BufReader::new(elevation_file))?;
    let profiles = local_profiles_from_json(elevation_value)?;

    let compile_config = CanonCompileConfig {
        min_vert_m: args.min_vert_m,
        min_length_m: args.min_candidate_length_m,
        dem_source: args.dem_source,
        odbl_extract_at: args.odbl_extract_at,
        ..CanonCompileConfig::default()
    };
    let mut report = compile_canon_candidates(&roads, &profiles, &compile_config);
    drop(roads);

    if let Some(loaded) = &boundary_decisions {
        let mut boundary_profiles = profiles;
        let embedded_value = serde_json::from_str(PHILLY_RATIFIED_BOUNDARY_PROFILES_V1)?;
        let embedded_profiles = local_profiles_from_json(embedded_value)?;
        let embedded_merge = merge_boundary_profiles(&mut boundary_profiles, embedded_profiles);
        let mut base_profile_resource = file_resource_digest(elevation_json)?;
        base_profile_resource.source = format!("base:{}", elevation_json.display());
        let mut profile_bundles = vec![
            base_profile_resource,
            resource_digest(
                "embedded:philly_ratified_boundary_3dep_profiles_v1.json",
                PHILLY_RATIFIED_BOUNDARY_PROFILES_V1.as_bytes(),
            ),
        ];
        let mut custom_merge = ProfileMergeStats {
            added: 0,
            replaced: 0,
        };
        eprintln!(
            "Boundary profiles: {} embedded ways added, {} generic ways replaced",
            embedded_merge.added, embedded_merge.replaced
        );
        if let Some(path) = &args.ratified_boundary_elevation_json {
            let bytes = std::fs::read(path)?;
            let value = serde_json::from_slice(&bytes)?;
            let supplemental = local_profiles_from_json(value)?;
            custom_merge = merge_boundary_profiles(&mut boundary_profiles, supplemental);
            profile_bundles.push(resource_digest(
                format!("custom:{}", path.display()),
                &bytes,
            ));
            eprintln!(
                "Boundary profiles: {} custom ways added, {} embedded/generic ways replaced",
                custom_merge.added, custom_merge.replaced
            );
        }

        eprintln!("Loading short OSM ways for ratified boundaries...");
        let boundary_parser = OsmParser::with_config(launch_canon_osm_config(0.0));
        let boundary_roads = boundary_parser.extract_roads(&args.pbf)?;
        report = apply_ratified_boundary_decisions(
            report,
            &boundary_roads,
            &boundary_profiles,
            &loaded.decisions,
            &compile_config,
        )?;
        report.stats.profiles_loaded = boundary_profiles.len();
        report.ratified_boundaries = Some(RatifiedBoundaryRunMetadata {
            mode: "applied".to_string(),
            model: Some(loaded.decisions.model.clone()),
            registry: Some(loaded.resource.clone()),
            road_graph: Some(file_resource_digest(&args.pbf)?),
            profile_bundles,
            applied_decisions: loaded.decisions.decisions.len(),
            retained_decisions: loaded.decisions.decisions.len(),
            embedded_profiles_added: embedded_merge.added,
            embedded_profiles_replaced: embedded_merge.replaced,
            custom_profiles_added: custom_merge.added,
            custom_profiles_replaced: custom_merge.replaced,
        });
        let capture_overrides = capture_tolerance_overrides_from_json(serde_json::from_str(
            PHILLY_CAPTURE_TOLERANCE_OVERRIDES_V1,
        )?)?;
        let capture_resource = resource_digest(
            "embedded:philly_capture_tolerance_overrides_v1.json",
            PHILLY_CAPTURE_TOLERANCE_OVERRIDES_V1.as_bytes(),
        );
        report = apply_capture_tolerance_overrides(report, &capture_overrides, &capture_resource)?;
        eprintln!(
            "Capture tolerance revisions: {}",
            capture_overrides.overrides.len()
        );
    } else {
        let mut base_profile_resource = file_resource_digest(elevation_json)?;
        base_profile_resource.source = format!("base:{}", elevation_json.display());
        report.ratified_boundaries = Some(RatifiedBoundaryRunMetadata {
            mode: "diagnostic_skip".to_string(),
            model: None,
            registry: None,
            road_graph: Some(file_resource_digest(&args.pbf)?),
            profile_bundles: vec![base_profile_resource],
            applied_decisions: 0,
            retained_decisions: 0,
            embedded_profiles_added: 0,
            embedded_profiles_replaced: 0,
            custom_profiles_added: 0,
            custom_profiles_replaced: 0,
        });
    }

    let graph = read_finish_control_graph(&args.pbf, &report.candidates)?;
    apply_finish_gate_rule(&mut report.candidates, &graph)?;
    if report.candidates.iter().any(|c| {
        c.provenance.get("finish_gate_rule").is_some()
            || c.provenance.get("finish_rule_unresolved").is_some()
            || c.provenance["ratified_boundary"]["publication_status"] == "review_only"
    }) {
        if let Some(metadata) = &mut report.ratified_boundaries {
            metadata.mode = "finish_rule_review".into();
        }
    }
    sort_and_limit_candidates(&mut report, args.max_candidates)?;

    eprintln!("Input roads:       {}", report.stats.input_roads);
    eprintln!("Profiles loaded:   {}", report.stats.profiles_loaded);
    eprintln!("Launch roads:      {}", report.stats.launch_scope_roads);
    eprintln!("Candidates:        {}", report.stats.emitted_candidates);
    eprintln!("Skipped roads:     {}", report.stats.skipped_roads);

    let output = File::create(&args.output)?;
    let mut writer = BufWriter::new(output);
    if args.pretty {
        serde_json::to_writer_pretty(&mut writer, &report)?;
    } else {
        serde_json::to_writer(&mut writer, &report)?;
    }
    writer.flush()?;

    if let Some(sql_output) = args.sql_output {
        write_sql_output(
            &report.candidates,
            report.ratified_boundaries.as_ref().map(|m| m.mode.as_str()),
            &sql_output,
        )?;
        eprintln!("SQL output:        {}", sql_output.display());
    }

    eprintln!("JSON output:       {}", args.output.display());

    Ok(())
}

fn write_sql_output(
    candidates: &[workout_parse::canon::CanonCandidate],
    mode: Option<&str>,
    path: &Path,
) -> Result<(), Box<dyn std::error::Error>> {
    if mode != Some("applied") {
        return Err(
            "SQL output requires an applied compiler run; finish proposals are review-only".into(),
        );
    }
    let file = File::create(path)?;
    let mut writer = BufWriter::new(file);
    for candidate in candidates {
        writeln!(writer, "{}", candidate_insert_sql(candidate))?;
    }
    writer.flush()?;
    Ok(())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct ProfileMergeStats {
    added: usize,
    replaced: usize,
}

fn merge_boundary_profiles(
    target: &mut HashMap<i64, LocalElevationProfile>,
    incoming: HashMap<i64, LocalElevationProfile>,
) -> ProfileMergeStats {
    let mut stats = ProfileMergeStats {
        added: 0,
        replaced: 0,
    };
    for (way_ref, profile) in incoming {
        if target.insert(way_ref, profile).is_some() {
            stats.replaced += 1;
        } else {
            stats.added += 1;
        }
    }
    stats
}

fn resource_digest(source: impl Into<String>, bytes: &[u8]) -> RatifiedBoundaryResourceDigest {
    RatifiedBoundaryResourceDigest {
        source: source.into(),
        blake3: blake3::hash(bytes).to_hex().to_string(),
    }
}

fn file_resource_digest(
    path: &Path,
) -> Result<RatifiedBoundaryResourceDigest, Box<dyn std::error::Error>> {
    let file = File::open(path)?;
    let mut reader = BufReader::new(file);
    let mut hasher = blake3::Hasher::new();
    let mut buffer = vec![0_u8; 1024 * 1024];
    loop {
        let count = reader.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        hasher.update(&buffer[..count]);
    }
    Ok(RatifiedBoundaryResourceDigest {
        source: path.display().to_string(),
        blake3: hasher.finalize().to_hex().to_string(),
    })
}

fn sort_and_limit_candidates(
    report: &mut CanonCompileReport,
    max_candidates: Option<usize>,
) -> Result<(), String> {
    report.candidates.sort_by(|a, b| {
        b.worthiness_score
            .partial_cmp(&a.worthiness_score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    if let Some(max_candidates) = max_candidates {
        let dropped_ratified = report
            .candidates
            .iter()
            .skip(max_candidates)
            .filter_map(|candidate| {
                candidate.provenance["ratified_boundary"]["decision_id"]
                    .as_str()
                    .map(str::to_string)
            })
            .collect::<Vec<_>>();
        if !dropped_ratified.is_empty() {
            return Err(format!(
                "--max-candidates {max_candidates} would remove ratified boundaries: {}",
                dropped_ratified.join(", ")
            ));
        }

        let dropped_capture_revisions = report
            .candidates
            .iter()
            .skip(max_candidates)
            .filter_map(|candidate| {
                candidate.provenance["capture_tolerance_revision"]["revision_id"]
                    .as_str()
                    .map(str::to_string)
            })
            .collect::<Vec<_>>();
        if !dropped_capture_revisions.is_empty() {
            return Err(format!(
                "--max-candidates {max_candidates} would remove capture tolerance revisions: {}",
                dropped_capture_revisions.join(", ")
            ));
        }

        report.candidates.truncate(max_candidates);
        report.stats.emitted_candidates = report.candidates.len();
    }

    if let Some(metadata) = &mut report.ratified_boundaries {
        metadata.retained_decisions = report
            .candidates
            .iter()
            .filter(|candidate| candidate.provenance["ratified_boundary"].is_object())
            .count();
    }
    if let Some(metadata) = &mut report.capture_tolerance_overrides {
        metadata.retained = report
            .candidates
            .iter()
            .filter(|candidate| {
                candidate.provenance["capture_tolerance_revision"]["revision_id"].is_string()
            })
            .count();
    }
    Ok(())
}

fn load_ratified_boundary_decisions(
    args: &Args,
) -> Result<Option<LoadedBoundaryDecisions>, Box<dyn std::error::Error>> {
    if args.skip_ratified_boundaries {
        if args.ratified_boundary_elevation_json.is_some() {
            return Err(
                "--ratified-boundary-elevation-json cannot be used with --skip-ratified-boundaries"
                    .into(),
            );
        }
        return Ok(None);
    }

    let (value, resource) = if let Some(path) = &args.ratified_boundary_decisions {
        let bytes = std::fs::read(path)?;
        (
            serde_json::from_slice(&bytes)?,
            resource_digest(format!("custom:{}", path.display()), &bytes),
        )
    } else {
        (
            serde_json::from_str(PHILLY_RATIFIED_BOUNDARIES_V1)?,
            resource_digest(
                "embedded:philly_ratified_boundaries_v1.json",
                PHILLY_RATIFIED_BOUNDARIES_V1.as_bytes(),
            ),
        )
    };
    Ok(Some(LoadedBoundaryDecisions {
        decisions: ratified_boundary_decisions_from_json(value)?,
        resource,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn embedded_boundary_resources_cover_every_ratified_way() {
        let decision_value = serde_json::from_str(PHILLY_RATIFIED_BOUNDARIES_V1).unwrap();
        let decisions = ratified_boundary_decisions_from_json(decision_value).unwrap();
        let profile_value = serde_json::from_str(PHILLY_RATIFIED_BOUNDARY_PROFILES_V1).unwrap();
        let profiles = local_profiles_from_json(profile_value).unwrap();

        assert_eq!(decisions.decisions.len(), 16);
        assert_eq!(profiles.len(), 65);
        for decision in decisions.decisions {
            for way_ref in decision.osm_way_refs {
                assert!(
                    profiles.contains_key(&way_ref),
                    "{} is missing the local DEM profile for OSM way {}",
                    decision.decision_id,
                    way_ref
                );
            }
        }
    }

    #[test]
    fn embedded_capture_tolerance_registry_is_the_four_ratified_candidates() {
        let overrides = capture_tolerance_overrides_from_json(
            serde_json::from_str(PHILLY_CAPTURE_TOLERANCE_OVERRIDES_V1).unwrap(),
        )
        .unwrap();
        assert_eq!(overrides.overrides.len(), 4);
        assert_eq!(
            overrides
                .overrides
                .iter()
                .map(|entry| entry.display_name.as_str())
                .collect::<std::collections::BTreeSet<_>>(),
            std::collections::BTreeSet::from([
                "Black Rock Road",
                "Flat Rock Road",
                "Rose Glen Road",
                "Sprague Road",
            ])
        );
    }

    #[test]
    fn boundary_profile_precedence_is_custom_then_embedded_then_generic() {
        let mut profiles = HashMap::from([(1, test_profile(1, 10.0))]);
        let embedded = HashMap::from([(1, test_profile(1, 20.0)), (2, test_profile(2, 30.0))]);
        assert_eq!(
            merge_boundary_profiles(&mut profiles, embedded),
            ProfileMergeStats {
                added: 1,
                replaced: 1
            }
        );
        assert_eq!(profiles[&1].points[0].elev_m, 20.0);

        let custom = HashMap::from([(1, test_profile(1, 40.0))]);
        assert_eq!(
            merge_boundary_profiles(&mut profiles, custom),
            ProfileMergeStats {
                added: 0,
                replaced: 1
            }
        );
        assert_eq!(profiles[&1].points[0].elev_m, 40.0);
    }

    #[test]
    fn candidate_limit_fails_before_dropping_a_ratified_boundary() {
        let road = workout_parse::geo_features::RoadFeatureBuilder::new(1)
            .highway("residential")
            .name("Limit Test Hill")
            .geometry(vec![(-75.0, 40.0), (-75.0, 40.002)])
            .build()
            .unwrap();
        let profiles = HashMap::from([(
            1,
            LocalElevationProfile {
                osm_way_id: 1,
                points: vec![
                    workout_parse::canon::CanonProfilePoint {
                        dist_m: 0.0,
                        lat: 40.0,
                        lon: -75.0,
                        elev_m: 10.0,
                    },
                    workout_parse::canon::CanonProfilePoint {
                        dist_m: 0.0,
                        lat: 40.002,
                        lon: -75.0,
                        elev_m: 40.0,
                    },
                ],
            },
        )]);
        let mut report =
            compile_canon_candidates(&[road], &profiles, &CanonCompileConfig::default());
        assert_eq!(report.candidates.len(), 1);
        let mut ordinary = report.candidates[0].clone();
        ordinary.candidate_fingerprint = "3".repeat(64);
        ordinary.worthiness_score = 100.0;
        let mut ratified = report.candidates[0].clone();
        ratified.candidate_fingerprint = "4".repeat(64);
        ratified.worthiness_score = 1.0;
        ratified.provenance = serde_json::json!({
            "ratified_boundary": {"decision_id": "required-boundary"}
        });
        report.candidates = vec![ordinary, ratified];
        report.stats.emitted_candidates = 2;

        let error = sort_and_limit_candidates(&mut report, Some(1)).unwrap_err();

        assert!(error.contains("would remove ratified boundaries: required-boundary"));
        assert_eq!(report.candidates.len(), 2);
    }

    #[test]
    fn candidate_limit_fails_before_dropping_a_capture_revision() {
        let road = workout_parse::geo_features::RoadFeatureBuilder::new(2)
            .highway("residential")
            .name("Capture Limit Hill")
            .geometry(vec![(-75.0, 40.0), (-75.0, 40.002)])
            .build()
            .unwrap();
        let profiles = HashMap::from([(
            2,
            LocalElevationProfile {
                osm_way_id: 2,
                points: vec![
                    workout_parse::canon::CanonProfilePoint {
                        dist_m: 0.0,
                        lat: 40.0,
                        lon: -75.0,
                        elev_m: 10.0,
                    },
                    workout_parse::canon::CanonProfilePoint {
                        dist_m: 0.0,
                        lat: 40.002,
                        lon: -75.0,
                        elev_m: 40.0,
                    },
                ],
            },
        )]);
        let mut report =
            compile_canon_candidates(&[road], &profiles, &CanonCompileConfig::default());
        let mut ordinary = report.candidates[0].clone();
        ordinary.candidate_fingerprint = "5".repeat(64);
        ordinary.worthiness_score = 100.0;
        let mut revised = report.candidates[0].clone();
        revised.candidate_fingerprint = "6".repeat(64);
        revised.worthiness_score = 1.0;
        revised.provenance["capture_tolerance_revision"] =
            serde_json::json!({"revision_id": "required-capture"});
        report.candidates = vec![ordinary, revised];
        report.stats.emitted_candidates = 2;

        let error = sort_and_limit_candidates(&mut report, Some(1)).unwrap_err();

        assert!(error.contains("would remove capture tolerance revisions: required-capture"));
        assert_eq!(report.candidates.len(), 2);
    }

    fn test_profile(osm_way_id: i64, elevation_m: f64) -> LocalElevationProfile {
        LocalElevationProfile {
            osm_way_id,
            points: vec![workout_parse::canon::CanonProfilePoint {
                dist_m: 0.0,
                lat: 40.0,
                lon: -75.0,
                elev_m: elevation_m,
            }],
        }
    }

    #[test]
    fn diagnostic_skip_mode_rejects_sql_output() {
        let error = Args::try_parse_from([
            "canon-compile",
            "--pbf",
            "roads.pbf",
            "--elevation-json",
            "profiles.json",
            "--output",
            "report.json",
            "--skip-ratified-boundaries",
            "--sql-output",
            "publish.sql",
        ])
        .unwrap_err();

        assert_eq!(error.kind(), clap::error::ErrorKind::ArgumentConflict);
    }

    #[test]
    fn review_report_refuses_sql_before_creating_or_truncating_file() {
        let path =
            std::env::temp_dir().join(format!("canon-review-refusal-{}.sql", std::process::id()));
        for mode in [Some("finish_rule_review"), Some("review_only"), None] {
            std::fs::write(&path, "existing local file").unwrap();
            let result = write_sql_output(&[], mode, &path);
            let contents = std::fs::read_to_string(&path).unwrap();
            std::fs::remove_file(&path).unwrap();
            assert!(result.is_err(), "review output emitted SQL: {mode:?}");
            assert_eq!(contents, "existing local file");
        }
        write_sql_output(&[], Some("applied"), &path).unwrap();
        std::fs::remove_file(path).unwrap();
    }
}
