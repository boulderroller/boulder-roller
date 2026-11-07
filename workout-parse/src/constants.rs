//! Constants for workout parsing.
//!
//! Sentinel values, limits, and configuration constants.

// === Sentinel Values ===
// Used to mark missing/invalid data in arrays.
// Important: 0 is a VALID value (e.g., 0W power during coasting).

pub const MISSING_U8: u8 = 0xFF;
pub const MISSING_U16: u16 = 0xFFFF;
pub const MISSING_I32: i32 = i32::MIN;
pub const MISSING_I64: i64 = i64::MIN;

// === Decompression Limits ===
// Prevent zip bombs and OOM from malicious/corrupt files.

pub const MAX_DECOMPRESSED_SIZE: usize = 100 * 1024 * 1024; // 100MB
pub const MAX_ZIP_ENTRIES: usize = 10;
pub const MAX_COMPRESSION_RATIO: usize = 100; // Applied to both gzip and zip
pub const MAX_RECURSION_DEPTH: usize = 2;

// === Activity Duration Limits ===
// OOM protection for corrupt timestamps.

pub const MAX_ACTIVITY_DURATION_S: usize = 48 * 3600; // 48 hours max

// === NP Calculation ===

pub const NP_WINDOW_S: usize = 30;
pub const PAUSE_THRESHOLD_S: i64 = 30; // Gaps > 30s treated as pauses

