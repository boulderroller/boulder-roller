//! Tile-to-feature lookup for ride attribution.
//!
//! This module provides efficient lookup of geographic features
//! for a set of H3 tiles, enabling ride attribution like:
//! "Your climb was 85% on Manayunk Wall"

use std::collections::HashMap;

/// Attribution result for a set of tiles.
#[derive(Debug, Clone)]
pub struct TileAttribution {
    /// Features with coverage percentage: [(feature_name, coverage), ...]
    /// Sorted by coverage descending.
    pub features: Vec<(String, f32)>,

    /// Total tiles queried.
    pub total_tiles: usize,

    /// Tiles that matched at least one feature.
    pub matched_tiles: usize,

    /// Primary feature (highest coverage).
    pub primary_feature: Option<String>,

    /// Primary feature coverage (0.0 - 1.0).
    pub primary_coverage: f32,
}

impl TileAttribution {
    /// Create an empty attribution (no matches).
    pub fn empty(total_tiles: usize) -> Self {
        Self {
            features: Vec::new(),
            total_tiles,
            matched_tiles: 0,
            primary_feature: None,
            primary_coverage: 0.0,
        }
    }

    /// Check if this attribution has any matches.
    pub fn has_matches(&self) -> bool {
        !self.features.is_empty()
    }

    /// Get a human-readable summary.
    pub fn summary(&self) -> String {
        if let Some(ref name) = self.primary_feature {
            let pct = (self.primary_coverage * 100.0).round() as u32;
            format!("{}% on {}", pct, name)
        } else {
            "No known features".to_string()
        }
    }
}

/// Tile-to-feature lookup engine.
///
/// This is a placeholder that will be connected to a database
/// containing preprocessed OSM road features.
pub struct TileLookup {
    /// In-memory cache of tile -> features mapping.
    /// In production, this would query a database.
    cache: HashMap<String, Vec<String>>,
}

impl TileLookup {
    /// Create a new lookup engine.
    ///
    /// In production, this would take a database connection pool.
    pub fn new() -> Self {
        Self {
            cache: HashMap::new(),
        }
    }

    /// Create a lookup engine with preloaded data.
    ///
    /// Used for testing or when data is small enough to fit in memory.
    pub fn with_cache(cache: HashMap<String, Vec<String>>) -> Self {
        Self { cache }
    }

    /// Attribute a set of tiles to geographic features.
    ///
    /// Returns coverage percentages for each feature that the tiles
    /// pass through.
    pub fn attribute_tiles(&self, tile_ids: &[String]) -> TileAttribution {
        if tile_ids.is_empty() {
            return TileAttribution::empty(0);
        }

        let total_tiles = tile_ids.len();
        let mut feature_counts: HashMap<String, usize> = HashMap::new();
        let mut matched_tiles = 0;

        for tile_id in tile_ids {
            if let Some(features) = self.cache.get(tile_id) {
                if !features.is_empty() {
                    matched_tiles += 1;
                    for feature in features {
                        *feature_counts.entry(feature.clone()).or_insert(0) += 1;
                    }
                }
            }
        }

        // Convert counts to coverage percentages
        let mut features: Vec<(String, f32)> = feature_counts
            .into_iter()
            .map(|(name, count)| (name, count as f32 / total_tiles as f32))
            .collect();

        // Sort by coverage descending
        features.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

        let (primary_feature, primary_coverage) = features
            .first()
            .map(|(name, cov)| (Some(name.clone()), *cov))
            .unwrap_or((None, 0.0));

        TileAttribution {
            features,
            total_tiles,
            matched_tiles,
            primary_feature,
            primary_coverage,
        }
    }

    /// Load tile mappings from a list of (tile_id, feature_name) pairs.
    pub fn load_mappings(&mut self, mappings: impl IntoIterator<Item = (String, String)>) {
        for (tile_id, feature_name) in mappings {
            self.cache
                .entry(tile_id)
                .or_insert_with(Vec::new)
                .push(feature_name);
        }
    }

    /// Get features for a single tile.
    pub fn get_tile_features(&self, tile_id: &str) -> Option<&Vec<String>> {
        self.cache.get(tile_id)
    }

    /// Check if a tile has any known features.
    pub fn tile_has_features(&self, tile_id: &str) -> bool {
        self.cache
            .get(tile_id)
            .map(|f| !f.is_empty())
            .unwrap_or(false)
    }
}

impl Default for TileLookup {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_lookup() -> TileLookup {
        let mut cache = HashMap::new();
        cache.insert(
            "8a2a1072b59ffff".to_string(),
            vec!["Manayunk Wall".to_string()],
        );
        cache.insert(
            "8a2a1072b58ffff".to_string(),
            vec!["Manayunk Wall".to_string()],
        );
        cache.insert(
            "8a2a1072b57ffff".to_string(),
            vec!["Manayunk Wall".to_string(), "Main St".to_string()],
        );
        cache.insert("8a2a1072b56ffff".to_string(), vec!["Ridge Ave".to_string()]);
        TileLookup::with_cache(cache)
    }

    #[test]
    fn test_attribute_full_coverage() {
        let lookup = sample_lookup();
        let tiles = vec![
            "8a2a1072b59ffff".to_string(),
            "8a2a1072b58ffff".to_string(),
            "8a2a1072b57ffff".to_string(),
        ];

        let attr = lookup.attribute_tiles(&tiles);

        assert_eq!(attr.total_tiles, 3);
        assert_eq!(attr.matched_tiles, 3);
        assert_eq!(attr.primary_feature, Some("Manayunk Wall".to_string()));
        assert!((attr.primary_coverage - 1.0).abs() < 0.001); // 100% coverage
    }

    #[test]
    fn test_attribute_partial_coverage() {
        let lookup = sample_lookup();
        let tiles = vec![
            "8a2a1072b59ffff".to_string(),
            "8a2a1072b58ffff".to_string(),
            "8a2a1072b56ffff".to_string(), // Different road
            "unknown_tile".to_string(),    // Not in cache
        ];

        let attr = lookup.attribute_tiles(&tiles);

        assert_eq!(attr.total_tiles, 4);
        assert_eq!(attr.matched_tiles, 3);
        assert_eq!(attr.primary_feature, Some("Manayunk Wall".to_string()));
        assert!((attr.primary_coverage - 0.5).abs() < 0.001); // 50% coverage
    }

    #[test]
    fn test_attribute_empty_tiles() {
        let lookup = sample_lookup();
        let attr = lookup.attribute_tiles(&[]);

        assert_eq!(attr.total_tiles, 0);
        assert!(!attr.has_matches());
    }

    #[test]
    fn test_attribute_no_matches() {
        let lookup = sample_lookup();
        let tiles = vec!["unknown1".to_string(), "unknown2".to_string()];

        let attr = lookup.attribute_tiles(&tiles);

        assert_eq!(attr.total_tiles, 2);
        assert_eq!(attr.matched_tiles, 0);
        assert!(!attr.has_matches());
    }

    #[test]
    fn test_summary() {
        let lookup = sample_lookup();
        let tiles = vec!["8a2a1072b59ffff".to_string(), "8a2a1072b58ffff".to_string()];

        let attr = lookup.attribute_tiles(&tiles);
        assert_eq!(attr.summary(), "100% on Manayunk Wall");
    }

    #[test]
    fn test_load_mappings() {
        let mut lookup = TileLookup::new();
        lookup.load_mappings(vec![
            ("tile1".to_string(), "Road A".to_string()),
            ("tile1".to_string(), "Road B".to_string()),
            ("tile2".to_string(), "Road A".to_string()),
        ]);

        let features = lookup.get_tile_features("tile1").unwrap();
        assert_eq!(features.len(), 2);
        assert!(features.contains(&"Road A".to_string()));
        assert!(features.contains(&"Road B".to_string()));
    }
}
