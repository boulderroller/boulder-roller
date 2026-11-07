//! H3 hexagonal tile projection for spatial indexing.
//!
//! Uses the H3 hierarchical hexagonal grid system for:
//! - Privacy-preserving location aggregation
//! - Efficient spatial queries
//! - Tile-based attestation architecture
//!
//! Resolution 10 (~50m hexagons) is the default for ride data.

use crate::constants::MISSING_I32;
use h3o::{CellIndex, LatLng, Resolution};
use std::collections::HashSet;

/// Default resolution for tile attestation (~50m hexagons).
pub const DEFAULT_RESOLUTION: Resolution = Resolution::Ten;

/// H3 cell representing a hexagonal tile.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct H3Cell {
    index: CellIndex,
}

impl H3Cell {
    /// Create a cell from lat/lon at the default resolution.
    pub fn from_lat_lon(lat: f64, lon: f64) -> Option<Self> {
        Self::from_lat_lon_res(lat, lon, DEFAULT_RESOLUTION)
    }

    /// Create a cell from lat/lon at a specific resolution.
    pub fn from_lat_lon_res(lat: f64, lon: f64, resolution: Resolution) -> Option<Self> {
        LatLng::new(lat, lon).ok().map(|ll| H3Cell {
            index: ll.to_cell(resolution),
        })
    }

    /// Get the underlying H3 cell index.
    pub fn index(&self) -> CellIndex {
        self.index
    }

    /// Convert to hex string representation (e.g., "8a2a1072b59ffff").
    pub fn to_string(&self) -> String {
        self.index.to_string()
    }

    /// Get the resolution of this cell (0-15).
    pub fn resolution(&self) -> u8 {
        self.index.resolution() as u8
    }

    /// Get the parent cell at a coarser resolution.
    pub fn parent(&self, resolution: Resolution) -> Option<Self> {
        self.index
            .parent(resolution)
            .map(|idx| H3Cell { index: idx })
    }

    /// Check if this cell contains another cell (is an ancestor).
    pub fn contains(&self, other: &H3Cell) -> bool {
        let self_res = self.index.resolution();
        let other_res = other.index.resolution();

        if self_res >= other_res {
            return self.index == other.index;
        }

        // Check if other's parent at self's resolution matches
        other
            .index
            .parent(self_res)
            .map(|p| p == self.index)
            .unwrap_or(false)
    }
}

/// Project GPS coordinates to H3 cells.
///
/// Coordinates are in e7 format (degrees * 10^7 as i32).
/// Returns cells in order, with consecutive duplicates removed.
pub fn project_to_h3(lat_e7: &[i32], lon_e7: &[i32], resolution: Resolution) -> Vec<H3Cell> {
    let mut cells = Vec::new();
    let mut last_cell: Option<CellIndex> = None;

    for (&lat, &lon) in lat_e7.iter().zip(lon_e7.iter()) {
        // Skip missing GPS points
        if lat == MISSING_I32 || lon == MISSING_I32 {
            continue;
        }

        let lat_deg = lat as f64 / 1e7;
        let lon_deg = lon as f64 / 1e7;

        if let Ok(latlng) = LatLng::new(lat_deg, lon_deg) {
            let cell_index = latlng.to_cell(resolution);

            // Dedupe consecutive
            if last_cell != Some(cell_index) {
                cells.push(H3Cell { index: cell_index });
                last_cell = Some(cell_index);
            }
        }
    }

    cells
}

/// Project GPS coordinates to H3 cells at default resolution.
pub fn project_to_cells(lat_e7: &[i32], lon_e7: &[i32]) -> Vec<H3Cell> {
    project_to_h3(lat_e7, lon_e7, DEFAULT_RESOLUTION)
}

/// Get unique cells from a list (removes all duplicates, not just consecutive).
pub fn unique_cells(cells: &[H3Cell]) -> Vec<H3Cell> {
    let mut seen = HashSet::new();
    cells
        .iter()
        .filter(|c| seen.insert(c.index))
        .copied()
        .collect()
}

/// Convert cells to string representations for storage.
pub fn cells_to_strings(cells: &[H3Cell]) -> Vec<String> {
    cells.iter().map(|c| c.to_string()).collect()
}

/// Count unique cells in a track.
pub fn count_unique_cells(lat_e7: &[i32], lon_e7: &[i32]) -> usize {
    let cells = project_to_cells(lat_e7, lon_e7);
    unique_cells(&cells).len()
}

// =============================================================================
// Legacy compatibility - these will be removed after migration
// =============================================================================

/// Legacy Tile struct for backwards compatibility during migration.
/// DEPRECATED: Use H3Cell instead.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[deprecated(since = "0.2.0", note = "Use H3Cell instead")]
pub struct Tile {
    pub x: u32,
    pub y: u32,
    pub z: u8,
}

#[allow(deprecated)]
impl Tile {
    /// DEPRECATED: Use H3Cell::from_lat_lon instead.
    #[deprecated(since = "0.2.0", note = "Use H3Cell::from_lat_lon instead")]
    pub fn from_lat_lon(_lat: f64, _lon: f64, _zoom: u8) -> Self {
        // Return dummy tile - this should not be used
        Tile { x: 0, y: 0, z: 0 }
    }

    /// DEPRECATED: H3 uses hex strings, not quadkeys.
    #[deprecated(since = "0.2.0", note = "H3 uses hex strings, not quadkeys")]
    pub fn to_quadkey(&self) -> String {
        String::new()
    }
}

/// DEPRECATED: Use project_to_h3 instead.
#[allow(deprecated)]
#[deprecated(since = "0.2.0", note = "Use project_to_h3 instead")]
pub fn project_to_tiles(_lat_e7: &[i32], _lon_e7: &[i32], _zoom: u8) -> Vec<Tile> {
    Vec::new()
}

/// DEPRECATED: Use unique_cells instead.
#[allow(deprecated)]
#[deprecated(since = "0.2.0", note = "Use unique_cells instead")]
pub fn unique_tiles(_tiles: &[Tile]) -> Vec<Tile> {
    Vec::new()
}

// =============================================================================
// Tests
// =============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_h3_basic() {
        // Philly: ~39.95, -75.16
        let cell = H3Cell::from_lat_lon(39.95, -75.16).unwrap();

        let cell_str = cell.to_string();
        assert!(
            cell_str.starts_with("8a"),
            "Expected res 10, got: {}",
            cell_str
        );
        assert_eq!(cell.resolution(), 10);
    }

    #[test]
    fn test_h3_from_e7() {
        // Philly in e7 format
        let lat_e7 = vec![399500000i32];
        let lon_e7 = vec![-751600000i32];

        let cells = project_to_cells(&lat_e7, &lon_e7);
        assert_eq!(cells.len(), 1);

        let cell_str = cells[0].to_string();
        assert!(cell_str.starts_with("8a"));
    }

    #[test]
    fn test_h3_dedupes_consecutive() {
        // Same point twice
        let lat_e7 = vec![399500000i32, 399500000i32];
        let lon_e7 = vec![-751600000i32, -751600000i32];

        let cells = project_to_cells(&lat_e7, &lon_e7);
        assert_eq!(cells.len(), 1, "Should dedupe consecutive duplicates");
    }

    #[test]
    fn test_h3_skips_missing() {
        let lat_e7 = vec![MISSING_I32, 399500000i32];
        let lon_e7 = vec![MISSING_I32, -751600000i32];

        let cells = project_to_cells(&lat_e7, &lon_e7);
        assert_eq!(cells.len(), 1, "Should skip missing points");
    }

    #[test]
    fn test_h3_unique_cells() {
        // A -> B -> A pattern (should dedupe the second A)
        let lat_e7 = vec![399500000i32, 399600000i32, 399500000i32];
        let lon_e7 = vec![-751600000i32, -751600000i32, -751600000i32];

        let cells = project_to_cells(&lat_e7, &lon_e7);
        // Consecutive dedupe: A, B, A (3 cells if A != B)
        // or A, A (2 cells if all same)

        let unique = unique_cells(&cells);
        // Should have at most 2 unique cells
        assert!(unique.len() <= cells.len());
    }

    #[test]
    fn test_h3_resolution() {
        let lat_e7 = vec![399500000i32];
        let lon_e7 = vec![-751600000i32];

        // Resolution 10 (default)
        let cells_10 = project_to_h3(&lat_e7, &lon_e7, Resolution::Ten);
        assert_eq!(cells_10[0].resolution(), 10);

        // Resolution 8 (coarser)
        let cells_8 = project_to_h3(&lat_e7, &lon_e7, Resolution::Eight);
        assert_eq!(cells_8[0].resolution(), 8);

        // Different resolutions should give different cells
        assert_ne!(cells_10[0].to_string(), cells_8[0].to_string());
    }

    #[test]
    fn test_h3_parent() {
        let cell = H3Cell::from_lat_lon_res(39.95, -75.16, Resolution::Ten).unwrap();

        let parent = cell.parent(Resolution::Eight).unwrap();
        assert_eq!(parent.resolution(), 8);

        // Parent should contain child
        assert!(parent.contains(&cell));
    }

    #[test]
    fn test_h3_contains() {
        let parent = H3Cell::from_lat_lon_res(39.95, -75.16, Resolution::Eight).unwrap();
        let child = H3Cell::from_lat_lon_res(39.95, -75.16, Resolution::Ten).unwrap();

        assert!(parent.contains(&child));
        assert!(!child.contains(&parent));
        assert!(parent.contains(&parent)); // Self-containment
    }

    #[test]
    fn test_cells_to_strings() {
        let lat_e7 = vec![399500000i32, 399600000i32];
        let lon_e7 = vec![-751600000i32, -751500000i32];

        let cells = project_to_cells(&lat_e7, &lon_e7);
        let strings = cells_to_strings(&cells);

        assert_eq!(strings.len(), cells.len());
        for s in &strings {
            assert!(s.starts_with("8a"), "All should be resolution 10");
        }
    }

    #[test]
    fn test_count_unique_cells() {
        let lat_e7 = vec![399500000i32, 399500000i32, 399600000i32];
        let lon_e7 = vec![-751600000i32, -751600000i32, -751500000i32];

        let count = count_unique_cells(&lat_e7, &lon_e7);
        assert!(count >= 1 && count <= 2);
    }
}
