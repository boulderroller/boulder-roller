//! Export local DEM-draped road profiles for the canon compiler.
//!
//! This binary consumes OSM-preprocessed road JSON plus locally downloaded
//! USGS 3DEP 1/3 arc-second GeoTIFFs. It does not call public elevation APIs.

use std::fs::File;
use std::io::{BufReader, BufWriter, Write};
use std::path::PathBuf;

use clap::Parser;
use serde::{Deserialize, Serialize};
use tiff::decoder::{Decoder, DecodingResult, Limits};
use tiff::tags::Tag;
use workout_parse::canon::{CanonProfilePoint, LocalElevationProfile};
use workout_parse::climb::utils::haversine_m;

#[derive(Parser, Debug)]
#[command(name = "canon-export-profiles")]
#[command(about = "Drape OSM road geometry over local 3DEP GeoTIFFs")]
#[command(version)]
struct Args {
    /// Road JSON from osm-preprocess, shaped as an array of road objects.
    #[arg(long)]
    roads_json: PathBuf,

    /// Local USGS 3DEP GeoTIFF. Repeat for adjacent 1x1 degree tiles.
    #[arg(long = "dem", required = true)]
    dem_paths: Vec<PathBuf>,

    /// Output elevation profile JSON path for canon-compile --elevation-json.
    #[arg(short, long)]
    output: PathBuf,

    /// Bounding box as min_lon,min_lat,max_lon,max_lat.
    #[arg(long, value_parser = parse_bbox)]
    bbox: BBox,

    /// Densified sample spacing in meters.
    #[arg(long, default_value = "10")]
    spacing_m: f64,

    /// Minimum road length to export.
    #[arg(long, default_value = "90")]
    min_road_length_m: f64,

    /// Limit exported profiles after filtering, longest roads first.
    #[arg(long)]
    max_roads: Option<usize>,

    /// Pretty print JSON output.
    #[arg(long, default_value = "false")]
    pretty: bool,
}

#[derive(Clone, Copy, Debug, Serialize)]
struct BBox {
    min_lon: f64,
    min_lat: f64,
    max_lon: f64,
    max_lat: f64,
}

#[derive(Debug, Deserialize)]
struct RoadJson {
    osm_way_id: i64,
    name: Option<String>,
    road_class: String,
    length_m: f64,
    #[serde(default)]
    geometry: Vec<[f64; 2]>,
}

#[derive(Debug, Serialize)]
struct ProfileExport {
    source: &'static str,
    dem_source: String,
    dem_registration: &'static str,
    spacing_m: f64,
    bbox: BBox,
    input_roads: usize,
    filtered_roads: usize,
    exported_profiles: usize,
    skipped_roads: Vec<SkippedRoad>,
    roads: Vec<LocalElevationProfile>,
}

#[derive(Debug, Serialize)]
struct SkippedRoad {
    osm_way_id: i64,
    name: Option<String>,
    reason: String,
}

#[derive(Debug)]
struct DemTile {
    path: PathBuf,
    width: usize,
    height: usize,
    scale_x: f64,
    scale_y: f64,
    tie_raster_x: f64,
    tie_raster_y: f64,
    tie_model_x: f64,
    tie_model_y: f64,
    registration: RasterRegistration,
    nodata: Option<f32>,
    values: Vec<f32>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum RasterRegistration {
    PixelIsArea,
    PixelIsPoint,
}

impl RasterRegistration {
    fn as_str(self) -> &'static str {
        match self {
            Self::PixelIsArea => "pixel_is_area_center_adjusted",
            Self::PixelIsPoint => "pixel_is_point",
        }
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Args::parse();
    if args.spacing_m <= 0.0 {
        return Err("spacing_m must be positive".into());
    }

    eprintln!("Canon 3DEP profile exporter");
    eprintln!("Roads: {}", args.roads_json.display());
    eprintln!("Output: {}", args.output.display());
    eprintln!("DEM tiles: {}", args.dem_paths.len());

    let mut dem_tiles = Vec::new();
    for path in &args.dem_paths {
        eprintln!("Loading DEM: {}", path.display());
        dem_tiles.push(DemTile::load(path.clone())?);
    }
    let dem_registration = dem_tiles[0].registration;
    if dem_tiles
        .iter()
        .any(|tile| tile.registration != dem_registration)
    {
        return Err("DEM tiles mix PixelIsArea and PixelIsPoint registration".into());
    }

    let road_file = File::open(&args.roads_json)?;
    let mut roads: Vec<RoadJson> = serde_json::from_reader(BufReader::new(road_file))?;
    let input_roads = roads.len();
    roads.retain(|road| {
        road.length_m >= args.min_road_length_m
            && road.geometry.len() >= 2
            && is_launch_scope_road(road)
            && road_bbox(&road.geometry)
                .map(|bbox| bbox.intersects(&args.bbox))
                .unwrap_or(false)
    });
    roads.sort_by(|a, b| {
        b.length_m
            .partial_cmp(&a.length_m)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    if let Some(max_roads) = args.max_roads {
        roads.truncate(max_roads);
    }

    let mut profiles = Vec::new();
    let mut skipped_roads = Vec::new();
    for road in &roads {
        match export_profile(road, &dem_tiles, args.spacing_m) {
            Some(profile) => profiles.push(profile),
            None => skipped_roads.push(SkippedRoad {
                osm_way_id: road.osm_way_id,
                name: road.name.clone(),
                reason: "missing_dem_sample_or_too_few_points".to_string(),
            }),
        }
    }

    let export = ProfileExport {
        source: "local_usgs_3dep_geotiff_profile_export",
        dem_source: dem_tiles
            .iter()
            .map(|tile| tile.path.file_name().unwrap_or_default().to_string_lossy())
            .collect::<Vec<_>>()
            .join(","),
        dem_registration: dem_registration.as_str(),
        spacing_m: args.spacing_m,
        bbox: args.bbox,
        input_roads,
        filtered_roads: roads.len(),
        exported_profiles: profiles.len(),
        skipped_roads,
        roads: profiles,
    };

    let output = File::create(&args.output)?;
    let mut writer = BufWriter::new(output);
    if args.pretty {
        serde_json::to_writer_pretty(&mut writer, &export)?;
    } else {
        serde_json::to_writer(&mut writer, &export)?;
    }
    writer.flush()?;

    eprintln!("Input roads:       {}", export.input_roads);
    eprintln!("Filtered roads:    {}", export.filtered_roads);
    eprintln!("Exported profiles: {}", export.exported_profiles);
    eprintln!("Skipped roads:     {}", export.skipped_roads.len());
    Ok(())
}

impl BBox {
    fn intersects(&self, other: &BBox) -> bool {
        self.min_lon <= other.max_lon
            && self.max_lon >= other.min_lon
            && self.min_lat <= other.max_lat
            && self.max_lat >= other.min_lat
    }
}

impl DemTile {
    fn load(path: PathBuf) -> Result<Self, Box<dyn std::error::Error>> {
        let file = File::open(&path)?;
        let mut decoder = Decoder::new(BufReader::new(file))?.with_limits(Limits::unlimited());
        let (width, height) = decoder.dimensions()?;
        let scale = decoder.get_tag_f64_vec(Tag::ModelPixelScaleTag)?;
        let tiepoint = decoder.get_tag_f64_vec(Tag::ModelTiepointTag)?;
        if scale.len() < 2 || tiepoint.len() < 6 {
            return Err(
                format!("DEM lacks GeoTIFF scale/tiepoint tags: {}", path.display()).into(),
            );
        }
        let nodata = decoder
            .get_tag_ascii_string(Tag::GdalNodata)
            .ok()
            .and_then(|value| value.trim().parse::<f32>().ok());
        let registration = match raster_registration_from_geokeys(
            decoder
                .get_tag_u16_vec(Tag::GeoKeyDirectoryTag)
                .ok()
                .as_deref(),
        ) {
            Ok(registration) => registration,
            Err(reason) => {
                return Err(format!(
                    "invalid GeoTIFF raster registration in {}: {}",
                    path.display(),
                    reason
                )
                .into())
            }
        };
        let values = match decoder.read_image()? {
            DecodingResult::F32(values) => values,
            DecodingResult::F64(values) => values.into_iter().map(|value| value as f32).collect(),
            DecodingResult::U16(values) => values.into_iter().map(|value| value as f32).collect(),
            DecodingResult::I16(values) => values.into_iter().map(|value| value as f32).collect(),
            other => {
                return Err(format!(
                    "unsupported DEM sample type in {}: {:?}",
                    path.display(),
                    other
                )
                .into())
            }
        };
        Ok(Self {
            path,
            width: width as usize,
            height: height as usize,
            scale_x: scale[0],
            scale_y: scale[1],
            tie_raster_x: tiepoint[0],
            tie_raster_y: tiepoint[1],
            tie_model_x: tiepoint[3],
            tie_model_y: tiepoint[4],
            registration,
            nodata,
            values,
        })
    }

    fn contains(&self, lon: f64, lat: f64) -> bool {
        let (x, y) = self.pixel_coords(lon, lat);
        x >= 0.0 && y >= 0.0 && x < (self.width - 1) as f64 && y < (self.height - 1) as f64
    }

    fn sample_bilinear(&self, lon: f64, lat: f64) -> Option<f64> {
        let (x, y) = self.pixel_coords(lon, lat);
        if x < 0.0 || y < 0.0 || x >= (self.width - 1) as f64 || y >= (self.height - 1) as f64 {
            return None;
        }
        let x0 = x.floor() as usize;
        let y0 = y.floor() as usize;
        let x1 = x0 + 1;
        let y1 = y0 + 1;
        let tx = x - x0 as f64;
        let ty = y - y0 as f64;
        let q00 = self.value(x0, y0)?;
        let q10 = self.value(x1, y0)?;
        let q01 = self.value(x0, y1)?;
        let q11 = self.value(x1, y1)?;
        let top = q00 * (1.0 - tx) + q10 * tx;
        let bottom = q01 * (1.0 - tx) + q11 * tx;
        Some(top * (1.0 - ty) + bottom * ty)
    }

    fn pixel_coords(&self, lon: f64, lat: f64) -> (f64, f64) {
        let (x, y) = (
            self.tie_raster_x + (lon - self.tie_model_x) / self.scale_x,
            self.tie_raster_y + (self.tie_model_y - lat) / self.scale_y,
        );
        match self.registration {
            RasterRegistration::PixelIsArea => (x - 0.5, y - 0.5),
            RasterRegistration::PixelIsPoint => (x, y),
        }
    }

    fn value(&self, x: usize, y: usize) -> Option<f64> {
        let value = *self.values.get(y.checked_mul(self.width)? + x)?;
        if !value.is_finite() {
            return None;
        }
        if self
            .nodata
            .map(|nodata| (value - nodata).abs() < f32::EPSILON)
            .unwrap_or(false)
        {
            return None;
        }
        Some(value as f64)
    }
}

fn raster_registration_from_geokeys(keys: Option<&[u16]>) -> Result<RasterRegistration, String> {
    const GT_RASTER_TYPE_GEO_KEY: u16 = 1025;
    const RASTER_PIXEL_IS_AREA: u16 = 1;
    const RASTER_PIXEL_IS_POINT: u16 = 2;

    let Some(keys) = keys else {
        return Ok(RasterRegistration::PixelIsArea);
    };
    if keys.len() < 4 {
        return Err("GeoKeyDirectoryTag is shorter than its header".to_string());
    }
    let key_count = usize::from(keys[3]);
    let expected_len = 4 + (key_count * 4);
    if keys.len() < expected_len {
        return Err("GeoKeyDirectoryTag is shorter than its declared key count".to_string());
    }

    for entry in keys[4..expected_len].chunks_exact(4) {
        if entry[0] != GT_RASTER_TYPE_GEO_KEY {
            continue;
        }
        if entry[1] != 0 || entry[2] != 1 {
            return Err("GTRasterTypeGeoKey must contain one inline value".to_string());
        }
        return match entry[3] {
            RASTER_PIXEL_IS_AREA => Ok(RasterRegistration::PixelIsArea),
            RASTER_PIXEL_IS_POINT => Ok(RasterRegistration::PixelIsPoint),
            value => Err(format!("unsupported GTRasterTypeGeoKey value {value}")),
        };
    }

    Ok(RasterRegistration::PixelIsArea)
}

fn parse_bbox(raw: &str) -> Result<BBox, String> {
    let values = raw
        .split(',')
        .map(|value| value.trim().parse::<f64>())
        .collect::<Result<Vec<_>, _>>()
        .map_err(|err| format!("invalid bbox number: {err}"))?;
    if values.len() != 4 {
        return Err("bbox must be min_lon,min_lat,max_lon,max_lat".to_string());
    }
    if values[0] >= values[2] || values[1] >= values[3] {
        return Err("bbox min values must be lower than max values".to_string());
    }
    Ok(BBox {
        min_lon: values[0],
        min_lat: values[1],
        max_lon: values[2],
        max_lat: values[3],
    })
}

fn is_launch_scope_road(road: &RoadJson) -> bool {
    let road_class = road.road_class.to_ascii_lowercase();
    if road_class == "service" && road.name.is_none() {
        return false;
    }
    matches!(
        road_class.as_str(),
        "primary"
            | "secondary"
            | "tertiary"
            | "residential"
            | "unclassified"
            | "cycleway"
            | "service"
            | "livingstreet"
            | "living_street"
    )
}

fn road_bbox(geometry: &[[f64; 2]]) -> Option<BBox> {
    let first = geometry.first()?;
    let mut bbox = BBox {
        min_lon: first[0],
        max_lon: first[0],
        min_lat: first[1],
        max_lat: first[1],
    };
    for [lon, lat] in geometry.iter().copied().skip(1) {
        bbox.min_lon = bbox.min_lon.min(lon);
        bbox.max_lon = bbox.max_lon.max(lon);
        bbox.min_lat = bbox.min_lat.min(lat);
        bbox.max_lat = bbox.max_lat.max(lat);
    }
    Some(bbox)
}

fn export_profile(
    road: &RoadJson,
    dem_tiles: &[DemTile],
    spacing_m: f64,
) -> Option<LocalElevationProfile> {
    let densified = densify_geometry(&road.geometry, spacing_m);
    let mut points = Vec::new();
    for (dist_m, lon, lat) in densified {
        let elevation = sample_dem(dem_tiles, lon, lat)?;
        points.push(CanonProfilePoint {
            dist_m,
            lat,
            lon,
            elev_m: elevation,
        });
    }
    if points.len() < 2 {
        return None;
    }
    Some(LocalElevationProfile {
        osm_way_id: road.osm_way_id,
        points,
    })
}

fn sample_dem(dem_tiles: &[DemTile], lon: f64, lat: f64) -> Option<f64> {
    dem_tiles
        .iter()
        .find(|tile| tile.contains(lon, lat))
        .and_then(|tile| tile.sample_bilinear(lon, lat))
}

fn densify_geometry(geometry: &[[f64; 2]], spacing_m: f64) -> Vec<(f64, f64, f64)> {
    let mut points = Vec::new();
    let Some(first) = geometry.first() else {
        return points;
    };
    points.push((0.0, first[0], first[1]));
    let mut cumulative_m = 0.0;
    for pair in geometry.windows(2) {
        let [lon_a, lat_a] = pair[0];
        let [lon_b, lat_b] = pair[1];
        let segment_m = haversine_m(lat_a, lon_a, lat_b, lon_b);
        if segment_m <= 0.0 {
            continue;
        }
        let mut next_sample_m = spacing_m;
        while next_sample_m < segment_m {
            let ratio = next_sample_m / segment_m;
            points.push((
                cumulative_m + next_sample_m,
                lon_a + (lon_b - lon_a) * ratio,
                lat_a + (lat_b - lat_a) * ratio,
            ));
            next_sample_m += spacing_m;
        }
        cumulative_m += segment_m;
        points.push((cumulative_m, lon_b, lat_b));
    }
    points
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_bbox() {
        let bbox = parse_bbox("-75.3,39.9,-75.0,40.2").unwrap();
        assert_eq!(bbox.min_lon, -75.3);
        assert_eq!(bbox.max_lat, 40.2);
        assert!(bbox.intersects(&BBox {
            min_lon: -75.25,
            min_lat: 40.0,
            max_lon: -75.2,
            max_lat: 40.1,
        }));
    }

    #[test]
    fn densifies_geometry_at_spacing() {
        let geometry = [[-75.0, 40.0], [-75.0, 40.001]];
        let points = densify_geometry(&geometry, 25.0);
        assert!(points.len() > 3);
        assert_eq!(points.first().unwrap().0, 0.0);
        assert!(points.last().unwrap().0 > 100.0);
    }

    #[test]
    fn pixel_is_area_samples_are_registered_at_pixel_centers() {
        let tile = DemTile {
            path: PathBuf::from("synthetic-pixel-is-area.tif"),
            width: 3,
            height: 3,
            scale_x: 1.0,
            scale_y: 1.0,
            tie_raster_x: 0.0,
            tie_raster_y: 0.0,
            tie_model_x: 0.0,
            tie_model_y: 0.0,
            registration: RasterRegistration::PixelIsArea,
            nodata: None,
            values: vec![10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0],
        };

        assert_eq!(tile.sample_bilinear(0.5, -0.5), Some(10.0));
    }

    #[test]
    fn pixel_is_point_samples_are_registered_at_tiepoints() {
        let tile = DemTile {
            path: PathBuf::from("synthetic-pixel-is-point.tif"),
            width: 3,
            height: 3,
            scale_x: 1.0,
            scale_y: 1.0,
            tie_raster_x: 0.0,
            tie_raster_y: 0.0,
            tie_model_x: 0.0,
            tie_model_y: 0.0,
            registration: RasterRegistration::PixelIsPoint,
            nodata: None,
            values: vec![10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0],
        };

        assert_eq!(tile.sample_bilinear(0.0, 0.0), Some(10.0));
    }

    #[test]
    fn geokeys_distinguish_pixel_is_area_from_pixel_is_point() {
        let area = [1, 1, 0, 1, 1025, 0, 1, 1];
        let point = [1, 1, 0, 1, 1025, 0, 1, 2];

        assert_eq!(
            raster_registration_from_geokeys(Some(&area)).unwrap(),
            RasterRegistration::PixelIsArea
        );
        assert_eq!(
            raster_registration_from_geokeys(Some(&point)).unwrap(),
            RasterRegistration::PixelIsPoint
        );
        assert_eq!(
            raster_registration_from_geokeys(None).unwrap(),
            RasterRegistration::PixelIsArea
        );
    }

    #[test]
    fn unnamed_service_is_not_exported_as_launch_canon_road() {
        let unnamed = RoadJson {
            osm_way_id: 1,
            name: None,
            road_class: "Service".to_string(),
            length_m: 100.0,
            geometry: vec![[-75.0, 40.0], [-75.0, 40.001]],
        };
        let named = RoadJson {
            name: Some("Back Drive".to_string()),
            ..RoadJson {
                osm_way_id: 2,
                name: None,
                road_class: "Service".to_string(),
                length_m: 100.0,
                geometry: vec![[-75.0, 40.0], [-75.0, 40.001]],
            }
        };

        assert!(!is_launch_scope_road(&unnamed));
        assert!(is_launch_scope_road(&named));
    }
}
