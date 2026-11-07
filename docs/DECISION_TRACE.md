# Decision Trace Specification

**Status:** DRAFT
**Last updated:** 2026-02-27

For every detected climb and every match attempt, store machine-readable
evidence so any vault decision can be explained from the database alone
in under 60 seconds.

---

## Principle

If you cannot reconstruct WHY a climb matched a vault (or didn't) from
stored data alone, the system is not production-ready for economic actions.

---

## Trace Structure

Every climb pattern stores a `match_trace` JSONB column on `patterns_climb`.

### Schema

```sql
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS match_trace JSONB;
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS economic_eligible BOOLEAN DEFAULT TRUE;
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS abstention_reasons TEXT[];
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS detector_version TEXT;
```

### Trace format

```json
{
  "detector": {
    "algorithm": "persistence",
    "version": "0.1.0",
    "commit": "abc1234"
  },
  "detection": {
    "persistence_m": 60.0,
    "is_essential": true,
    "canonical_bounds": [99, 398],
    "effort_bounds": [102, 395],
    "quality_filters": {
      "vert_floor_passed": true,
      "vam_cap_passed": true,
      "gradient_cap_passed": true,
      "distance_nonzero": true
    }
  },
  "signatures": {
    "v1_hex": "aabb...",
    "v2_hex": "0200...",
    "v2_checksum_valid": true
  },
  "match_attempts": [
    {
      "method": "gps_gated",
      "vault_id": 42,
      "vault_name": "Manayunk Wall",
      "gates": {
        "version": {"passed": true, "detail": "both v2"},
        "h3_proximity": {"passed": true, "grid_distance": 1},
        "geometric": {"passed": true, "vert_diff_pct": 3.2, "dist_diff_pct": 8.1},
        "dct_shape": {"passed": true, "d_rel": 0.032, "threshold": 0.08},
        "gps_proximity": {"passed": true, "distance_m": 23.4, "threshold_m": 150.0}
      },
      "result": "match",
      "confidence": 0.94,
      "similarity": 0.97
    }
  ],
  "best_match": {
    "vault_id": 42,
    "vault_name": "Manayunk Wall",
    "similarity": 0.97,
    "method": "gps_gated"
  },
  "abstention": {
    "eligible": true,
    "reasons": []
  },
  "economic_action": {
    "type": "vault_completion",
    "cal_tribute": 7,
    "is_new_kom": false,
    "solana_tx": null
  }
}
```

### When no match is found

```json
{
  "detector": { ... },
  "detection": { ... },
  "signatures": { ... },
  "match_attempts": [],
  "best_match": null,
  "abstention": {
    "eligible": true,
    "reasons": []
  },
  "economic_action": null
}
```

### When abstaining

```json
{
  ...
  "best_match": {
    "vault_id": 42,
    "vault_name": "Manayunk Wall",
    "similarity": 0.87,
    "method": "signature_only"
  },
  "abstention": {
    "eligible": false,
    "reasons": ["MATCH:probable_without_gps", "SIGNIFICANCE:tier_0_unbootstrapped"]
  },
  "economic_action": null
}
```

---

## Implementation

### 1. Build trace during matching

In `PatternEngine._match_vaults_and_record()`, accumulate trace data
as each gate is evaluated:

```python
trace = {
    "detector": {
        "algorithm": self.climb_algorithm,
        "version": wp.__version__ if wp else "python",
    },
    "detection": {
        "persistence_m": pattern.persistence_m,
        "canonical_bounds": None,  # Not stored on model yet
        "effort_bounds": [pattern.start_offset_s, pattern.end_offset_s],
    },
    "signatures": {
        "v1_hex": pattern.signature_hex[:16] + "..." if pattern.signature_hex else None,
        "v2_hex": pattern.signature_v2_hex[:16] + "..." if pattern.signature_v2_hex else None,
        "v2_checksum_valid": True,  # Already validated at parse time
    },
    "match_attempts": [],
    "best_match": None,
    "abstention": {
        "eligible": pattern.economic_eligible,
        "reasons": pattern.abstention_reasons or [],
    },
    "economic_action": None,
}
```

### 2. Log each match attempt

When `find_best_vault_match()` or `find_matches()` returns a result,
append the gate details:

```python
attempt = {
    "method": "gps_gated",
    "vault_id": vault.id,
    "vault_name": vault.name,
    "result": match_result["result"],
    "confidence": match_result.get("confidence", 0),
    "dct_distance": match_result.get("dct_distance"),
    "gps_distance_m": match_result.get("gps_distance_m"),
    "similarity": similarity,
}
trace["match_attempts"].append(attempt)
```

### 3. Store on pattern

```python
pattern.match_trace = trace
# Pass to repository for JSONB storage
```

### 4. DB migration

```sql
-- 068_decision_trace.sql
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS match_trace JSONB;
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS economic_eligible BOOLEAN DEFAULT TRUE;
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS abstention_reasons TEXT[];
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS detector_version TEXT;

CREATE INDEX IF NOT EXISTS idx_patterns_climb_eligible
    ON patterns_climb (economic_eligible)
    WHERE economic_eligible = FALSE;

COMMENT ON COLUMN patterns_climb.match_trace IS 'Machine-readable evidence for vault match decision (JSONB)';
COMMENT ON COLUMN patterns_climb.economic_eligible IS 'False if climb abstained from economic actions';
COMMENT ON COLUMN patterns_climb.abstention_reasons IS 'List of abstention trigger codes';
COMMENT ON COLUMN patterns_climb.detector_version IS 'Algorithm version that produced this detection';
```

---

## Querying

### Why did this climb match this vault?
```sql
SELECT match_trace->'best_match'->>'vault_name',
       match_trace->'best_match'->>'similarity',
       match_trace->'best_match'->>'method'
FROM patterns_climb
WHERE id = '<climb_id>';
```

### Which climbs abstained and why?
```sql
SELECT id, vert_m, abstention_reasons,
       match_trace->'best_match'->>'vault_name' as would_have_matched
FROM patterns_climb
WHERE economic_eligible = FALSE
ORDER BY created_at DESC;
```

### What's the abstention rate this week?
```sql
SELECT
    COUNT(*) as total,
    COUNT(*) FILTER (WHERE economic_eligible = TRUE) as eligible,
    COUNT(*) FILTER (WHERE economic_eligible = FALSE) as abstained,
    ROUND(100.0 * COUNT(*) FILTER (WHERE economic_eligible = FALSE) / COUNT(*), 1) as abstention_pct
FROM patterns_climb
WHERE created_at > NOW() - INTERVAL '7 days';
```

### Match confidence distribution
```sql
SELECT
    (match_trace->'best_match'->>'method') as method,
    COUNT(*) as matches,
    ROUND(AVG((match_trace->'best_match'->>'similarity')::float), 3) as avg_similarity
FROM patterns_climb
WHERE match_trace->'best_match' IS NOT NULL
GROUP BY 1;
```

---

## Relationship to other docs

- **Truth Contract v1:** Implements INV-ECON-1, INV-ECON-3, INV-ABST-1-3
- **Abstention Policy:** Decision trace stores abstention evidence
- **Benchmark v1:** Trace data enables corpus-level match quality analysis
