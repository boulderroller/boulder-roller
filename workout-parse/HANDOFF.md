# Workout-Parse Build Handoff

## Project Overview
High-performance Rust workout file parser with PyO3 Python bindings for BoulderRoller. Parses FIT/GPX/TCX files and calculates cycling metrics (NP, TSS, IF). Replaces slower Python parser while maintaining backward compatibility via adapter layer.

## Current Status
**In Progress:** Building the Rust module. Just fixed fitparser API issues, need to verify compilation.

---

## IMMEDIATE NEXT STEPS

### 1. Verify Rust Compilation
```bash
cd /Users/gabetemp/curahee/BoulderRoller-v2/workout-parse && cargo check
```

### 2. Run Cargo Tests
```bash
cd /Users/gabetemp/curahee/BoulderRoller-v2/workout-parse && cargo test
```

### 3. Build Python Module with Maturin
Maturin is installed but not in PATH:
```bash
/Users/gabetemp/Library/Python/3.9/bin/maturin develop
```

### 4. Test Python Import
```bash
cd /Users/gabetemp/curahee/BoulderRoller-v2/workout-parse
python -c "import workout_parse; print(dir(workout_parse))"
```

### 5. Test Basic Functionality
```python
import workout_parse as wp
print(wp.MISSING_U8, wp.MISSING_U16, wp.MISSING_I32)
# Should print: 255 65535 -2147483648
```

---

## Recent Fixes Applied (in lib.rs)
1. `fitparser::from_reader(cursor)` → `fitparser::from_reader(&mut cursor)` (line 96)
2. `fitparser::profile::MesgsDataType::Record` → `fitparser::profile::MesgNum::Record` (line 120)
3. `fitparser::profile::MesgNumDataType::FileId` → `fitparser::profile::MesgNum::FileId` (line 228)
4. `fitparser::profile::MesgNumDataType::Sport` → `fitparser::profile::MesgNum::Sport` (line 235)

---

## If Errors Occur

### Fitparser API Issues
Check actual API at: `~/.cargo/registry/src/index.crates.io-*/fitparser-0.7.0/src/`
- Enums are in `fitparser::profile::MesgNum::{Record, FileId, Sport, Session, etc.}`
- Value variants: `Value::Timestamp`, `Value::SInt32`, `Value::UInt16`, `Value::UInt8`, `Value::Float64`

### PyO3/Numpy Issues
Using PyO3 0.21 + numpy 0.21. Key patterns:
```rust
use numpy::IntoPyArray;
self.inner.time_ms.clone().into_pyarray(py).into()
```

---

## Key Files

| File | Purpose |
|------|---------|
| `workout-parse/src/lib.rs` | Main parser + PyO3 bindings (FIT/GPX/TCX parsers) |
| `workout-parse/src/metrics.rs` | NP/TSS/IF calculation with 30s rolling window |
| `workout-parse/src/tiles.rs` | Web Mercator tile projection for CAL tokens |
| `workout-parse/src/constants.rs` | Sentinel values, limits |
| `workout-parse/src/decompress.rs` | Safe gzip/zip decompression |
| `workout-parse/src/error.rs` | Error types |
| `workout-parse/Cargo.toml` | Rust dependencies |
| `workout-parse/pyproject.toml` | Python/maturin config |
| `workout-parse/python/workout_parse/__init__.py` | Python re-exports |
| `backend/app/services/workout_parse_adapter.py` | Backward-compatible adapter |

---

## Dependencies (Cargo.toml)
```toml
pyo3 = { version = "0.21", features = ["extension-module"] }
numpy = "0.21"
fitparser = "0.7"
quick-xml = "0.31"
chrono = "0.4"
flate2 = "1.0"
zip = { version = "0.6", default-features = false, features = ["deflate"] }
thiserror = "1.0"
```

---

## Architecture Notes

### Sentinel Values (for missing data)
- `MISSING_U8 = 255`
- `MISSING_U16 = 65535`
- `MISSING_I32 = i32::MIN`
- `MISSING_I64 = i64::MIN`

### GPS Coordinates
Stored as e7 format (degrees * 10^7 as i32) for precision without floats.

### Metrics Calculation
- Resample power to 1Hz with carry-forward for sparse samples
- 30-second rolling average for Normalized Power
- TSS = (duration_sec × NP × IF) / (FTP × 3600) × 100
- IF = NP / FTP

### Python Adapter
Located at `backend/app/services/workout_parse_adapter.py`. Provides:
- `parse_ride_file_rust()` - drop-in for `ride_parser.parse_ride_file()`
- `calculate_metrics_rust()` - drop-in for `ride_metrics.calculate_metrics()`
- Feature flag: `USE_RUST_PARSER=true` environment variable

---

## Expected Warnings (OK to ignore)
- Deprecated `into_pyarray` → will be `into_pyarray_bound` in future
- Deprecated `get_type` → will be `get_type_bound` in future
- Unused variables `in_trkpt`, `in_trackpoint` in GPX/TCX parsers

---

## After Build Succeeds

### Integration Test with Backend
```bash
cd /Users/gabetemp/curahee/BoulderRoller-v2/backend
USE_RUST_PARSER=true python -c "
from app.services.workout_parse_adapter import is_rust_parser_available, parse_ride_file_rust
print('Available:', is_rust_parser_available())
"
```

### Test with Real FIT File (if available)
```python
import workout_parse as wp
activity = wp.parse_file('/path/to/file.fit')
print(f'Records: {len(activity.time_ms)}')
print(f'Sport: {activity.sport}')
metrics = wp.compute_metrics(activity, ftp_w=200, weight_kg=75.0)
print(f'NP: {metrics.np_w}, TSS: {metrics.tss}')
```

---

## Full TODO Checklist
- [ ] `cargo check` passes
- [ ] `cargo test` passes
- [ ] `maturin develop` builds successfully
- [ ] `import workout_parse` works in Python
- [ ] Constants accessible (MISSING_U8, etc.)
- [ ] `parse_bytes()` function available
- [ ] `compute_metrics()` function available
- [ ] Backend adapter imports successfully
