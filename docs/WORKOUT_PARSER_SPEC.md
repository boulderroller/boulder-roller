# BoulderRoller Workout Parser — Technical Specification

## Overview

High-performance workout file parsing engine for BoulderRoller. Rust core with PyO3 Python bindings for server-side use. Replaces `fitparse` + `gpxpy` with a single, fast, unified parser.

**Goals:**
- Parse FIT, GPX, and TCX files at near-hardware speeds
- Extract session metadata directly when available
- **Always recompute NP/TSS/IF using server-side user FTP** (device values logged but not used)
- Support gzip/zip compressed wrappers with safety limits
- Columnar output format with zero-copy numpy integration
- Effort pattern detection (climbs, steady work, exploration)
- Tile-based spatial assignment for CAL/DUNG tokenomics

**Performance Targets:**

| Scenario | Current (Python) | Target (Rust) | Speedup |
|----------|------------------|---------------|---------|
| 3MB FIT file parse | ~800ms | <20ms | 40x |
| 500KB GPX file parse | ~400ms | <30ms | 13x |
| NP/TSS calculation | ~150ms | <3ms | 50x |
| Effort detection | ~200ms | <10ms | 20x |
| **Full pipeline** | **~1.2s** | **<50ms** | **24x** |

---

## Key Design Decisions

### 1. Metrics Policy: Server Recomputes Everything

Device-provided NP/TSS/IF are **logged but not used** for application logic. Rationale:

- Devices compute metrics using their local FTP setting, which may differ from server
- Different manufacturers use slightly different NP algorithms
- We need consistent metrics across all users for leaderboards/analytics

**Policy:**
```
Device NP/TSS/IF → stored in session.device_np_w, session.device_tss, session.device_if
Server NP/TSS/IF → computed using user's server-side FTP → used for all app logic
```

### 2. Missing Data Representation

Two-level strategy:

| Level | Representation | Example |
|-------|----------------|---------|
| **Channel missing** | `Optional[np.ndarray]` = `None` | No power meter → `pwr_w = None` |
| **Sample missing** | Sentinel value | Dropout mid-ride → `hr_bpm[i] = 255` |

**Sentinel values:**
| Type | Sentinel | Meaning |
|------|----------|---------|
| `u8` | `255` (0xFF) | Missing |
| `u16` | `65535` (0xFFFF) | Missing |
| `i32` | `i32::MIN` (-2147483648) | Missing |
| `i64` | `i64::MIN` | Missing |

**Important:** `0` is a valid value (e.g., 0W power during coasting). Sentinel means "no reading available."

**Rust constants:**
```rust
pub const MISSING_U8: u8 = 0xFF;
pub const MISSING_U16: u16 = 0xFFFF;
pub const MISSING_I32: i32 = i32::MIN;
pub const MISSING_I64: i64 = i64::MIN;
```

**Array Invariants:**
- If a channel array is present (not `None`), its length equals `n` (the record count)
- All arrays are aligned to `time_ms` by index: `pwr_w[i]` corresponds to `time_ms[i]`
- Gaps in time (pauses) are represented by gaps in `time_ms` values, not missing array elements
- Sentinel values mark "sensor dropout" within a continuous recording

**Python usage:**
```python
# Check if channel exists
if activity.pwr_w is not None:
    power = np.asarray(activity.pwr_w)
    # Mask missing samples (use integer comparison before any conversion)
    valid_mask = power != wp.MISSING_U16
    avg_power = power[valid_mask].mean()

# GPS masking - compare integers, then convert
if activity.lat_e7 is not None:
    lat_e7 = np.asarray(activity.lat_e7)
    lon_e7 = np.asarray(activity.lon_e7)
    valid_gps = lat_e7 != wp.MISSING_I32  # Integer comparison
    lat_deg = lat_e7[valid_gps] / 1e7     # Convert only valid values
    lon_deg = lon_e7[valid_gps] / 1e7
```

### 3. Multi-Session FIT Files

FIT files can contain multiple sessions (multisport, resumed activities). Policy:

- Parse **all** sessions into `Vec<SessionMeta>`
- **Primary session** = longest by `total_timer_time`
- Expose `activity.sessions: List[SessionMeta]` and `activity.primary_session: SessionMeta`
- Log warning if multiple sessions detected

### 4. Decompression Safety Limits

```rust
pub const MAX_DECOMPRESSED_SIZE: usize = 100 * 1024 * 1024;  // 100 MB
pub const MAX_ZIP_ENTRIES: usize = 10;
pub const MAX_COMPRESSION_RATIO: usize = 100;  // Reject if output/input > 100x (gzip AND zip)
pub const MAX_RECURSION_DEPTH: usize = 2;      // gzip(zip(fit)) ok, deeper = reject
```

Violations return `WpError::DecompressionLimitExceeded`.

### 5. Activity Duration Limits

```rust
pub const MAX_ACTIVITY_DURATION_S: usize = 48 * 3600;  // 48 hours max, prevents OOM on corrupt timestamps
```

If `(end_ms - start_ms) / 1000 > MAX_ACTIVITY_DURATION_S`, return `WpError::DurationLimitExceeded`. This prevents corrupt files with bogus timestamps from causing OOM during resampling.

### 6. Tile Zoom Validation

```rust
pub const MAX_TILE_ZOOM: u8 = 22;  // ~0.6m resolution at equator, sufficient for any use case
```

Zoom values > 22 are clamped or rejected to prevent overflow in `1u64 << zoom`.

### 7. GIL Release for Async Compatibility

All parsing functions release the Python GIL:

```rust
#[pyfunction]
fn parse_file(py: Python, path: &str) -> PyResult<ParsedActivity> {
    py.allow_threads(|| {
        // All CPU-intensive work here
        internal_parse_file(path)
    }).map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e.to_string()))
}
```

This allows FastAPI's async workers to handle other requests during parsing.

### 8. NP Calculation: Pauses vs Missing Power

NP (Normalized Power) must operate on a **fixed-rate time series**. Key distinctions:

| Scenario | Data Pattern | NP Handling |
|----------|--------------|-------------|
| **Coasting** | `pwr_w[i] = 0` | Include as 0W (valid reading) |
| **Sensor dropout** | `pwr_w[i] = MISSING_U16` | Substitute with 0W for NP calc |
| **Smart recording / sparse samples** | Missing seconds but gaps ≤ `PAUSE_THRESHOLD_S` | Carry-forward last known power |
| **Pause (stopped)** | Gap in `time_ms` (e.g., 5 min jump) | Skip gap, don't inflate window |

**Algorithm:**
1. Resample to 1Hz based on `time_ms` timestamps
2. For each 1-second bucket:
   - If power samples exist: average them (treat `MISSING_U16` as 0W)
   - If no samples but within continuous recording (smart recording): carry-forward last known power
   - If timestamp gap > threshold (e.g., 30s): treat as pause, exclude from NP
3. Apply 30-second rolling average to continuous segments only
4. NP = 4th root of mean of 4th powers

**Critical:** Do NOT drop missing samples and compress time. A 1-hour ride with 10 minutes of sensor dropout is still a 1-hour ride for NP purposes, not a 50-minute ride.

**Dropout policy note:** Substituting `MISSING_U16` with 0W is intentionally conservative. If you want less punitive fitness analytics, consider an alternative policy (e.g., return `None` when power coverage is below a threshold, or invalidate rolling windows that include missing power).

**Pause detection limitation:** Splitting segments on `time_ms` gaps > `PAUSE_THRESHOLD_S` is a heuristic. Some devices keep emitting records while stopped (0 speed), and some smart-record while moving (sparse timestamps). For FIT files, a more reliable alternative is to segment on `GM_EVENT` timer start/stop (and/or use `total_timer_time`) when available; keep the gap heuristic as the fallback (and for GPX/TCX).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Python Backend (FastAPI)                     │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────────┐   │
│  │ /rides/upload │  │ ride_processor│  │ pattern_engine    │   │
│  └───────┬───────┘  └───────┬───────┘  └─────────┬─────────┘   │
│          │                  │                    │              │
│          └──────────────────┼────────────────────┘              │
│                             ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              workout_parse (PyO3 module)                  │  │
│  │                                                           │  │
│  │  parse_file(path) -> ParsedActivity     [GIL released]    │  │
│  │  parse_bytes(data) -> ParsedActivity    [GIL released]    │  │
│  │  detect_patterns(activity, config) -> List[Pattern]       │  │
│  │  compute_metrics(activity, ftp) -> ComputedMetrics        │  │
│  │                                                           │  │
│  └──────────────────────────────────────────────────────────┘  │
│                             │                                   │
│                             │ Zero-copy numpy arrays            │
│                             ▼                                   │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────────┐   │
│  │ Postgres      │  │ Solana RPC    │  │ Analytics         │   │
│  │ (rides table) │  │ (mint DUNG)   │  │ (zones, fitness)  │   │
│  └───────────────┘  └───────────────┘  └───────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Structures

### ParsedActivity (main output)

```python
@dataclass
class ParsedActivity:
    """Complete parsed activity with records and metadata."""

    # Record count
    n: int

    # Columnar record data (numpy arrays via buffer protocol)
    # None if channel not present in file
    time_ms: np.ndarray[np.int64]            # Unix milliseconds (always present)
    lat_e7: Optional[np.ndarray[np.int32]]   # Latitude * 10^7, MISSING_I32 for gaps
    lon_e7: Optional[np.ndarray[np.int32]]   # Longitude * 10^7
    alt_mm: Optional[np.ndarray[np.int32]]   # Altitude in millimeters
    speed_mmps: Optional[np.ndarray[np.int32]]  # Speed in mm/s
    hr_bpm: Optional[np.ndarray[np.uint8]]   # Heart rate, 255 = missing
    cad_rpm: Optional[np.ndarray[np.uint8]]  # Cadence, 255 = missing
    pwr_w: Optional[np.ndarray[np.uint16]]   # Power in watts, 65535 = missing
    dist_m: Optional[np.ndarray[np.float32]] # Cumulative distance in meters (f32 for range)
    temp_c: Optional[np.ndarray[np.int8]]    # Temperature, -128 = missing
    grade_pct_x100: Optional[np.ndarray[np.int16]]  # Grade * 100 (e.g., 850 = 8.5%)

    # Sessions (FIT files can have multiple)
    sessions: List[SessionMeta]
    primary_session: SessionMeta  # Longest by timer_time

    # Laps
    laps: List[LapMeta]

    # Device info
    device: DeviceInfo

    # File metadata
    file_type: str  # "fit", "gpx", "tcx"
    sport: str      # "cycling", "running", etc.
    sub_sport: str  # "road", "mountain", "virtual", etc.
```

### SessionMeta

```python
@dataclass
class SessionMeta:
    """Device-reported session summary extracted from file.

    Not canonical for analytics: use `ComputedMetrics` for all application logic.
    """

    # Timing
    started_at: datetime              # Activity start (UTC)
    ended_at: datetime                # Activity end (UTC)
    total_elapsed_time_s: float       # Wall clock time
    total_timer_time_s: float         # Moving time (excludes pauses)

    # Distance & elevation
    total_distance_m: float
    total_ascent_m: int
    total_descent_m: int

    # Device-reported metrics (logged, not used for app logic)
    device_avg_power_w: Optional[int]
    device_max_power_w: Optional[int]
    device_np_w: Optional[int]          # Device's NP calculation
    device_tss: Optional[float]         # Device's TSS (uses device FTP)
    device_if: Optional[float]          # Device's IF

    # Heart rate (from device)
    avg_hr_bpm: Optional[int]
    max_hr_bpm: Optional[int]

    # Cadence (from device)
    avg_cadence_rpm: Optional[int]
    max_cadence_rpm: Optional[int]

    # Speed (from device)
    avg_speed_mps: Optional[float]
    max_speed_mps: Optional[float]

    # Energy (from device)
    total_calories: Optional[int]
    total_work_kj: Optional[int]

    # Sport classification
    sport: int       # FIT sport enum
    sub_sport: int   # FIT sub_sport enum
```

### ComputedMetrics (server-calculated)

```python
@dataclass
class ComputedMetrics:
    """Canonical metrics computed server-side using user's FTP."""

    # Computed with user's server-side FTP
    ftp_used: int
    normalized_power_w: Optional[int]
    training_stress_score: Optional[float]
    intensity_factor: Optional[float]

    # Aggregates from records
    avg_power_w: Optional[int]
    max_power_w: Optional[int]
    avg_hr_bpm: Optional[int]
    max_hr_bpm: Optional[int]
    avg_cadence_rpm: Optional[int]
    max_cadence_rpm: Optional[int]

    # Elevation (calculated with smoothing)
    elevation_gain_m: int
    elevation_loss_m: int

    # Distance
    total_distance_m: float

    # Derived
    kcals: int
    work_kj: Optional[int]
```

**Type-stub guidance:** In `python/workout_parse/__init__.pyi`, add docstrings on `SessionMeta` fields explicitly warning they are device-reported and should not be used for analysis. Point developers to `ComputedMetrics` as the canonical source.

### LapMeta

```python
@dataclass
class LapMeta:
    """Per-lap metrics from FIT lap records."""

    lap_number: int
    start_time: datetime
    end_time: datetime
    start_idx: int   # Index into record arrays
    end_idx: int

    total_elapsed_time_s: float
    total_timer_time_s: float
    total_distance_m: float
    total_ascent_m: int
    total_descent_m: int

    avg_power_w: Optional[int]
    max_power_w: Optional[int]
    normalized_power_w: Optional[int]

    avg_hr_bpm: Optional[int]
    max_hr_bpm: Optional[int]

    avg_cadence_rpm: Optional[int]
    max_cadence_rpm: Optional[int]

    avg_speed_mps: Optional[float]
    max_speed_mps: Optional[float]

    total_calories: Optional[int]

    trigger: str  # "manual", "distance", "position", "time", "session_end"
```

### DeviceInfo

```python
@dataclass
class DeviceInfo:
    """Device that recorded the activity."""

    manufacturer: Optional[str]       # "garmin", "wahoo", "zwift", etc.
    product: Optional[str]            # "edge_840", "kickr", etc.
    serial_number: Optional[str]
    software_version: Optional[str]
```

---

## Python API

### Basic Usage

```python
import workout_parse as wp
import numpy as np

# Parse from file path (GIL released during parse)
activity = wp.parse_file("/path/to/ride.fit")

# Parse from bytes (e.g., from HTTP upload)
activity = wp.parse_bytes(file_bytes)

# Auto-detects format, handles gzip/zip transparently
# Raises wp.ParseError on failure
# Raises wp.DecompressionLimitExceeded on zip bombs
```

### Computing Metrics with User FTP

```python
# Get user's FTP from database
user_ftp = user.get("ftp_w") or 200

# Compute metrics server-side (always use this, not device values)
metrics = wp.compute_metrics(activity, ftp=user_ftp)

print(f"NP: {metrics.normalized_power_w} W")
print(f"TSS: {metrics.training_stress_score:.1f}")
print(f"IF: {metrics.intensity_factor:.2f}")

# Device values are available but should only be logged
print(f"Device NP (logged only): {activity.primary_session.device_np_w}")
```

### Working with Record Arrays

```python
# Zero-copy numpy arrays
time_ms = np.asarray(activity.time_ms)

# Check if channel exists before accessing
if activity.pwr_w is not None:
    power = np.asarray(activity.pwr_w)

    # Mask missing samples (sentinel = 65535)
    valid_mask = power != wp.MISSING_U16
    valid_power = power[valid_mask]

    print(f"Power samples: {valid_mask.sum()} / {len(power)}")
    print(f"Avg power: {valid_power.mean():.0f} W")

# GPS data
if activity.lat_e7 is not None:
    lat_e7 = np.asarray(activity.lat_e7)
    lon_e7 = np.asarray(activity.lon_e7)

    # Mask missing GPS points (integer comparison before float conversion)
    valid_gps = lat_e7 != wp.MISSING_I32
    lat = lat_e7[valid_gps] / 1e7  # float64 by default; avoid float32 for coords
    lon = lon_e7[valid_gps] / 1e7
```

### Multi-Session Handling

```python
# Check for multiple sessions
if len(activity.sessions) > 1:
    logger.warning(f"FIT file has {len(activity.sessions)} sessions, using primary")

# Primary session is longest by timer_time
session = activity.primary_session

# Or iterate all sessions
for i, sess in enumerate(activity.sessions):
    print(f"Session {i}: {sess.sport} - {sess.total_timer_time_s/60:.0f} min")
```

### Pattern Detection

```python
config = wp.PatternConfig(
    # User profile
    ftp_watts=280,
    lthr_bpm=165,
    weight_kg=75.0,

    # Climb detection
    min_climb_grade_pct=3.0,
    min_climb_duration_s=60,
    min_climb_vert_m=20,

    # Steady effort detection
    steady_power_cv_max=0.15,
    steady_min_duration_s=120,

    # Tile system
    tile_zoom=14,
)

patterns = wp.detect_patterns(activity, config)

for p in patterns:
    if p.pattern_type == "climb":
        print(f"Climb: {p.vert_m}m @ {p.avg_grade_pct:.1f}%")
    elif p.pattern_type == "steady":
        print(f"Steady: {p.duration_s}s @ {p.avg_power_w}W")
```

### Integration with Existing Code

```python
# In ride_processor.py

import workout_parse as wp
from app.services.ride_metrics import RideMetrics

async def process_upload(file_bytes: bytes, user_id: str, repo):
    # Parse file (GIL released - won't block other async tasks)
    try:
        activity = wp.parse_bytes(file_bytes)
    except wp.DecompressionLimitExceeded:
        raise HTTPException(400, "File too large or potentially malicious")
    except wp.ParseError as e:
        raise HTTPException(400, f"Invalid file: {e}")

    # Get user profile
    user = await repo.get_user_by_id(user_id)
    user_ftp = user.get("ftp_w") or 200
    user_weight = user.get("weight_kg") or 75.0

    # Compute metrics with server FTP (not device values)
    metrics = wp.compute_metrics(activity, ftp=user_ftp)

    # Build RideMetrics for storage
    ride_metrics = RideMetrics(
        duration_sec=int(activity.primary_session.total_timer_time_s),
        distance_m=metrics.total_distance_m,
        elevation_gain_m=metrics.elevation_gain_m,
        tss=metrics.training_stress_score or estimate_tss_fallback(activity, metrics),
        kcals=metrics.kcals,
        avg_power_w=metrics.avg_power_w,
        max_power_w=metrics.max_power_w,
        normalized_power_w=metrics.normalized_power_w,
        avg_hr_bpm=metrics.avg_hr_bpm,
        max_hr_bpm=metrics.max_hr_bpm,
        avg_speed_mps=activity.primary_session.avg_speed_mps,
        avg_cadence_rpm=metrics.avg_cadence_rpm,
    )

    # Detect patterns
    config = wp.PatternConfig(
        ftp_watts=user_ftp,
        weight_kg=user_weight,
    )
    patterns = wp.detect_patterns(activity, config)

    return activity, ride_metrics, patterns
```

---

## Rust Implementation

### Repository Structure

```
workout-parse/
├── Cargo.toml
├── src/
│   ├── lib.rs              # PyO3 module entry point
│   ├── error.rs            # Error types
│   ├── constants.rs        # Sentinel values, limits
│   ├── activity.rs         # ParsedActivity struct
│   ├── session.rs          # SessionMeta, LapMeta, DeviceInfo
│   ├── metrics.rs          # NP/TSS/IF calculation (O(n) algorithms)
│   ├── sniff.rs            # Format detection
│   ├── decompress.rs       # gzip/zip with safety limits
│   ├── resample.rs         # 1Hz resampling for NP
│   ├── fit/
│   │   ├── mod.rs
│   │   ├── decode.rs
│   │   ├── profile.rs      # FIT SDK constants
│   │   └── session.rs
│   ├── xml/
│   │   ├── mod.rs
│   │   ├── gpx.rs
│   │   └── tcx.rs
│   ├── patterns/
│   │   ├── mod.rs
│   │   ├── climb.rs
│   │   ├── steady.rs
│   │   ├── sprint.rs
│   │   └── tiles.rs
│   └── pyo3/
│       ├── mod.rs          # Python bindings with allow_threads
│       └── numpy.rs
├── python/
│   └── workout_parse/
│       ├── __init__.py
│       └── __init__.pyi    # Type stubs
└── tests/
    ├── fixtures/
    └── *.rs
```

### Cargo.toml

```toml
[package]
name = "workout_parse"
version = "0.1.0"
edition = "2021"

[lib]
name = "workout_parse"
crate-type = ["cdylib", "rlib"]

[dependencies]
# Core
thiserror = "1"
bitflags = "2"

# FIT parsing
memmap2 = "0.9"

# XML parsing (GPX/TCX)
quick-xml = { version = "0.36", features = ["encoding"] }

# Compression (pure Rust backends - no system deps)
flate2 = "1"  # Uses miniz_oxide by default
zip = { version = "2", default-features = false, features = ["deflate"] }

# Python bindings
pyo3 = { version = "0.22", features = ["extension-module"] }
numpy = "0.22"

# DateTime handling
chrono = { version = "0.4", features = ["serde"] }

[dev-dependencies]
criterion = "0.5"

[[bench]]
name = "parse_bench"
harness = false

[profile.release]
lto = true
codegen-units = 1
```

### Constants (src/constants.rs)

```rust
//! Sentinel values and safety limits

// Sentinel values for missing data
pub const MISSING_U8: u8 = 0xFF;
pub const MISSING_U16: u16 = 0xFFFF;
pub const MISSING_I8: i8 = i8::MIN;
pub const MISSING_I16: i16 = i16::MIN;
pub const MISSING_I32: i32 = i32::MIN;
pub const MISSING_I64: i64 = i64::MIN;

// Decompression safety limits
pub const MAX_DECOMPRESSED_SIZE: usize = 100 * 1024 * 1024;  // 100 MB
pub const MAX_ZIP_ENTRIES: usize = 10;
pub const MAX_COMPRESSION_RATIO: usize = 100;  // Applied to both gzip and zip
pub const MAX_RECURSION_DEPTH: usize = 2;

// Activity duration limits (OOM protection)
pub const MAX_ACTIVITY_DURATION_S: usize = 48 * 3600;  // 48 hours max

// NP calculation
pub const NP_WINDOW_S: usize = 30;
pub const PAUSE_THRESHOLD_S: i64 = 30;  // Gaps > 30s treated as pauses

// Tile system
pub const MAX_TILE_ZOOM: u8 = 22;

// FIT epoch offset
pub const FIT_EPOCH_OFFSET_S: i64 = 631065600;  // 1989-12-31 00:00:00 UTC
```

### Error Types (src/error.rs)

```rust
use thiserror::Error;

#[derive(Error, Debug)]
pub enum WpError {
    #[error("Invalid UTF-8 in path")]
    BadUtf8Path,

    #[error("Unknown or unsupported file format")]
    UnknownFormat,

    #[error("File truncated or corrupt: {0}")]
    Truncated(String),

    #[error("Missing FIT definition for local message {0}")]
    MissingFitDefinition(u8),

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Zip error: {0}")]
    Zip(String),

    #[error("XML parse error: {0}")]
    Xml(String),

    #[error("Decompression limit exceeded: {0}")]
    DecompressionLimitExceeded(String),

    #[error("Duration limit exceeded: {0}")]
    DurationLimitExceeded(String),

    #[error("No valid records found in file")]
    NoRecords,

    #[error("No valid sessions found in file")]
    NoSessions,
}
```

### Safe Decompression (src/decompress.rs)

```rust
use crate::constants::*;
use crate::error::WpError;
use flate2::read::GzDecoder;
use std::io::Read;
use zip::ZipArchive;

/// Decompression result - either owned (decompressed) or borrowed (not compressed)
pub enum DecompressResult<'a> {
    Borrowed(&'a [u8]),
    Owned(Vec<u8>),
}

impl<'a> DecompressResult<'a> {
    pub fn as_slice(&self) -> &[u8] {
        match self {
            DecompressResult::Borrowed(s) => s,
            DecompressResult::Owned(v) => v,
        }
    }
}

/// Decompress data if needed, with safety limits.
/// Returns borrowed slice if not compressed (zero-copy).
pub fn decompress_safe(data: &[u8], depth: usize) -> Result<DecompressResult<'_>, WpError> {
    if depth > MAX_RECURSION_DEPTH {
        return Err(WpError::DecompressionLimitExceeded(
            format!("Max recursion depth {} exceeded", MAX_RECURSION_DEPTH)
        ));
    }

    if data.len() < 4 {
        return Ok(DecompressResult::Borrowed(data));
    }

    // Gzip: 1F 8B
    if data[0] == 0x1F && data[1] == 0x8B {
        let decompressed = decompress_gzip_safe(data)?;
        // Recurse to handle nested compression
        return match decompress_safe(&decompressed, depth + 1)? {
            DecompressResult::Borrowed(_) => Ok(DecompressResult::Owned(decompressed)),
            DecompressResult::Owned(v) => Ok(DecompressResult::Owned(v)),
        };
    }

    // Zip: 50 4B 03 04
    if &data[0..4] == b"PK\x03\x04" {
        let decompressed = decompress_zip_safe(data)?;
        return match decompress_safe(&decompressed, depth + 1)? {
            DecompressResult::Borrowed(_) => Ok(DecompressResult::Owned(decompressed)),
            DecompressResult::Owned(v) => Ok(DecompressResult::Owned(v)),
        };
    }

    // Not compressed - return borrowed reference (zero-copy)
    Ok(DecompressResult::Borrowed(data))
}

fn decompress_gzip_safe(data: &[u8]) -> Result<Vec<u8>, WpError> {
    let mut decoder = GzDecoder::new(data);
    let mut output = Vec::new();
    let mut buf = [0u8; 65536];
    let input_size = data.len();

    loop {
        let n = decoder.read(&mut buf).map_err(WpError::Io)?;
        if n == 0 {
            break;
        }

        output.extend_from_slice(&buf[..n]);

        // Size limit
        if output.len() > MAX_DECOMPRESSED_SIZE {
            return Err(WpError::DecompressionLimitExceeded(
                format!("Decompressed size exceeds {} bytes", MAX_DECOMPRESSED_SIZE)
            ));
        }

        // Ratio limit
        if input_size > 0 && output.len() / input_size > MAX_COMPRESSION_RATIO {
            return Err(WpError::DecompressionLimitExceeded(
                format!("Compression ratio exceeds {}x (potential bomb)", MAX_COMPRESSION_RATIO)
            ));
        }
    }

    Ok(output)
}

fn decompress_zip_safe(data: &[u8]) -> Result<Vec<u8>, WpError> {
    let cursor = std::io::Cursor::new(data);
    let mut archive = ZipArchive::new(cursor)
        .map_err(|e| WpError::Zip(e.to_string()))?;

    if archive.len() > MAX_ZIP_ENTRIES {
        return Err(WpError::DecompressionLimitExceeded(
            format!("Zip has {} entries, max is {}", archive.len(), MAX_ZIP_ENTRIES)
        ));
    }

    // Find best candidate file
    let mut best_idx: Option<usize> = None;
    for i in 0..archive.len() {
        let file = archive.by_index(i)
            .map_err(|e| WpError::Zip(e.to_string()))?;
        let name = file.name().to_lowercase();

        if name.ends_with(".fit") || name.ends_with(".gpx") || name.ends_with(".tcx") {
            best_idx = Some(i);
            break;
        }
        if best_idx.is_none() && !name.ends_with('/') {
            best_idx = Some(i);
        }
    }

    let idx = best_idx.ok_or_else(|| WpError::Zip("Empty or no suitable files".into()))?;

    let mut file = archive.by_index(idx)
        .map_err(|e| WpError::Zip(e.to_string()))?;

    let compressed_size = file.compressed_size() as usize;
    let uncompressed_size = file.size() as usize;
    let wrapper_size = data.len();

    // Size limit
    if uncompressed_size > MAX_DECOMPRESSED_SIZE {
        return Err(WpError::DecompressionLimitExceeded(
            format!("Uncompressed size {} exceeds limit", uncompressed_size)
        ));
    }

    // Ratio limit (also check zip, not just gzip).
    // Note: header sizes are not fully trustworthy; treat this as best-effort fast-fail.
    if compressed_size > 0 && uncompressed_size > compressed_size.saturating_mul(MAX_COMPRESSION_RATIO) {
        return Err(WpError::DecompressionLimitExceeded(
            format!("Zip ratio exceeds {}x (potential bomb)", MAX_COMPRESSION_RATIO)
        ));
    }

    let mut output = Vec::with_capacity(uncompressed_size.min(MAX_DECOMPRESSED_SIZE));
    let mut buf = [0u8; 65536];

    loop {
        let n = file.read(&mut buf).map_err(WpError::Io)?;
        if n == 0 {
            break;
        }

        output.extend_from_slice(&buf[..n]);

        if output.len() > MAX_DECOMPRESSED_SIZE {
            return Err(WpError::DecompressionLimitExceeded(
                format!("Decompressed size exceeds {} bytes", MAX_DECOMPRESSED_SIZE)
            ));
        }

        // Ratio limit while streaming (defense-in-depth vs forged headers).
        // Prefer actual wrapper size (cannot be forged); also enforce entry ratio when available.
        if wrapper_size > 0 && output.len() > wrapper_size.saturating_mul(MAX_COMPRESSION_RATIO) {
            return Err(WpError::DecompressionLimitExceeded(
                format!("Zip ratio exceeds {}x (potential bomb)", MAX_COMPRESSION_RATIO)
            ));
        }
        if compressed_size > 0 && output.len() > compressed_size.saturating_mul(MAX_COMPRESSION_RATIO) {
            return Err(WpError::DecompressionLimitExceeded(
                format!("Zip ratio exceeds {}x (potential bomb)", MAX_COMPRESSION_RATIO)
            ));
        }
    }

    Ok(output)
}
```

### O(n) NP Calculation (src/metrics.rs)

```rust
use crate::constants::*;
use crate::error::WpError;

/// Represents a continuous segment of riding (between pauses).
/// Internal to crate - not exposed in Python API.
pub(crate) struct Segment {
    pub(crate) start_s: usize,
    pub(crate) end_s: usize,
    pub(crate) power: Vec<u16>,  // 1Hz power values, 0 for coasting/dropout
}

/// Resample power data to 1Hz for accurate NP calculation.
///
/// Key behaviors:
/// - Bins samples into 1-second buckets
/// - Missing samples (MISSING_U16) within continuous riding -> treated as 0W
/// - No samples in a given second (smart recording) -> carry-forward last known power
/// - Gaps > PAUSE_THRESHOLD_S -> segment boundary (pause)
/// - Returns segments, not a single array, to handle pauses correctly
pub(crate) fn resample_power_1hz(
    time_ms: &[i64],
    power_w: &[u16],
) -> Result<Vec<Segment>, WpError> {
    if time_ms.len() != power_w.len() || time_ms.is_empty() {
        return Ok(vec![]);
    }

    let start_ms = time_ms[0];
    let end_ms = time_ms[time_ms.len() - 1];

    // Guard against corrupt timestamps (end before or equal to start)
    if end_ms <= start_ms {
        return Ok(vec![]);  // No valid duration
    }

    let duration_s = ((end_ms - start_ms) / 1000) as usize;

    // OOM protection: reject corrupt files with huge timestamp spans
    if duration_s > MAX_ACTIVITY_DURATION_S {
        return Err(WpError::DurationLimitExceeded(
            format!("Activity span {}s exceeds max {}s", duration_s, MAX_ACTIVITY_DURATION_S)
        ));
    }

    if duration_s < NP_WINDOW_S {
        return Ok(vec![]);
    }

    // First pass: identify segment boundaries (pauses)
    let mut segment_boundaries: Vec<usize> = vec![0];  // Start indices
    for i in 1..time_ms.len() {
        let gap_ms = time_ms[i] - time_ms[i - 1];
        if gap_ms > PAUSE_THRESHOLD_S * 1000 {
            segment_boundaries.push(i);
        }
    }
    segment_boundaries.push(time_ms.len());  // End sentinel

    // Second pass: build 1Hz segments
    let mut segments: Vec<Segment> = Vec::new();

    for w in segment_boundaries.windows(2) {
        let seg_start_idx = w[0];
        let seg_end_idx = w[1];

        if seg_end_idx <= seg_start_idx {
            continue;
        }

        let seg_start_ms = time_ms[seg_start_idx];
        let seg_end_ms = time_ms[seg_end_idx - 1];

        // Guard against non-monotonic timestamps within segment
        if seg_end_ms <= seg_start_ms {
            continue;  // Skip corrupt segment
        }

        let seg_duration_s = ((seg_end_ms - seg_start_ms) / 1000) as usize + 1;

        if seg_duration_s < NP_WINDOW_S {
            continue;  // Segment too short for NP
        }

        // Bin samples into 1-second buckets
        let mut bucket_sums: Vec<u64> = vec![0; seg_duration_s];
        let mut bucket_counts: Vec<u32> = vec![0; seg_duration_s];

        for i in seg_start_idx..seg_end_idx {
            let bucket = ((time_ms[i] - seg_start_ms) / 1000) as usize;
            if bucket < seg_duration_s {
                let p = power_w[i];
                // MISSING_U16 -> treat as 0W (sensor dropout)
                // 0 -> valid 0W (coasting)
                let effective_power = if p == MISSING_U16 { 0 } else { p };
                bucket_sums[bucket] += effective_power as u64;
                bucket_counts[bucket] += 1;
            }
        }

        // Build 1Hz power array
        let mut power_1hz: Vec<u16> = Vec::with_capacity(seg_duration_s);

        // Seed carry-forward with the first available bucket average (if any) to avoid leading 0W
        // when a segment begins with sparse ("smart recording") samples.
        let mut last_power: u16 = 0;
        for i in 0..seg_duration_s {
            if bucket_counts[i] > 0 {
                last_power = (bucket_sums[i] / bucket_counts[i] as u64) as u16;
                break;
            }
        }

        for i in 0..seg_duration_s {
            if bucket_counts[i] > 0 {
                last_power = (bucket_sums[i] / bucket_counts[i] as u64) as u16;
            }
            // No samples in this second (smart recording) -> hold-last-value.
            // 0W is reserved for explicit readings (coasting) and MISSING_U16 substitution.
            power_1hz.push(last_power);
        }

        let start_s = ((seg_start_ms - start_ms) / 1000) as usize;
        segments.push(Segment {
            start_s,
            end_s: start_s + seg_duration_s,
            power: power_1hz,
        });
    }

    Ok(segments)
}

/// Calculate Normalized Power from segments.
///
/// NP is calculated per-segment, then combined weighted by segment duration.
/// This correctly handles pauses without inflating NP.
pub(crate) fn calculate_np(segments: &[Segment]) -> Option<f32> {
    if segments.is_empty() {
        return None;
    }

    let mut total_fourth_power_sum: f64 = 0.0;
    let mut total_windows: usize = 0;

    for seg in segments {
        if seg.power.len() < NP_WINDOW_S {
            continue;
        }

        // O(n) sliding window within segment
        let mut window_sum: u64 = seg.power[..NP_WINDOW_S]
            .iter()
            .map(|&p| p as u64)
            .sum();

        // First window
        let avg = window_sum as f64 / NP_WINDOW_S as f64;
        total_fourth_power_sum += avg.powi(4);
        total_windows += 1;

        // Slide window
        for i in NP_WINDOW_S..seg.power.len() {
            window_sum += seg.power[i] as u64;
            window_sum -= seg.power[i - NP_WINDOW_S] as u64;
            let avg = window_sum as f64 / NP_WINDOW_S as f64;
            total_fourth_power_sum += avg.powi(4);
            total_windows += 1;
        }
    }

    if total_windows == 0 {
        return None;
    }

    // NP = 4th root of mean of 4th powers
    let mean_fourth = total_fourth_power_sum / total_windows as f64;
    Some(mean_fourth.powf(0.25) as f32)
}

/// Calculate TSS from NP and FTP.
/// TSS = (duration_s * NP * IF) / (FTP * 3600) * 100
pub fn calculate_tss(duration_s: u32, np: f32, ftp: f32) -> f32 {
    if ftp <= 0.0 {
        return 0.0;
    }
    let intensity_factor = np / ftp;
    (duration_s as f32 * np * intensity_factor) / (ftp * 3600.0) * 100.0
}

/// Calculate Intensity Factor.
pub fn calculate_if(np: f32, ftp: f32) -> f32 {
    if ftp <= 0.0 {
        return 0.0;
    }
    np / ftp
}

/// Estimate TSS from HR when no power data available.
pub fn estimate_tss_from_hr(duration_s: u32, avg_hr: u8, max_hr: u8) -> f32 {
    if max_hr == 0 || avg_hr == 0 {
        return 0.0;
    }
    let hr_ratio = avg_hr as f32 / max_hr as f32;
    let hours = duration_s as f32 / 3600.0;

    // ~50 TSS/hour at moderate intensity
    let base_tss_per_hour = 50.0;
    let intensity_mult = ((hr_ratio - 0.5) * 4.0).clamp(0.5, 2.0);

    hours * base_tss_per_hour * intensity_mult
}

/// Estimate TSS from duration alone (last resort).
pub fn estimate_tss_from_duration(duration_s: u32, distance_m: f32, elevation_m: f32) -> f32 {
    let hours = duration_s as f32 / 3600.0;
    let mut base_tss = 45.0 * hours;

    // Adjust for climbing
    if distance_m > 0.0 {
        let gradient_factor = 1.0 + (elevation_m / distance_m) * 10.0;
        base_tss *= gradient_factor.min(1.5);
    }

    base_tss
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_np_steady_state() {
        // 60 seconds of 200W steady state
        let seg = Segment {
            start_s: 0,
            end_s: 60,
            power: vec![200; 60],
        };
        let np = calculate_np(&[seg]).unwrap();
        assert!((np - 200.0).abs() < 1.0);
    }

    #[test]
    fn test_np_variability() {
        // Alternating 100W and 300W should give NP > avg (200W)
        let mut power = Vec::with_capacity(120);
        for _ in 0..60 {
            power.push(100);
            power.push(300);
        }
        let seg = Segment { start_s: 0, end_s: 120, power };
        let np = calculate_np(&[seg]).unwrap();
        assert!(np > 200.0); // NP penalizes variability
    }

    #[test]
    fn test_np_with_pause() {
        // Two 60-second segments with a pause between them
        // Pause should NOT inflate NP
        let seg1 = Segment { start_s: 0, end_s: 60, power: vec![200; 60] };
        let seg2 = Segment { start_s: 3660, end_s: 3720, power: vec![200; 60] };
        let np = calculate_np(&[seg1, seg2]).unwrap();
        // NP should be ~200W, not inflated by the pause
        assert!((np - 200.0).abs() < 1.0);
    }

    #[test]
    fn test_np_sensor_dropout_as_zero() {
        // Sensor dropout within segment -> treated as 0W
        // This should lower NP
        let mut power = vec![200u16; 60];
        power[30] = 0; // Dropout became 0W during resampling
        let seg = Segment { start_s: 0, end_s: 60, power };
        let np = calculate_np(&[seg]).unwrap();
        assert!(np < 200.0); // Lower than steady 200W
    }

    #[test]
    fn test_tss_one_hour_at_ftp() {
        // 1 hour at FTP = 100 TSS
        let tss = calculate_tss(3600, 250.0, 250.0);
        assert!((tss - 100.0).abs() < 1.0);
    }

    #[test]
    fn test_resample_rejects_huge_duration() {
        // Corrupt file with timestamps spanning years
        let time_ms = vec![0i64, 1_000_000_000_000i64]; // ~31 years
        let power_w = vec![200u16, 200u16];
        let result = resample_power_1hz(&time_ms, &power_w);
        assert!(result.is_err());
    }
}
```

### Tile Math with Edge Cases (src/patterns/tiles.rs)

```rust
use crate::constants::MAX_TILE_ZOOM;

/// Web Mercator tile key
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct TileKey {
    pub x: i32,
    pub y: i32,
    pub z: u8,
}

impl TileKey {
    /// Convert lat/lon to tile key at given zoom level.
    /// Handles edge cases: poles, antimeridian, out-of-bounds, invalid zoom.
    pub fn from_latlon(lat_deg: f64, lon_deg: f64, zoom: u8) -> Self {
        // Clamp zoom to prevent overflow in 1u64 << zoom
        let zoom = zoom.min(MAX_TILE_ZOOM);

        // Web Mercator latitude limits
        const MAX_LAT: f64 = 85.05112878;

        // Clamp latitude to valid range
        let lat = lat_deg.clamp(-MAX_LAT, MAX_LAT);

        // Normalize longitude to [-180, 180)
        let lon = ((lon_deg + 180.0).rem_euclid(360.0)) - 180.0;

        let n = (1u64 << zoom) as f64;

        // X tile
        let x = ((lon + 180.0) / 360.0 * n) as i32;

        // Y tile (Mercator projection)
        let lat_rad = lat.to_radians();
        let y = ((1.0 - lat_rad.tan().asinh() / std::f64::consts::PI) / 2.0 * n) as i32;

        // Clamp to valid tile range [0, 2^z - 1]
        let max_tile = ((1u64 << zoom) - 1) as i32;
        TileKey {
            x: x.clamp(0, max_tile),
            y: y.clamp(0, max_tile),
            z: zoom,
        }
    }

    /// String key for database storage: "z/x/y"
    pub fn to_string(&self) -> String {
        format!("{}/{}/{}", self.z, self.x, self.y)
    }

    /// Parse from string "z/x/y"
    pub fn from_string(s: &str) -> Option<Self> {
        let parts: Vec<&str> = s.split('/').collect();
        if parts.len() != 3 {
            return None;
        }
        let z: u8 = parts[0].parse().ok()?;
        if z > MAX_TILE_ZOOM {
            return None;
        }
        Some(TileKey {
            z,
            x: parts[1].parse().ok()?,
            y: parts[2].parse().ok()?,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_tile_basic() {
        // NYC at zoom 14
        let tile = TileKey::from_latlon(40.7128, -74.0060, 14);
        assert_eq!(tile.z, 14);
        assert!(tile.x > 0 && tile.x < 16384);
        assert!(tile.y > 0 && tile.y < 16384);
    }

    #[test]
    fn test_tile_poles() {
        // North pole (should clamp lat to ~85)
        let tile = TileKey::from_latlon(90.0, 0.0, 10);
        assert_eq!(tile.y, 0);

        // South pole
        let tile = TileKey::from_latlon(-90.0, 0.0, 10);
        assert_eq!(tile.y, 1023);
    }

    #[test]
    fn test_tile_antimeridian() {
        // Just west of antimeridian
        let t1 = TileKey::from_latlon(0.0, 179.9, 10);
        // Just east of antimeridian
        let t2 = TileKey::from_latlon(0.0, -179.9, 10);
        // Should be adjacent tiles (wrapping)
        assert!((t1.x - t2.x).abs() <= 1 || (t1.x - t2.x).abs() >= 1022);
    }

    #[test]
    fn test_tile_lon_180() {
        // Exactly 180 degrees (normalizes to -180)
        let tile = TileKey::from_latlon(0.0, 180.0, 10);
        assert!(tile.x >= 0 && tile.x < 1024);
    }

    #[test]
    fn test_tile_zoom_clamp() {
        // Zoom 30 should be clamped to MAX_TILE_ZOOM (22)
        let tile = TileKey::from_latlon(0.0, 0.0, 30);
        assert_eq!(tile.z, MAX_TILE_ZOOM);
    }

    #[test]
    fn test_tile_zoom_overflow_safe() {
        // This would overflow 1i32 << 31, but zoom is clamped
        let tile = TileKey::from_latlon(40.0, -74.0, 255);
        assert_eq!(tile.z, MAX_TILE_ZOOM);
        // Should not panic
    }
}
```

### PyO3 Bindings with GIL Release (src/pyo3/mod.rs)

```rust
use pyo3::prelude::*;
use pyo3::exceptions::{PyValueError, PyIOError};
use numpy::{PyArray1, PyArrayMethods};

use crate::activity::ParsedActivity;
use crate::error::WpError;
use crate::constants::*;

/// Parse a workout file from path.
/// Releases GIL during parsing for async compatibility.
#[pyfunction]
fn parse_file(py: Python<'_>, path: &str) -> PyResult<PyParsedActivity> {
    let result = py.allow_threads(|| {
        crate::parse_file(path)
    });

    match result {
        Ok(activity) => Ok(PyParsedActivity::from(activity)),
        Err(WpError::DecompressionLimitExceeded(msg)) => {
            Err(PyErr::new::<DecompressionLimitExceeded, _>(msg))
        }
        Err(WpError::DurationLimitExceeded(msg)) => {
            Err(PyErr::new::<DurationLimitExceeded, _>(msg))
        }
        Err(e) => Err(PyErr::new::<ParseError, _>(e.to_string())),
    }
}

/// Parse a workout file from bytes.
/// Releases GIL during parsing for async compatibility.
#[pyfunction]
fn parse_bytes(py: Python<'_>, data: &[u8]) -> PyResult<PyParsedActivity> {
    let result = py.allow_threads(|| {
        crate::parse_bytes(data)
    });

    match result {
        Ok(activity) => Ok(PyParsedActivity::from(activity)),
        Err(WpError::DecompressionLimitExceeded(msg)) => {
            Err(PyErr::new::<DecompressionLimitExceeded, _>(msg))
        }
        Err(WpError::DurationLimitExceeded(msg)) => {
            Err(PyErr::new::<DurationLimitExceeded, _>(msg))
        }
        Err(e) => Err(PyErr::new::<ParseError, _>(e.to_string())),
    }
}

/// Compute metrics using server-side FTP.
#[pyfunction]
fn compute_metrics(
    py: Python<'_>,
    activity: &PyParsedActivity,
    ftp: u16,
) -> PyResult<PyComputedMetrics> {
    let result = py.allow_threads(|| {
        crate::metrics::compute_all(&activity.inner, ftp)
    });

    Ok(PyComputedMetrics::from(result))
}

/// Custom exception for parse errors.
pyo3::create_exception!(workout_parse, ParseError, pyo3::exceptions::PyException);

/// Custom exception for decompression limit exceeded.
pyo3::create_exception!(workout_parse, DecompressionLimitExceeded, pyo3::exceptions::PyException);

/// Custom exception for duration limit exceeded (corrupt timestamps).
pyo3::create_exception!(workout_parse, DurationLimitExceeded, pyo3::exceptions::PyException);

#[pymodule]
fn workout_parse(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(parse_file, m)?)?;
    m.add_function(wrap_pyfunction!(parse_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(compute_metrics, m)?)?;
    m.add_function(wrap_pyfunction!(detect_patterns, m)?)?;

    m.add_class::<PyParsedActivity>()?;
    m.add_class::<PySessionMeta>()?;
    m.add_class::<PyLapMeta>()?;
    m.add_class::<PyComputedMetrics>()?;
    m.add_class::<PyPatternConfig>()?;
    m.add_class::<PyDetectedPattern>()?;

    m.add("ParseError", m.py().get_type::<ParseError>())?;
    m.add("DecompressionLimitExceeded", m.py().get_type::<DecompressionLimitExceeded>())?;
    m.add("DurationLimitExceeded", m.py().get_type::<DurationLimitExceeded>())?;

    // Export sentinel constants
    m.add("MISSING_U8", MISSING_U8)?;
    m.add("MISSING_U16", MISSING_U16)?;
    m.add("MISSING_I32", MISSING_I32)?;

    Ok(())
}
```

### Zero-copy NumPy Conversion (src/pyo3/numpy.rs)

To meet the performance targets, `Vec<T>` -> NumPy conversion must avoid per-element copying. Prefer APIs that consume the `Vec<T>` and transfer ownership of the underlying buffer to NumPy (e.g., `PyArray1::from_vec(...)` or `PyArray1::from_vec_bound(...)` depending on `numpy`/`pyo3` versions), rather than building arrays element-by-element.

---

## FIT Profile Constants

```rust
// src/fit/profile.rs
// [Full FIT SDK constants - same as before, abbreviated here]

// Global Message Numbers
pub const GM_FILE_ID: u16 = 0;
pub const GM_SESSION: u16 = 18;
pub const GM_LAP: u16 = 19;
pub const GM_RECORD: u16 = 20;
pub const GM_EVENT: u16 = 21;
pub const GM_DEVICE_INFO: u16 = 23;
pub const GM_ACTIVITY: u16 = 34;

// Record fields
pub const REC_TIMESTAMP: u8 = 253;
pub const REC_POSITION_LAT: u8 = 0;
pub const REC_POSITION_LONG: u8 = 1;
pub const REC_ALTITUDE: u8 = 2;
pub const REC_HEART_RATE: u8 = 3;
pub const REC_CADENCE: u8 = 4;
pub const REC_DISTANCE: u8 = 5;
pub const REC_SPEED: u8 = 6;
pub const REC_POWER: u8 = 7;
pub const REC_TEMPERATURE: u8 = 13;
pub const REC_ENHANCED_SPEED: u8 = 73;
pub const REC_ENHANCED_ALTITUDE: u8 = 78;

// Session fields
pub const SES_SPORT: u8 = 5;
pub const SES_SUB_SPORT: u8 = 6;
pub const SES_TOTAL_ELAPSED_TIME: u8 = 7;
pub const SES_TOTAL_TIMER_TIME: u8 = 8;
pub const SES_TOTAL_DISTANCE: u8 = 9;
pub const SES_TOTAL_CALORIES: u8 = 11;
pub const SES_AVG_SPEED: u8 = 14;
pub const SES_MAX_SPEED: u8 = 15;
pub const SES_AVG_HEART_RATE: u8 = 16;
pub const SES_MAX_HEART_RATE: u8 = 17;
pub const SES_AVG_CADENCE: u8 = 18;
pub const SES_MAX_CADENCE: u8 = 19;
pub const SES_AVG_POWER: u8 = 20;
pub const SES_MAX_POWER: u8 = 21;
pub const SES_TOTAL_ASCENT: u8 = 22;
pub const SES_TOTAL_DESCENT: u8 = 23;
pub const SES_NORMALIZED_POWER: u8 = 34;
pub const SES_TRAINING_STRESS_SCORE: u8 = 35;
pub const SES_INTENSITY_FACTOR: u8 = 36;

// [... full constants same as before ...]
```

---

## Build & Integration

### Building

```bash
# Install maturin
pip install maturin

# Development build (debug, fast compile)
cd workout-parse
maturin develop

# Release build
maturin build --release

# Install wheel
pip install workout-parse/target/wheels/workout_parse-*.whl
```

### CI Configuration

```yaml
# .github/workflows/workout-parse.yml
name: Workout Parse

on:
  push:
    paths:
      - 'workout-parse/**'
  pull_request:
    paths:
      - 'workout-parse/**'

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Rust
        uses: dtolnay/rust-action@stable

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install maturin
        run: pip install maturin pytest numpy

      - name: Build
        working-directory: workout-parse
        run: maturin build --release

      - name: Test Rust
        working-directory: workout-parse
        run: cargo test

      - name: Install wheel
        run: pip install workout-parse/target/wheels/workout_parse-*.whl

      - name: Test Python
        working-directory: workout-parse
        run: pytest tests/python/

      - name: Benchmark
        working-directory: workout-parse
        run: cargo bench --bench parse_bench -- --noplot
```

**Spec hygiene (recommended):** Add a lightweight CI/pre-commit check to reject ANSI/control bytes in `docs/WORKOUT_PARSER_SPEC.md` (copy/paste from terminals can insert `\x1b[...]` sequences).

```bash
python3 - <<'PY'
import pathlib, sys
p = pathlib.Path("docs/WORKOUT_PARSER_SPEC.md")
b = p.read_bytes()
bad = [
    (i, c)
    for i, c in enumerate(b)
    if c == 0x1B or (c < 32 and c not in (9, 10, 13))
]
if bad:
    print("Found ANSI/control bytes:", bad[:10])
    sys.exit(1)
PY
```

---

## Migration Path

### Phase 1: Parallel Operation (1 week)

1. Add `workout_parse` wheel to requirements.txt
2. Add feature flag `USE_RUST_PARSER=false` in settings
3. In ride_processor.py, run both parsers when flag is false:
   ```python
   rust_result = wp.parse_bytes(data)
   python_result = _parse_fit_legacy(data)
   _log_discrepancies(rust_result, python_result)
   ```
4. Monitor logs for discrepancies over 1000+ rides

### Phase 2: Validation (1 week)

1. Compare metrics (NP, TSS, elevation) between parsers
2. Test edge cases:
   - Corrupt/truncated files
   - Multi-session FIT files
   - Zwift/TrainerRoad/Wahoo files
   - Large files (>50MB)
   - Nested compression
3. Run load tests to verify performance targets

### Phase 3: Cutover

1. Set `USE_RUST_PARSER=true`
2. Monitor error rates for 48 hours
3. Remove legacy parser code
4. Remove `fitparse`, `gpxpy` from requirements.txt

### Rollback Plan

- Feature flag allows instant rollback
- Keep legacy code in `_legacy/` for 30 days
- Database stores raw file bytes, can always reprocess

---

## Performance Monitoring

```python
from prometheus_client import Histogram, Counter

PARSE_DURATION = Histogram(
    'workout_parse_duration_seconds',
    'Time to parse workout file',
    ['file_type'],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
)

PARSE_ERRORS = Counter(
    'workout_parse_errors_total',
    'Parse errors by type',
    ['error_type']
)

METRICS_DURATION = Histogram(
    'workout_metrics_duration_seconds',
    'Time to compute metrics',
    buckets=[0.001, 0.002, 0.005, 0.01, 0.025]
)
```

**Expected Results:**

| Metric | Before | After | Target |
|--------|--------|-------|--------|
| p50 parse time | 400ms | 15ms | <20ms |
| p99 parse time | 1.2s | 40ms | <100ms |
| p50 NP calc | 80ms | 1ms | <3ms |
| Memory per parse | 50MB | 10MB | <20MB |

---

## Testing Strategy

### Unit Tests (Rust)

```rust
#[cfg(test)]
mod tests {
    // NP algorithm correctness
    #[test] fn test_np_steady_state() { ... }
    #[test] fn test_np_variable_power() { ... }
    #[test] fn test_np_with_sensor_dropout() { ... }  // MISSING_U16 -> 0W
    #[test] fn test_np_with_coasting() { ... }        // 0W is valid, not dropped
    #[test] fn test_np_with_pause() { ... }           // Gap > 30s splits segments
    #[test] fn test_np_pause_doesnt_inflate() { ... } // 1hr ride + 1hr pause ≠ 2hr NP

    // Resampling
    #[test] fn test_resample_regular() { ... }
    #[test] fn test_resample_irregular() { ... }
    #[test] fn test_resample_with_missing() { ... }
    #[test] fn test_resample_oom_protection() { ... } // Huge timestamp span -> error
    #[test] fn test_resample_corrupt_timestamps() { ... } // end <= start -> empty vec
    #[test] fn test_resample_nonmonotonic_segment() { ... } // seg_end < seg_start -> skip segment
    #[test] fn test_resample_segments_on_pause() { ... }

    // Decompression safety
    #[test] fn test_gzip_normal() { ... }
    #[test] fn test_gzip_bomb_rejected() { ... }
    #[test] fn test_gzip_zero_copy_passthrough() { ... }  // Uncompressed -> borrowed
    #[test] fn test_zip_normal() { ... }
    #[test] fn test_zip_ratio_rejected() { ... }          // Ratio check on zip too
    #[test] fn test_zip_too_many_entries() { ... }
    #[test] fn test_nested_compression() { ... }

    // Tile math
    #[test] fn test_tile_poles() { ... }
    #[test] fn test_tile_antimeridian() { ... }
    #[test] fn test_tile_zoom_clamp() { ... }
    #[test] fn test_tile_zoom_overflow_safe() { ... }

    // Sentinel handling
    #[test] fn test_zero_is_valid_power() { ... }     // 0W ≠ MISSING
    #[test] fn test_sentinel_is_missing() { ... }     // 65535 = no reading
}
```

### Golden File Tests

```
workout-parse/tests/fixtures/
├── garmin_edge_840.fit         # Standard Garmin outdoor ride
├── wahoo_kickr.fit             # Indoor trainer
├── zwift_watopia.fit           # Virtual ride with developer fields
├── trainerroad_workout.fit     # Structured workout
├── strava_export.gpx           # GPX with extensions
├── strava_export.gpx.gz        # Gzipped GPX
├── garmin_connect.zip          # Zipped FIT
├── multisport_triathlon.fit    # Multiple sessions
├── corrupted_truncated.fit     # Truncated file
└── minimal_no_power.fit        # HR only, no power
```

### Fuzzing (optional but recommended)

```rust
// In tests/fuzz.rs
#[cfg(fuzzing)]
fuzz_target!(|data: &[u8]| {
    // Should never panic, only return errors
    let _ = workout_parse::parse_bytes(data);
});
```

---

## Open Questions (Resolved)

| Question | Resolution |
|----------|------------|
| Device vs server metrics | Server recomputes all metrics using server FTP |
| Missing data representation | Optional arrays + sentinel values; 0 is valid, sentinel is missing |
| Multi-session FIT files | Parse all, expose primary (longest) |
| Decompression limits | 100MB max, 10 entries, 100x ratio (gzip AND zip), 2 depth |
| dist_mm overflow | Changed to `dist_m: f32` (meters, float) |
| GIL release | All parse functions use `py.allow_threads()` |
| NP with gaps | Segment-based: pauses split segments, sensor dropout -> 0W, sparse seconds -> carry-forward |
| Resample OOM | Cap at MAX_ACTIVITY_DURATION_S (48h), check end > start before calc |
| Decompression copies | Use `DecompressResult::Borrowed` for uncompressed data (zero-copy) |
| Zip ratio check | Multiplication-based check (avoids div-by-zero), applied to both gzip and zip |
| Tile zoom overflow | Clamp zoom to MAX_TILE_ZOOM (22) before bit shift |
| Array invariants | Documented: length = n, aligned to time_ms, sentinels mark gaps |
| ANSI/control bytes in docs | Disallow; strip; add CI/pre-commit lint check |
| Unicode arrows in docs | Prefer ASCII `->` in code blocks for copy-paste safety |
| Rust API visibility | `Segment` and `resample_power_1hz` are `pub(crate)` (internal only) |
| Lifetime annotations | `DecompressResult<'_>` properly annotated in return types |
| Per-segment timestamps | Non-monotonic segments (seg_end <= seg_start) are skipped |
| PyO3 exception mapping | `DurationLimitExceeded` properly mapped (not just `ParseError`) |

---

## Document Revision

- **Version:** 1.8
- **Date:** December 2024
- **Author:** BoulderRoller Engineering
- **Status:** Revised after eighth audit - Ready for implementation
- **Changes v1.8:**
  - Docs: added recommended lint check to reject ANSI/control bytes
  - Docs: clarified control-byte vs Unicode-arrow guidance in the resolved questions table
- **Changes v1.7:**
  - Docs: clarified `SessionMeta` is device-reported; `ComputedMetrics` is canonical (and added stub guidance)
  - Docs: added explicit zero-copy requirement for `Vec<T>` -> NumPy conversion in `src/pyo3/numpy.rs`
  - Docs: clarified GPS float precision expectations (avoid float32)
- **Changes v1.6:**
  - Zip: added ratio enforcement during streaming reads (defense-in-depth vs forged headers)
  - NP: seeded carry-forward from first available bucket average to avoid leading 0W for sparse starts
  - Docs: clarified that `MISSING_U16 -> 0W` is a conservative policy with alternatives
- **Changes v1.5:**
  - NP: resample uses carry-forward for sparse seconds; 0W only for explicit 0W and `MISSING_U16` substitution
  - Rust: `calculate_np` is `pub(crate)` to match `Segment` visibility
  - Docs: documented pause-detection limitations and FIT `GM_EVENT` alternative
- **Changes v1.4:**
  - GPS: fixed "Working with Record Arrays" example to use integer comparison before float conversion
  - Rust: added lifetime `'_` to `DecompressResult` return type (compile fix)
  - Rust: made `Segment` and `resample_power_1hz` `pub(crate)` (API visibility fix)
  - Resample: added per-segment monotonic guard (`seg_end_ms <= seg_start_ms` -> skip)
  - PyO3: wired `DurationLimitExceeded` exception in error mapping
  - Constants: removed redundant `MAX_RESAMPLED_SECONDS` (consolidated into `MAX_ACTIVITY_DURATION_S`)
  - Zip: changed ratio check to multiplication-based (`saturating_mul`) to avoid div-by-zero
- **Changes v1.3:**
  - Code: replaced Unicode arrows (→) with ASCII (->) in code blocks for copy-paste safety
  - Resample: added explicit `end_ms <= start_ms` guard before duration calc (prevents usize overflow)
- **Changes v1.2:**
  - NP: segment-based calculation, pauses don't inflate NP, sensor dropout -> 0W
  - Resample: OOM protection via MAX_ACTIVITY_DURATION_S check
  - Decompression: zero-copy for uncompressed files, ratio check for zip
  - Tiles: zoom clamping to prevent overflow
  - Docs: array invariants, GPS masking example fixed, 0 vs sentinel clarified
- **Changes v1.1:**
  - Fixed NP O(n²) → O(n)
  - Added missing data policy
  - Decompression limits
  - Tile edge cases
  - GIL release
  - Multi-session handling
