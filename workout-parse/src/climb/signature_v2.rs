//! DCT-II climb signatures (v2).
//!
//! Replaces SHA256-hashed gradient profiles with DCT coefficients that preserve
//! geometric similarity. Uses relative Euclidean distance instead of Hamming
//! distance for matching.
//!
//! # Signature Layout (64 bytes)
//!
//! | Offset | Size | Type    | Field            |
//! |--------|------|---------|------------------|
//! | 0      | 1    | u8      | version (0x02)   |
//! | 1      | 1    | u8      | flags            |
//! | 2      | 2    | u16 BE  | vert_m           |
//! | 4      | 2    | u16 BE  | distance_dam (×10m) |
//! | 6      | 2    | i16 BE  | avg_gradient×100 |
//! | 8      | 8    | u64 BE  | h3_anchor        |
//! | 16     | 32   | f16[16] | DCT-II coeffs    |
//! | 48     | 16   | [u8;16] | BLAKE3 checksum  |

use half::f16;
use std::f64::consts::PI;

use super::constants::{GRADIENT_BINS, SIGNATURE_GRADIENT_MAX, SIGNATURE_GRADIENT_MIN};

/// Signature version byte for v2 format.
pub const SIGNATURE_VERSION: u8 = 0x02;

/// Number of DCT coefficients retained in the signature (first 16 of 32).
const DCT_COEFFS: usize = 16;

/// Established v2 f16 zero bits by DCT slot.
///
/// Target libm implementations can give exact-zero DCT terms tiny residuals
/// with opposite signs. Those residuals both quantize to zero, but f16 retains
/// the sign bit and the signature checksum covers it. Keep the original macOS
/// wire signs explicit so zero-valued coefficients encode identically.
const CANONICAL_DCT_ZERO_BITS: [u16; DCT_COEFFS] = [
    0x0000, 0x0000, 0x8000, 0x0000, 0x8000, 0x0000, 0x0000, 0x8000, 0x8000, 0x8000, 0x0000, 0x8000,
    0x8000, 0x8000, 0x0000, 0x8000,
];

/// Number of DCT coefficients used for matching.
/// Only the low-frequency coefficients (0-5) are stable across different GPS recordings
/// of the same physical climb. Coefficients 6+ are dominated by barometric/GPS noise
/// (corpus analysis: DCT[0-3] divergence 46-55, DCT[8+] divergence 200-500+).
const DCT_MATCH_COEFFS: usize = 6;

/// Match threshold: relative Euclidean distance below this is a definite match.
const MATCH_THRESHOLD: f64 = 0.08;

/// Probable match threshold: between MATCH and this is uncertain.
const PROBABLE_MATCH_THRESHOLD: f64 = 0.15;

/// Geometric pre-filter: vert and distance must be within this relative diff.
/// Relaxed from 0.15 to 0.25 to accommodate GPS noise and different recording
/// start/end points on the same physical climb.
const GEOMETRIC_TOLERANCE: f64 = 0.25;

/// H3 k-ring distance limit for geographic proximity gate.
const H3_MAX_GRID_DISTANCE: u32 = 3;

/// H3 resolution used for the matching proximity gate.
/// Signatures encode midpoint res-10 cells (~76m edges), but GPS jitter and
/// boundary differences can place the same climb's midpoints 20+ cells apart. Coarsening to
/// res-7 (~1.4km edges) before computing grid distance absorbs this jitter while
/// still filtering cross-city false matches. The k=3 bound is a multi-kilometer
/// neighborhood whose exact center-to-center reach varies by cell geometry.
/// Corpus evidence: 146 known same-climb pairs had res-10 grid distance 4–31
/// but res-7 distance 0–2.
const H3_MATCH_RESOLUTION: h3o::Resolution = h3o::Resolution::Seven;

// ---------------------------------------------------------------------------
// Data structures
// ---------------------------------------------------------------------------

/// A v2 climb signature.
#[derive(Debug, Clone)]
pub struct SignatureV2 {
    /// Raw 64-byte signature.
    pub bytes: [u8; 64],
    /// Decoded fields for fast access.
    pub version: u8,
    pub flags: u8,
    pub vert_m: u16,
    /// Decoded distance in meters. The wire field remains decameters.
    pub distance_m: u32,
    pub avg_gradient_x100: i16,
    pub h3_anchor: u64,
    pub dct_coeffs: [f32; DCT_COEFFS],
}

/// Result of multi-gate signature matching.
#[derive(Debug, Clone, PartialEq)]
pub enum MatchResult {
    /// Strong match — same climb with high confidence.
    Match { confidence: f64 },
    /// Possible match — boundary case.
    ProbableMatch { confidence: f64 },
    /// Not a match.
    NoMatch,
    /// Signatures are incompatible (different versions).
    Incompatible,
}

/// Flags byte encoding.
#[derive(Debug, Clone, Copy)]
pub struct SignatureFlags {
    pub terrain: u8,     // 2 bits: 0=flat, 1=rolling, 2=hilly, 3=mountainous
    pub direction: bool, // false=N/E dominant, true=S/W dominant
    pub has_power: bool,
}

impl SignatureFlags {
    pub fn encode(&self) -> u8 {
        let mut flags = 0u8;
        flags |= (self.terrain & 0x03) << 2;
        if self.direction {
            flags |= 0x02;
        }
        if self.has_power {
            flags |= 0x01;
        }
        flags
    }

    pub fn decode(byte: u8) -> Self {
        Self {
            terrain: (byte >> 2) & 0x03,
            direction: (byte & 0x02) != 0,
            has_power: (byte & 0x01) != 0,
        }
    }
}

// ---------------------------------------------------------------------------
// DCT-II computation
// ---------------------------------------------------------------------------

/// Compute orthonormal DCT-II of a 32-element input, returning the first 16 coefficients.
///
/// Formula: c[k] = sqrt(2/N) * sum_{n=0}^{N-1} x[n] * cos(pi*(2n+1)*k / (2N))
/// with sqrt(1/N) normalization for k=0.
fn dct_ii_32_to_16(input: &[u8; GRADIENT_BINS]) -> [f32; DCT_COEFFS] {
    let n = GRADIENT_BINS as f64;
    let mut coeffs = [0.0f32; DCT_COEFFS];

    for k in 0..DCT_COEFFS {
        let mut sum = 0.0f64;
        for (idx, &x) in input.iter().enumerate() {
            let angle = PI * (2.0 * idx as f64 + 1.0) * k as f64 / (2.0 * n);
            sum += x as f64 * angle.cos();
        }

        // Orthonormal scaling
        let scale = if k == 0 {
            (1.0 / n).sqrt()
        } else {
            (2.0 / n).sqrt()
        };

        coeffs[k] = (sum * scale) as f32;
    }

    coeffs
}

fn dct_coefficient_bytes(coefficient_index: usize, coefficient: f32) -> [u8; 2] {
    debug_assert!(coefficient_index < DCT_COEFFS);

    let quantized_bits = f16::from_f32(coefficient).to_bits();
    let wire_bits = if quantized_bits & 0x7fff == 0 {
        CANONICAL_DCT_ZERO_BITS[coefficient_index]
    } else {
        quantized_bits
    };
    wire_bits.to_be_bytes()
}

// ---------------------------------------------------------------------------
// Gradient profile (shared logic with v1)
// ---------------------------------------------------------------------------

/// Build a 32-bin gradient profile from elevation and distance arrays.
/// Same binning as v1 (constants::GRADIENT_BINS) for consistency.
pub fn build_gradient_profile(elevations: &[f64], distances: &[f64]) -> [u8; GRADIENT_BINS] {
    let total_dist = distances.last().unwrap_or(&0.0) - distances.first().unwrap_or(&0.0);
    if total_dist <= 0.0 {
        return [0u8; GRADIENT_BINS];
    }

    let bin_size = total_dist / GRADIENT_BINS as f64;
    let mut profile = [0u8; GRADIENT_BINS];

    for bin_idx in 0..GRADIENT_BINS {
        let bin_start_dist = distances[0] + bin_idx as f64 * bin_size;
        let bin_end_dist = bin_start_dist + bin_size;

        let start_elev = interpolate(distances, elevations, bin_start_dist);
        let end_elev = interpolate(distances, elevations, bin_end_dist);

        let gradient_pct = if bin_size > 0.0 {
            ((end_elev - start_elev) / bin_size) * 100.0
        } else {
            0.0
        };

        let normalized = (gradient_pct - SIGNATURE_GRADIENT_MIN)
            / (SIGNATURE_GRADIENT_MAX - SIGNATURE_GRADIENT_MIN);
        profile[bin_idx] = (normalized.clamp(0.0, 1.0) * 255.0) as u8;
    }

    profile
}

/// Linear interpolation for elevation at a target distance.
fn interpolate(distances: &[f64], values: &[f64], target: f64) -> f64 {
    if target <= distances[0] {
        return values[0];
    }
    if target >= *distances.last().unwrap_or(&0.0) {
        return *values.last().unwrap_or(&0.0);
    }
    for i in 1..distances.len() {
        if distances[i] >= target {
            let d0 = distances[i - 1];
            let d1 = distances[i];
            if (d1 - d0).abs() < f64::EPSILON {
                return values[i - 1];
            }
            let t = (target - d0) / (d1 - d0);
            return values[i - 1] + t * (values[i] - values[i - 1]);
        }
    }
    *values.last().unwrap_or(&0.0)
}

// ---------------------------------------------------------------------------
// Signature generation
// ---------------------------------------------------------------------------

/// Generate a v2 signature from climb data.
///
/// # Arguments
/// * `elevations` - Smoothed elevation values (meters)
/// * `distances` - Cumulative distances (meters), same length as elevations
/// * `h3_anchor` - H3 resolution-10 cell at climb midpoint (0 if unknown)
/// * `has_power` - Whether the ride had power meter data
/// * `terrain_class` - 0=flat, 1=rolling, 2=hilly, 3=mountainous
pub fn generate_signature_v2(
    elevations: &[f64],
    distances: &[f64],
    h3_anchor: u64,
    has_power: bool,
    terrain_class: u8,
) -> Option<SignatureV2> {
    if elevations.len() < 2 || elevations.len() != distances.len() {
        return None;
    }

    let total_dist = distances.last().unwrap_or(&0.0) - distances.first().unwrap_or(&0.0);
    if total_dist <= 0.0 {
        return None;
    }

    // Metrics
    let vert: f64 = elevations.windows(2).map(|w| (w[1] - w[0]).max(0.0)).sum();

    // Reject micro-climbs that produce degenerate all-zero DCT signatures.
    // Climbs below 5m vert or 50m distance can't produce meaningful gradient
    // profiles — they round to zero in the 32-bin DCT.
    if vert < 5.0 || total_dist < 50.0 {
        return None;
    }

    let elev_change = elevations.last().unwrap_or(&0.0) - elevations.first().unwrap_or(&0.0);
    let avg_gradient = (elev_change / total_dist) * 100.0;

    let vert_u16 = (vert as u16).min(u16::MAX);
    // Encode distance in decameters (×10m units, max 655.35 km)
    let dist_dam = ((total_dist / 10.0) as u16).min(u16::MAX);
    let grad_i16 = (avg_gradient * 100.0) as i16;

    // Build gradient profile and compute DCT
    let profile = build_gradient_profile(elevations, distances);
    let dct_f32 = dct_ii_32_to_16(&profile);

    // Determine direction from GPS (N/E vs S/W dominant)
    // Simple heuristic: if climb ends further north/east than it starts
    let direction = false; // Default; caller can override if needed

    let flags = SignatureFlags {
        terrain: terrain_class & 0x03,
        direction,
        has_power,
    };

    // Assemble 64-byte signature
    let mut bytes = [0u8; 64];
    bytes[0] = SIGNATURE_VERSION;
    bytes[1] = flags.encode();
    bytes[2..4].copy_from_slice(&vert_u16.to_be_bytes());
    bytes[4..6].copy_from_slice(&dist_dam.to_be_bytes());
    bytes[6..8].copy_from_slice(&grad_i16.to_be_bytes());
    bytes[8..16].copy_from_slice(&h3_anchor.to_be_bytes());

    // Pack f16 coefficients (2 bytes each, 16 coeffs = 32 bytes)
    for (i, &coeff) in dct_f32.iter().enumerate() {
        let coeff_bytes = dct_coefficient_bytes(i, coeff);
        bytes[16 + i * 2] = coeff_bytes[0];
        bytes[16 + i * 2 + 1] = coeff_bytes[1];
    }

    // BLAKE3 checksum of bytes 0..48, truncated to 16 bytes
    let hash = blake3::hash(&bytes[0..48]);
    bytes[48..64].copy_from_slice(&hash.as_bytes()[..16]);

    Some(SignatureV2 {
        bytes,
        version: SIGNATURE_VERSION,
        flags: flags.encode(),
        vert_m: vert_u16,
        distance_m: u32::from(dist_dam) * 10,
        avg_gradient_x100: grad_i16,
        h3_anchor,
        dct_coeffs: dct_f32,
    })
}

impl SignatureV2 {
    /// Decode a v2 signature from raw bytes.
    pub fn from_bytes(bytes: [u8; 64]) -> Option<Self> {
        if bytes[0] != SIGNATURE_VERSION {
            return None;
        }

        // Verify BLAKE3 checksum
        let hash = blake3::hash(&bytes[0..48]);
        if &hash.as_bytes()[..16] != &bytes[48..64] {
            return None;
        }

        let vert_m = u16::from_be_bytes([bytes[2], bytes[3]]);
        let distance_m = u32::from(u16::from_be_bytes([bytes[4], bytes[5]])) * 10;
        let avg_gradient_x100 = i16::from_be_bytes([bytes[6], bytes[7]]);
        let h3_anchor = u64::from_be_bytes([
            bytes[8], bytes[9], bytes[10], bytes[11], bytes[12], bytes[13], bytes[14], bytes[15],
        ]);

        // Unpack f16 coefficients
        let mut dct_coeffs = [0.0f32; DCT_COEFFS];
        for i in 0..DCT_COEFFS {
            let f16_val = f16::from_be_bytes([bytes[16 + i * 2], bytes[16 + i * 2 + 1]]);
            dct_coeffs[i] = f16_val.to_f32();
        }

        Some(Self {
            bytes,
            version: SIGNATURE_VERSION,
            flags: bytes[1],
            vert_m,
            distance_m,
            avg_gradient_x100,
            h3_anchor,
            dct_coeffs,
        })
    }

    /// Return signature as hex string (128 chars).
    pub fn hex(&self) -> String {
        hex::encode(&self.bytes)
    }

    /// Decode from hex string.
    pub fn from_hex(s: &str) -> Option<Self> {
        let bytes_vec = hex::decode(s).ok()?;
        if bytes_vec.len() != 64 {
            return None;
        }
        let mut bytes = [0u8; 64];
        bytes.copy_from_slice(&bytes_vec);
        Self::from_bytes(bytes)
    }

    /// Relative Euclidean distance between two signatures' DCT coefficients.
    ///
    /// d_rel(x, y) = ||c_x - c_y||_2 / (0.5 * (||c_x||_2 + ||c_y||_2))
    ///
    /// Only compares the first DCT_MATCH_COEFFS (low-frequency) coefficients,
    /// which encode the climb's gross shape. Higher coefficients are noise-dominated
    /// and cause false negatives when matching the same physical climb across rides.
    ///
    /// Returns 0.0 for identical, 2.0 for maximally different.
    /// Returns f64::MAX for degenerate cases (zero-norm vectors).
    pub fn dct_distance(&self, other: &SignatureV2) -> f64 {
        let mut diff_sq = 0.0f64;
        let mut norm_a_sq = 0.0f64;
        let mut norm_b_sq = 0.0f64;

        for i in 0..DCT_MATCH_COEFFS {
            let a = self.dct_coeffs[i] as f64;
            let b = other.dct_coeffs[i] as f64;
            diff_sq += (a - b) * (a - b);
            norm_a_sq += a * a;
            norm_b_sq += b * b;
        }

        let denominator = 0.5 * (norm_a_sq.sqrt() + norm_b_sq.sqrt());
        if denominator < f64::EPSILON {
            return if diff_sq < f64::EPSILON {
                0.0
            } else {
                f64::MAX
            };
        }

        diff_sq.sqrt() / denominator
    }

    /// Full 16-coefficient distance (used for testing/diagnostics).
    pub fn dct_distance_full(&self, other: &SignatureV2) -> f64 {
        let mut diff_sq = 0.0f64;
        let mut norm_a_sq = 0.0f64;
        let mut norm_b_sq = 0.0f64;

        for i in 0..DCT_COEFFS {
            let a = self.dct_coeffs[i] as f64;
            let b = other.dct_coeffs[i] as f64;
            diff_sq += (a - b) * (a - b);
            norm_a_sq += a * a;
            norm_b_sq += b * b;
        }

        let denominator = 0.5 * (norm_a_sq.sqrt() + norm_b_sq.sqrt());
        if denominator < f64::EPSILON {
            return if diff_sq < f64::EPSILON {
                0.0
            } else {
                f64::MAX
            };
        }

        diff_sq.sqrt() / denominator
    }

    /// Multi-gate matching pipeline.
    pub fn match_against(&self, other: &SignatureV2) -> MatchResult {
        // Gate 0: Version
        if self.version != other.version {
            return MatchResult::Incompatible;
        }

        // Gate 1: H3 proximity
        if self.h3_anchor != 0 && other.h3_anchor != 0 {
            match h3_grid_distance(self.h3_anchor, other.h3_anchor) {
                Some(d) if d > H3_MAX_GRID_DISTANCE => return MatchResult::NoMatch,
                None => return MatchResult::NoMatch,
                _ => {}
            }
        }

        // Gate 2: Geometric pre-filter
        if self.vert_m > 0 && other.vert_m > 0 {
            let max_v = self.vert_m.max(other.vert_m) as f64;
            let diff_v = (self.vert_m as f64 - other.vert_m as f64).abs();
            if diff_v / max_v > GEOMETRIC_TOLERANCE {
                return MatchResult::NoMatch;
            }
        }
        if self.distance_m > 0 && other.distance_m > 0 {
            let max_d = self.distance_m.max(other.distance_m) as f64;
            let diff_d = (self.distance_m as f64 - other.distance_m as f64).abs();
            if diff_d / max_d > GEOMETRIC_TOLERANCE {
                return MatchResult::NoMatch;
            }
        }

        // Gate 3: DCT shape match
        let d = self.dct_distance(other);
        if d < MATCH_THRESHOLD {
            MatchResult::Match {
                confidence: 1.0 - d / MATCH_THRESHOLD,
            }
        } else if d < PROBABLE_MATCH_THRESHOLD {
            MatchResult::ProbableMatch {
                confidence: 1.0
                    - (d - MATCH_THRESHOLD) / (PROBABLE_MATCH_THRESHOLD - MATCH_THRESHOLD),
            }
        } else {
            MatchResult::NoMatch
        }
    }
}

/// Compute H3 grid distance between two cells, coarsened to [`H3_MATCH_RESOLUTION`].
///
/// Signatures encode res-10 cells, but GPS jitter across recordings of the same
/// physical climb can place midpoint anchors in cells 20+ apart at res-10. Coarsening
/// to res-7 before comparing absorbs this jitter (res-7 edge ≈ 1.4 km) while still
/// filtering geographically distant false matches.
///
/// Returns `None` if either cell is invalid or cannot be coarsened.
fn h3_grid_distance(a: u64, b: u64) -> Option<u32> {
    use h3o::CellIndex;
    let cell_a = CellIndex::try_from(a).ok()?;
    let cell_b = CellIndex::try_from(b).ok()?;

    // Coarsen to match resolution to absorb GPS jitter
    let parent_a = cell_a.parent(H3_MATCH_RESOLUTION)?;
    let parent_b = cell_b.parent(H3_MATCH_RESOLUTION)?;

    parent_a.grid_distance(parent_b).ok().map(|d| d as u32)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_dct_dc_component() {
        // Uniform profile should have all energy in c[0]
        let input = [128u8; GRADIENT_BINS];
        let coeffs = dct_ii_32_to_16(&input);
        // c[0] should be 128 * sqrt(N) for orthonormal
        let expected_c0 = 128.0 * (GRADIENT_BINS as f32).sqrt();
        assert!(
            (coeffs[0] - expected_c0).abs() < 0.1,
            "DC component should be 128*sqrt(32)={}, got {}",
            expected_c0,
            coeffs[0]
        );
        // All other coefficients should be ~0
        for k in 1..DCT_COEFFS {
            assert!(
                coeffs[k].abs() < 0.01,
                "c[{}] should be ~0 for uniform input, got {}",
                k,
                coeffs[k]
            );
        }
    }

    #[test]
    fn test_dct_energy_preservation() {
        // Parseval's theorem: sum of squared coefficients = sum of squared input / N
        // (for orthonormal DCT, energy is exactly preserved)
        let input: [u8; GRADIENT_BINS] = {
            let mut arr = [0u8; GRADIENT_BINS];
            for i in 0..GRADIENT_BINS {
                arr[i] = (i * 8) as u8;
            }
            arr
        };

        let full_coeffs = {
            // Compute all 32 coefficients for energy check
            let n = GRADIENT_BINS as f64;
            let mut c = [0.0f64; GRADIENT_BINS];
            for k in 0..GRADIENT_BINS {
                let mut sum = 0.0;
                for (idx, &x) in input.iter().enumerate() {
                    let angle = PI * (2.0 * idx as f64 + 1.0) * k as f64 / (2.0 * n);
                    sum += x as f64 * angle.cos();
                }
                let scale = if k == 0 {
                    (1.0 / n).sqrt()
                } else {
                    (2.0 / n).sqrt()
                };
                c[k] = sum * scale;
            }
            c
        };

        let input_energy: f64 = input.iter().map(|&x| (x as f64) * (x as f64)).sum();
        let dct_energy: f64 = full_coeffs.iter().map(|&x| x * x).sum();

        assert!(
            (input_energy - dct_energy).abs() / input_energy < 0.001,
            "Energy mismatch: input={}, dct={}",
            input_energy,
            dct_energy
        );

        // Check that first 16 coefficients capture >99% of energy
        let first_16_energy: f64 = full_coeffs[..16].iter().map(|&x| x * x).sum();
        let retention = first_16_energy / dct_energy;
        assert!(
            retention > 0.99,
            "First 16 coefficients should capture >99% energy, got {:.4}",
            retention
        );
    }

    #[test]
    fn test_signature_roundtrip() {
        let elevations: Vec<f64> = (0..100).map(|i| 500.0 + i as f64 * 3.0).collect();
        let distances: Vec<f64> = (0..100).map(|i| i as f64 * 50.0).collect();

        let sig = generate_signature_v2(&elevations, &distances, 0, false, 2).unwrap();
        assert_eq!(sig.version, SIGNATURE_VERSION);
        assert_eq!(sig.bytes[0], 0x02);

        // Decode from bytes
        let decoded = SignatureV2::from_bytes(sig.bytes).unwrap();
        assert_eq!(decoded.vert_m, sig.vert_m);
        assert_eq!(decoded.distance_m, sig.distance_m);
        assert_eq!(decoded.distance_m, 4_950);
        assert_eq!(decoded.h3_anchor, 0);

        // DCT coefficients should survive f16 roundtrip with minimal loss
        for i in 0..DCT_COEFFS {
            let diff = (sig.dct_coeffs[i] - decoded.dct_coeffs[i]).abs();
            assert!(
                diff < 1.0, // f16 precision for values up to ~700
                "DCT coeff {} diverged: {} vs {} (diff={})",
                i,
                sig.dct_coeffs[i],
                decoded.dct_coeffs[i],
                diff
            );
        }
    }

    #[test]
    fn test_hex_roundtrip() {
        let elevations: Vec<f64> = (0..50).map(|i| 100.0 + i as f64 * 2.0).collect();
        let distances: Vec<f64> = (0..50).map(|i| i as f64 * 30.0).collect();

        let sig =
            generate_signature_v2(&elevations, &distances, 0x8a2a1072b59ffff, true, 1).unwrap();
        let hex_str = sig.hex();
        assert_eq!(hex_str.len(), 128);

        let decoded = SignatureV2::from_hex(&hex_str).unwrap();
        assert_eq!(decoded.h3_anchor, 0x8a2a1072b59ffff);
        assert_eq!(decoded.version, 0x02);
    }

    #[test]
    fn test_identical_signatures_match() {
        let elevations: Vec<f64> = (0..100).map(|i| 500.0 + i as f64 * 5.0).collect();
        let distances: Vec<f64> = (0..100).map(|i| i as f64 * 40.0).collect();

        let sig1 = generate_signature_v2(&elevations, &distances, 0, false, 2).unwrap();
        let sig2 = generate_signature_v2(&elevations, &distances, 0, false, 2).unwrap();

        let d = sig1.dct_distance(&sig2);
        assert!(
            d < 0.001,
            "Identical signatures should have distance ~0, got {}",
            d
        );

        match sig1.match_against(&sig2) {
            MatchResult::Match { confidence } => {
                assert!(confidence > 0.99, "Should have high confidence");
            }
            other => panic!("Expected Match, got {:?}", other),
        }
    }

    #[test]
    fn test_different_gradients_no_match() {
        let elev1: Vec<f64> = (0..100).map(|i| 500.0 + i as f64 * 3.0).collect(); // 6% avg
        let elev2: Vec<f64> = (0..100).map(|i| 500.0 + i as f64 * 10.0).collect(); // 20% avg
        let distances: Vec<f64> = (0..100).map(|i| i as f64 * 50.0).collect();

        let sig1 = generate_signature_v2(&elev1, &distances, 0, false, 2).unwrap();
        let sig2 = generate_signature_v2(&elev2, &distances, 0, false, 2).unwrap();

        let d = sig1.dct_distance(&sig2);
        assert!(
            d > 0.12,
            "Very different gradients should have d_rel > 0.12, got {}",
            d
        );
    }

    #[test]
    fn test_noisy_same_climb_matches() {
        // Simulate GPS noise: same underlying climb with small perturbations
        let base: Vec<f64> = (0..200).map(|i| 400.0 + i as f64 * 2.5).collect();
        let distances: Vec<f64> = (0..200).map(|i| i as f64 * 25.0).collect();

        // Add small noise (simulating different GPS recordings of same climb)
        let noisy: Vec<f64> = base
            .iter()
            .enumerate()
            .map(|(i, &e)| e + (i as f64 * 0.7).sin() * 1.5)
            .collect();

        let sig1 = generate_signature_v2(&base, &distances, 0, false, 2).unwrap();
        let sig2 = generate_signature_v2(&noisy, &distances, 0, false, 2).unwrap();

        let d = sig1.dct_distance(&sig2);
        assert!(
            d < MATCH_THRESHOLD,
            "Same climb with GPS noise should match (d_rel={}, threshold={})",
            d,
            MATCH_THRESHOLD
        );
    }

    #[test]
    fn test_scaled_profile_not_cosine_fooled() {
        // Two profiles with same shape but 2x gradient should NOT match
        // (cosine similarity would say 1.0, relative Euclidean catches this)
        let gentle: Vec<f64> = (0..100).map(|i| 500.0 + i as f64 * 2.0).collect();
        let steep: Vec<f64> = (0..100).map(|i| 500.0 + i as f64 * 4.0).collect();
        let distances: Vec<f64> = (0..100).map(|i| i as f64 * 50.0).collect();

        let sig1 = generate_signature_v2(&gentle, &distances, 0, false, 2).unwrap();
        let sig2 = generate_signature_v2(&steep, &distances, 0, false, 2).unwrap();

        let d = sig1.dct_distance(&sig2);
        assert!(
            d > PROBABLE_MATCH_THRESHOLD,
            "2x steeper profile should have d_rel > {} (got {}), cosine would miss this",
            PROBABLE_MATCH_THRESHOLD,
            d
        );
    }

    #[test]
    fn test_geometric_gate_filters() {
        // Same shape but very different vert — should be filtered by geometric gate
        let sig1 = generate_signature_v2(
            &(0..100).map(|i| 500.0 + i as f64 * 5.0).collect::<Vec<_>>(),
            &(0..100).map(|i| i as f64 * 20.0).collect::<Vec<_>>(),
            0,
            false,
            2,
        )
        .unwrap();

        // Manually create a sig with very different vert
        let mut sig2 = sig1.clone();
        sig2.vert_m = sig1.vert_m * 3; // 3x vertical gain
        sig2.distance_m = sig1.distance_m * 3;

        match sig1.match_against(&sig2) {
            MatchResult::NoMatch => {} // expected
            other => panic!("Geometric gate should filter, got {:?}", other),
        }
    }

    #[test]
    fn test_v2_signature_deterministic() {
        // Pinned test: known inputs must always produce the same v2 signature.
        // If this test breaks, v2 signature generation changed. DO NOT update
        // the expected value without a vault migration plan.
        let elevations: Vec<f64> = (0..100).map(|i| 1000.0 + i as f64 * 3.0).collect();
        let distances: Vec<f64> = (0..100).map(|i| i as f64 * 50.0).collect();

        let sig = generate_signature_v2(&elevations, &distances, 0, false, 2).unwrap();
        let hex = sig.hex();

        // Pinned hex value — if this changes, v2 signature generation changed.
        // v2.1: distance field encodes decameters (×10m), not raw meters.
        // Prior to v2.1, distance_m overflowed u16 on rides >65km.
        let expected = "0208012901ef025800000000000000006203000080000000800000000000800080008000000080008000800000008000e9105ad1a189212e4aaad7873984334a";
        assert_eq!(
            hex, expected,
            "v2 signature must be deterministic — DO NOT change without vault migration"
        );
    }

    #[test]
    fn test_dct_zero_signs_are_canonical() {
        let positive_residual = f32::from_bits(0x0000_0001);
        let negative_residual = f32::from_bits(0x8000_0001);

        for (coefficient_index, expected_bits) in
            CANONICAL_DCT_ZERO_BITS.iter().copied().enumerate()
        {
            for residual in [negative_residual, positive_residual] {
                assert_eq!(
                    dct_coefficient_bytes(coefficient_index, residual),
                    expected_bits.to_be_bytes()
                );
            }
        }

        assert_eq!(
            dct_coefficient_bytes(13, f16::from_bits(0x0001).to_f32()),
            [0x00, 0x01]
        );
        assert_eq!(
            dct_coefficient_bytes(3, f16::from_bits(0x8001).to_f32()),
            [0x80, 0x01]
        );
    }

    #[test]
    fn test_blake3_checksum_validates() {
        let elevations: Vec<f64> = (0..50).map(|i| 200.0 + i as f64 * 4.0).collect();
        let distances: Vec<f64> = (0..50).map(|i| i as f64 * 30.0).collect();

        let sig = generate_signature_v2(&elevations, &distances, 0, true, 1).unwrap();

        // Valid signature should decode
        assert!(SignatureV2::from_bytes(sig.bytes).is_some());

        // Corrupt a byte and checksum should fail
        let mut corrupted = sig.bytes;
        corrupted[20] ^= 0xFF;
        assert!(
            SignatureV2::from_bytes(corrupted).is_none(),
            "Corrupted signature should fail checksum"
        );
    }

    #[test]
    fn test_flags_encoding() {
        let flags = SignatureFlags {
            terrain: 2, // hilly
            direction: true,
            has_power: true,
        };
        let byte = flags.encode();
        let decoded = SignatureFlags::decode(byte);
        assert_eq!(decoded.terrain, 2);
        assert!(decoded.direction);
        assert!(decoded.has_power);
    }

    #[test]
    fn test_h3_coarsening_matches_same_climb() {
        // Corpus finding: same physical climb recorded on different days lands in
        // different res-10 H3 cells due to GPS jitter (grid distance 4-31 at res-10).
        // After coarsening to res-7, these become distance 0-2.
        // Real pair from corpus: 0x8a9eae2ee22ffff vs 0x8a9eae2e8ac7fff
        // (res-10 grid distance = 21, res-7 grid distance = 1)
        let h3_a: u64 = 0x8a9eae2ee22ffff;
        let h3_b: u64 = 0x8a9eae2e8ac7fff;

        let d = h3_grid_distance(h3_a, h3_b);
        assert!(
            d.is_some(),
            "Should be able to compute distance between valid H3 cells"
        );
        assert!(
            d.unwrap() <= H3_MAX_GRID_DISTANCE,
            "Same-climb H3 cells should pass proximity gate after coarsening (got d={})",
            d.unwrap()
        );
    }

    #[test]
    fn test_h3_distant_cells_still_rejected() {
        // Cells on different continents should still be rejected after coarsening.
        // Philadelphia (res-10): 0x8a2a1072b59ffff
        // Tucson (res-10):       0x8a48e8d5a527fff
        let philly: u64 = 0x8a2a1072b59ffff;
        let tucson: u64 = 0x8a48e8d5a527fff;

        let d = h3_grid_distance(philly, tucson);
        // Either None (different base cells can't compute distance) or > 3
        match d {
            Some(dist) => assert!(
                dist > H3_MAX_GRID_DISTANCE,
                "Cross-country cells should fail proximity gate (d={})",
                dist
            ),
            None => {} // Also acceptable — can't compute distance across large gaps
        }

        let elevations: Vec<f64> = (0..100).map(|i| 500.0 + i as f64 * 3.0).collect();
        let distances: Vec<f64> = (0..100).map(|i| i as f64 * 50.0).collect();
        let philly_sig = generate_signature_v2(&elevations, &distances, philly, false, 2).unwrap();
        let tucson_sig = generate_signature_v2(&elevations, &distances, tucson, false, 2).unwrap();

        assert_eq!(
            philly_sig.match_against(&tucson_sig),
            MatchResult::NoMatch,
            "an H3 distance error must fail closed for reward-grade matching"
        );
    }
}
