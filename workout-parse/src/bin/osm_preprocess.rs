//! OSM preprocessing CLI for Boulder Rollers.
//!
//! Extracts road features from OSM PBF files and outputs JSON
//! for loading into the database.
//!
//! Usage:
//!   osm-preprocess --input philadelphia.osm.pbf --output roads.json
//!   osm-preprocess --input philadelphia.osm.pbf --output roads.json --named-only

use std::fs::File;
use std::io::{BufWriter, Write};
use std::path::PathBuf;

use clap::Parser;
use serde::Serialize;

use workout_parse::geo_features::{OsmParser, OsmParserConfig, PreprocessedRoads, RoadClass};

#[derive(Parser, Debug)]
#[command(name = "osm-preprocess")]
#[command(about = "Extract road features from OSM PBF files for Boulder Rollers")]
#[command(version)]
struct Args {
    /// Input OSM PBF file path
    #[arg(short, long)]
    input: PathBuf,

    /// Output JSON file path
    #[arg(short, long)]
    output: PathBuf,

    /// Only include roads with names
    #[arg(long, default_value = "false")]
    named_only: bool,

    /// Only include roads with grade information
    #[arg(long, default_value = "false")]
    grade_only: bool,

    /// Minimum road length in meters
    #[arg(long, default_value = "50")]
    min_length: f32,

    /// H3 resolution (0-15, default 10 for ~50m hexagons)
    #[arg(long, default_value = "10")]
    h3_resolution: u8,

    /// Output tile mappings separately (for quick loading)
    #[arg(long)]
    tile_output: Option<PathBuf>,

    /// Pretty print JSON output
    #[arg(long, default_value = "false")]
    pretty: bool,
}

/// Serializable road feature for JSON output.
#[derive(Serialize)]
struct RoadJson {
    osm_way_id: i64,
    name: Option<String>,
    road_class: String,
    grade: Option<f32>,
    length_m: f32,
    geometry: Vec<[f64; 2]>, // [[lon, lat], ...]
    h3_cells: Vec<String>,
    has_bike_infra: bool,
    surface: Option<String>,
}

/// Serializable tile mapping for JSON output.
#[derive(Serialize)]
struct TileMappingJson {
    tile_id: String,
    road_names: Vec<String>,
}

/// Output stats summary.
#[derive(Serialize)]
struct OutputStats {
    total_roads: usize,
    named_roads: usize,
    roads_with_grade: usize,
    total_tiles: usize,
    avg_tiles_per_road: f32,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Args::parse();

    // Validate H3 resolution
    if args.h3_resolution > 15 {
        eprintln!("Error: H3 resolution must be 0-15");
        std::process::exit(1);
    }

    let resolution = match args.h3_resolution {
        0 => h3o::Resolution::Zero,
        1 => h3o::Resolution::One,
        2 => h3o::Resolution::Two,
        3 => h3o::Resolution::Three,
        4 => h3o::Resolution::Four,
        5 => h3o::Resolution::Five,
        6 => h3o::Resolution::Six,
        7 => h3o::Resolution::Seven,
        8 => h3o::Resolution::Eight,
        9 => h3o::Resolution::Nine,
        10 => h3o::Resolution::Ten,
        11 => h3o::Resolution::Eleven,
        12 => h3o::Resolution::Twelve,
        13 => h3o::Resolution::Thirteen,
        14 => h3o::Resolution::Fourteen,
        15 => h3o::Resolution::Fifteen,
        _ => unreachable!(),
    };

    // Build parser config
    let mut include_classes = std::collections::HashSet::new();
    include_classes.insert(RoadClass::Primary);
    include_classes.insert(RoadClass::Secondary);
    include_classes.insert(RoadClass::Tertiary);
    include_classes.insert(RoadClass::Residential);
    include_classes.insert(RoadClass::Unclassified);
    include_classes.insert(RoadClass::Cycleway);
    include_classes.insert(RoadClass::Path);
    include_classes.insert(RoadClass::Track);

    let config = OsmParserConfig {
        h3_resolution: resolution,
        min_length_m: args.min_length,
        require_name: args.named_only,
        require_grade: args.grade_only,
        include_classes,
    };

    eprintln!("OSM Preprocessor for Boulder Rollers");
    eprintln!("=====================================");
    eprintln!("Input:  {}", args.input.display());
    eprintln!("Output: {}", args.output.display());
    eprintln!(
        "H3 Resolution: {} (~{}m hexagons)",
        args.h3_resolution,
        h3_resolution_to_meters(args.h3_resolution)
    );
    eprintln!("Min Length: {}m", args.min_length);
    eprintln!("Named Only: {}", args.named_only);
    eprintln!("Grade Only: {}", args.grade_only);
    eprintln!();

    // Parse OSM file
    let parser = OsmParser::with_config(config);
    let roads = parser.extract_roads(&args.input)?;

    // Build preprocessed data
    let preprocessed = PreprocessedRoads::from_roads(roads);

    // Print stats
    eprintln!();
    eprintln!("Results:");
    eprintln!("  Total roads:       {}", preprocessed.stats.total_roads);
    eprintln!("  Named roads:       {}", preprocessed.stats.named_roads);
    eprintln!(
        "  Roads with grade:  {}",
        preprocessed.stats.roads_with_grade
    );
    eprintln!("  Total tiles:       {}", preprocessed.stats.total_tiles);
    eprintln!(
        "  Avg tiles/road:    {:.1}",
        preprocessed.stats.avg_tiles_per_road
    );

    // Convert to JSON format
    let roads_json: Vec<RoadJson> = preprocessed
        .roads
        .iter()
        .map(|r| RoadJson {
            osm_way_id: r.osm_way_id,
            name: r.name.clone(),
            road_class: format!("{:?}", r.road_class),
            grade: r.grade,
            length_m: r.length_m,
            geometry: r.geometry.iter().map(|&(lon, lat)| [lon, lat]).collect(),
            h3_cells: r.h3_cells.iter().cloned().collect(),
            has_bike_infra: r.has_bike_infra,
            surface: r.surface.clone(),
        })
        .collect();

    // Write roads JSON
    eprintln!();
    eprintln!("Writing roads to {}...", args.output.display());
    let file = File::create(&args.output)?;
    let mut writer = BufWriter::new(file);

    if args.pretty {
        serde_json::to_writer_pretty(&mut writer, &roads_json)?;
    } else {
        serde_json::to_writer(&mut writer, &roads_json)?;
    }
    writer.flush()?;

    // Optionally write tile mappings
    if let Some(tile_path) = args.tile_output {
        eprintln!("Writing tile mappings to {}...", tile_path.display());

        let tile_mappings: Vec<TileMappingJson> = preprocessed
            .tile_to_roads
            .iter()
            .map(|(tile_id, names)| TileMappingJson {
                tile_id: tile_id.clone(),
                road_names: names.clone(),
            })
            .collect();

        let file = File::create(&tile_path)?;
        let mut writer = BufWriter::new(file);

        if args.pretty {
            serde_json::to_writer_pretty(&mut writer, &tile_mappings)?;
        } else {
            serde_json::to_writer(&mut writer, &tile_mappings)?;
        }
        writer.flush()?;
    }

    eprintln!();
    eprintln!("Done!");

    Ok(())
}

/// Approximate edge length in meters for H3 resolution.
fn h3_resolution_to_meters(res: u8) -> u32 {
    match res {
        0 => 1107_000,
        1 => 418_000,
        2 => 158_000,
        3 => 59_000,
        4 => 22_000,
        5 => 8_000,
        6 => 3_000,
        7 => 1_200,
        8 => 460,
        9 => 174,
        10 => 66,
        11 => 25,
        12 => 9,
        13 => 3,
        14 => 1,
        15 => 0,
        _ => 0,
    }
}
