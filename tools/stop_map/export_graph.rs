// Research adapter. The two readers below are the unmodified compiler readers.
// This binary never opens rider data. Its outputs contain public OSM data only.
use std::{env, fs::File, io::{BufWriter, Write}, path::Path};
use workout_parse::{canon::{CanonCandidate, finish_gates::read_finish_control_graph},
    geo_features::{osm::{OsmParser, OsmParserConfig}, roads::RoadClass}};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = env::args().collect();
    assert_eq!(args.len(), 4, "usage: export-graph PBF CANDIDATES_JSON OUTPUT_DIRECTORY");
    let out = Path::new(&args[3]);
    std::fs::create_dir_all(out)?;
    let mut config = OsmParserConfig::default();
    config.min_length_m = 0.0;
    config.include_classes.insert(RoadClass::Service);
    let roads = OsmParser::with_config(config).extract_roads(&args[1])?;
    let mut writer = BufWriter::new(File::create(out.join("roads.json"))?);
    writer.write_all(b"[")?;
    for (i, r) in roads.iter().enumerate() {
        if i > 0 { writer.write_all(b",")?; }
        serde_json::to_writer(&mut writer, &serde_json::json!({
            "osm_way_id": r.osm_way_id, "geometry": r.geometry,
            "osm_node_ids": r.osm_node_ids, "road_class": format!("{:?}", r.road_class),
            "name": r.name, "length_m": r.length_m
        }))?;
    }
    writer.write_all(b"]\n")?;
    writer.flush()?;
    let value: serde_json::Value = serde_json::from_reader(File::open(&args[2])?)?;
    let mut candidate: CanonCandidate = serde_json::from_value(value["candidates"][0].clone())?;
    candidate.osm_way_refs = roads.iter().map(|r| r.osm_way_id).collect();
    eprintln!("Exported {} compiler roads; reading compiler control graph", roads.len());
    drop(roads);
    let graph = read_finish_control_graph(Path::new(&args[1]), &[candidate])?;
    // This graph has a public Debug implementation but no public accessors or
    // Serialize. Decode only this pinned schema; fail if its syntax changes.
    let mut writer = BufWriter::new(File::create(out.join("controls.debug"))?);
    writeln!(writer, "{:?}", graph)?;
    Ok(())
}
