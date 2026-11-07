//! Climb signature generation.
//!
//! Creates 64-byte fingerprints for climb profiles used for vault matching.
//!
//! Signature Structure (64 bytes):
//! - Bytes 0-31:  SHA256(gradient_profile) - 32 bins normalized to 0-255
//! - Bytes 32-35: Total vertical gain (f32, big-endian)
//! - Bytes 36-39: Average gradient % (f32, big-endian)
//! - Bytes 40-43: Distance meters (f32, big-endian)
//! - Bytes 44-47: Duration seconds (u32, big-endian)
//! - Bytes 48-63: MD5 checksum of bytes 0-48

use sha2::{Digest, Sha256};

use super::constants::*;

/// A 64-byte climb signature for vault matching.
#[derive(Debug, Clone)]
pub struct ClimbSignature {
    /// The 64-byte signature
    pub signature: [u8; 64],
    /// Decoded vertical gain
    pub vert_m: f32,
    /// Decoded average gradient
    pub avg_gradient_pct: f32,
    /// Decoded distance
    pub distance_m: f32,
    /// Decoded duration
    pub duration_s: u32,
}

impl ClimbSignature {
    /// Return signature as hex string.
    pub fn hex(&self) -> String {
        hex::encode(&self.signature)
    }

    /// Calculate similarity score between two signatures (0.0 to 1.0).
    ///
    /// Uses Hamming distance on gradient hash + metric comparison.
    pub fn similarity(&self, other: &ClimbSignature) -> f64 {
        // Hamming distance on gradient profile (32 bytes = 256 bits)
        let bit_diff: u32 = self.signature[..32]
            .iter()
            .zip(other.signature[..32].iter())
            .map(|(a, b)| (a ^ b).count_ones())
            .sum();
        let gradient_sim = 1.0 - (bit_diff as f64 / 256.0);

        // Metric similarities
        let vert_sim = 1.0
            - ((self.vert_m - other.vert_m).abs() / self.vert_m.max(other.vert_m).max(1.0)) as f64;
        let grad_sim = 1.0 - ((self.avg_gradient_pct - other.avg_gradient_pct).abs() / 20.0) as f64;
        let dist_sim = 1.0
            - ((self.distance_m - other.distance_m).abs()
                / self.distance_m.max(other.distance_m).max(1.0)) as f64;

        // Weighted combination (gradient shape matters most)
        0.5 * gradient_sim
            + 0.2 * vert_sim.clamp(0.0, 1.0)
            + 0.2 * grad_sim.clamp(0.0, 1.0)
            + 0.1 * dist_sim.clamp(0.0, 1.0)
    }
}

/// Generate a 64-byte signature from elevation profile data.
///
/// # Arguments
/// * `elevations` - Elevation values in meters (smoothed recommended)
/// * `timestamps` - Timestamps in seconds since ride start
/// * `distances` - Optional cumulative distances in meters
pub fn generate_signature(
    elevations: &[f64],
    timestamps: &[i64],
    distances: Option<&[f64]>,
) -> Option<ClimbSignature> {
    if elevations.len() < 2 || elevations.len() != timestamps.len() {
        return None;
    }

    let n = elevations.len();

    // Calculate or estimate distances
    let owned_distances: Vec<f64>;
    let dist_slice = if let Some(d) = distances {
        d
    } else {
        // Estimate from time at ~5 m/s
        owned_distances = {
            let mut dists = vec![0.0];
            for i in 1..n {
                let dt = (timestamps[i] - timestamps[i - 1]).abs() as f64;
                dists.push(dists.last().unwrap() + dt * ESTIMATED_CYCLING_SPEED_MPS);
            }
            dists
        };
        &owned_distances
    };

    let total_distance = dist_slice.last().unwrap_or(&0.0) - dist_slice.first().unwrap_or(&0.0);
    let total_distance = if total_distance <= 0.0 {
        1.0
    } else {
        total_distance
    };

    // Calculate total vertical gain
    let total_vert: f64 = elevations.windows(2).map(|w| (w[1] - w[0]).max(0.0)).sum();

    // Calculate average gradient (straight-line)
    let elev_change = elevations.last().unwrap_or(&0.0) - elevations.first().unwrap_or(&0.0);
    let avg_gradient = if total_distance > 0.0 {
        (elev_change / total_distance) * 100.0
    } else {
        0.0
    };

    // Duration
    let duration_s =
        (timestamps.last().unwrap_or(&0) - timestamps.first().unwrap_or(&0)).max(0) as u32;

    // Build gradient profile (32 bins)
    let gradient_profile = build_gradient_profile(elevations, dist_slice);

    // Hash the gradient profile
    let mut hasher = Sha256::new();
    hasher.update(&gradient_profile);
    let profile_hash: [u8; 32] = hasher.finalize().into();

    // Pack metrics (big-endian)
    let vert_bytes = (total_vert as f32).to_be_bytes();
    let grad_bytes = (avg_gradient as f32).to_be_bytes();
    let dist_bytes = (total_distance as f32).to_be_bytes();
    let dur_bytes = duration_s.to_be_bytes();

    // Build data for checksum
    let mut data_to_hash = Vec::with_capacity(48);
    data_to_hash.extend_from_slice(&profile_hash);
    data_to_hash.extend_from_slice(&vert_bytes);
    data_to_hash.extend_from_slice(&grad_bytes);
    data_to_hash.extend_from_slice(&dist_bytes);
    data_to_hash.extend_from_slice(&dur_bytes);

    // Calculate MD5 checksum using md5 crate
    let checksum: [u8; 16] = md5::compute(&data_to_hash).0;

    // Assemble 64-byte signature
    let mut signature = [0u8; 64];
    signature[0..32].copy_from_slice(&profile_hash);
    signature[32..36].copy_from_slice(&vert_bytes);
    signature[36..40].copy_from_slice(&grad_bytes);
    signature[40..44].copy_from_slice(&dist_bytes);
    signature[44..48].copy_from_slice(&dur_bytes);
    signature[48..64].copy_from_slice(&checksum);

    Some(ClimbSignature {
        signature,
        vert_m: total_vert as f32,
        avg_gradient_pct: avg_gradient as f32,
        distance_m: total_distance as f32,
        duration_s,
    })
}

/// Build a normalized gradient profile as 32 bytes.
fn build_gradient_profile(elevations: &[f64], distances: &[f64]) -> [u8; GRADIENT_BINS] {
    let total_dist = distances.last().unwrap_or(&0.0) - distances.first().unwrap_or(&0.0);

    if total_dist <= 0.0 {
        return [0u8; GRADIENT_BINS];
    }

    let bin_size = total_dist / GRADIENT_BINS as f64;
    let mut profile = [0u8; GRADIENT_BINS];

    for bin_idx in 0..GRADIENT_BINS {
        let bin_start_dist = distances[0] + bin_idx as f64 * bin_size;
        let bin_end_dist = bin_start_dist + bin_size;

        // Interpolate elevation at bin boundaries
        let start_elev = interpolate_elevation(distances, elevations, bin_start_dist);
        let end_elev = interpolate_elevation(distances, elevations, bin_end_dist);

        let elev_change = end_elev - start_elev;
        let gradient_pct = if bin_size > 0.0 {
            (elev_change / bin_size) * 100.0
        } else {
            0.0
        };

        // Normalize to 0-255 (maps [-10%, +20%] to bytes)
        let normalized = (gradient_pct - SIGNATURE_GRADIENT_MIN)
            / (SIGNATURE_GRADIENT_MAX - SIGNATURE_GRADIENT_MIN);
        let normalized = normalized.clamp(0.0, 1.0);
        profile[bin_idx] = (normalized * 255.0) as u8;
    }

    profile
}

/// Linear interpolation to get elevation at a specific distance.
fn interpolate_elevation(distances: &[f64], elevations: &[f64], target_dist: f64) -> f64 {
    if target_dist <= distances[0] {
        return elevations[0];
    }
    if target_dist >= *distances.last().unwrap_or(&0.0) {
        return *elevations.last().unwrap_or(&0.0);
    }

    for i in 1..distances.len() {
        if distances[i] >= target_dist {
            let d0 = distances[i - 1];
            let d1 = distances[i];
            let e0 = elevations[i - 1];
            let e1 = elevations[i];

            if (d1 - d0).abs() < f64::EPSILON {
                return e0;
            }

            let t = (target_dist - d0) / (d1 - d0);
            return e0 + t * (e1 - e0);
        }
    }

    *elevations.last().unwrap_or(&0.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_signature_generation() {
        let elevations: Vec<f64> = (0..100).map(|i| 1000.0 + i as f64 * 3.0).collect();
        let timestamps: Vec<i64> = (0..100).map(|i| i * 10).collect();

        let sig = generate_signature(&elevations, &timestamps, None);
        assert!(sig.is_some());

        let sig = sig.unwrap();
        assert_eq!(sig.signature.len(), 64);
        assert!(sig.vert_m > 0.0);
        assert!(sig.duration_s > 0);
    }

    #[test]
    fn test_signature_hex() {
        let elevations: Vec<f64> = (0..50).map(|i| 1000.0 + i as f64 * 2.0).collect();
        let timestamps: Vec<i64> = (0..50).map(|i| i * 10).collect();

        let sig = generate_signature(&elevations, &timestamps, None).unwrap();
        let hex = sig.hex();

        assert_eq!(hex.len(), 128); // 64 bytes = 128 hex chars
    }

    #[test]
    fn test_signature_similarity_identical() {
        let elevations: Vec<f64> = (0..100).map(|i| 1000.0 + i as f64 * 3.0).collect();
        let timestamps: Vec<i64> = (0..100).map(|i| i * 10).collect();

        let sig1 = generate_signature(&elevations, &timestamps, None).unwrap();
        let sig2 = generate_signature(&elevations, &timestamps, None).unwrap();

        let similarity = sig1.similarity(&sig2);
        assert!(
            similarity > 0.99,
            "Identical signatures should have similarity > 0.99"
        );
    }

    #[test]
    fn test_signature_similarity_different() {
        let elev1: Vec<f64> = (0..100).map(|i| 1000.0 + i as f64 * 3.0).collect();
        let elev2: Vec<f64> = (0..100).map(|i| 1000.0 + i as f64 * 10.0).collect();
        let timestamps: Vec<i64> = (0..100).map(|i| i * 10).collect();

        let sig1 = generate_signature(&elev1, &timestamps, None).unwrap();
        let sig2 = generate_signature(&elev2, &timestamps, None).unwrap();

        let similarity = sig1.similarity(&sig2);
        assert!(
            similarity < 0.9,
            "Different gradients should have lower similarity"
        );
    }

    #[test]
    fn test_v1_signature_deterministic() {
        // Pinned test: known inputs must always produce the same signature.
        // If this test fails, v1 signature generation has changed, which would
        // corrupt all existing vault matches. DO NOT update the expected value
        // without a migration plan for all indexed_vaults signatures.
        let elevations: Vec<f64> = (0..100).map(|i| 1000.0 + i as f64 * 3.0).collect();
        let timestamps: Vec<i64> = (0..100).map(|i| i * 10).collect();
        let distances: Vec<f64> = (0..100).map(|i| i as f64 * 50.0).collect();

        let sig = generate_signature(&elevations, &timestamps, Some(&distances)).unwrap();
        let hex = sig.hex();

        assert_eq!(
            hex,
            "e8b72e0b71c772f8398f58104fb04c243c67ec46014cb06c22329c49b03d4c864394800040c00000459ab000000003defb3518f2556e719e1ddcf39142aabe06"
        );
    }

    #[test]
    fn test_gradient_profile() {
        let elevations: Vec<f64> = (0..100).map(|i| 1000.0 + i as f64 * 5.0).collect();
        let distances: Vec<f64> = (0..100).map(|i| i as f64 * 10.0).collect();

        let profile = build_gradient_profile(&elevations, &distances);

        // 5m rise per 10m horizontal = 50% gradient
        // Normalized: (50 - (-10)) / (20 - (-10)) = 60/30 = 2.0 -> clamped to 1.0 -> 255
        assert!(
            profile.iter().all(|&b| b == 255),
            "50% gradient should max out bins"
        );
    }
}
