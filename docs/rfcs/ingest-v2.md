# RFC: Ride Ingest v2 ("Brap Stack")

Status: Draft
Owner: BoulderRoller team
Last updated: 2025-12-15
Target: Scale from ~50 alpha → 5k users with "Ferrari" ingest latency, predictable cost, and idempotent on-chain rewards.

> ⚠️ **OUTDATED CAL MODEL**: References to "CAL-gated scoring", `scored_patterns`,
> and `/scoring/*` routes are deprecated. Current model: CAL earned from TSS, tributed
> to vaults automatically. No manual scoring. See `docs/TOKENOMICS_V2.md`.

---

## 0) Executive Summary

BoulderRoller’s current ride ingest path sends workout files as JSON base64 through the API and Celery, parses them in Python, writes high-volume data through Supabase PostgREST, and blocks “ride completion” on Solana minting. This will bottleneck on CPU, queue/memory bloat, and network latency.

This RFC proposes a v2 ingest architecture:

- **Presigned uploads to S3-compatible object storage (DO Spaces)** (no base64).
- **Small job messages** (`ride_id`, `file_key`) via **NATS JetStream**.
- **Dedicated Rust ingest worker** for parse + metrics + tile projection + pattern detection + bulk writes.
- **Separate proof/mint worker** so chain latency never blocks ride processing.
- **Direct Postgres** for hot-path writes (keep Supabase Postgres as the database if desired; just stop using PostgREST for bulk ingestion).

---

## 1) Scope

### In scope
- Upload pipeline changes (API + clients) to remove base64.
- Worker pipeline changes (queue + processing) to remove file bytes from queues.
- Parsing + metrics computation performance (FIT/GPX/TCX).
- Tile/pattern detection pipeline (existing H3 + pattern tables).
- Proof/mint flow decoupling and idempotency.
- Observability + operational guardrails.

### Out of scope (for this RFC)
- Rewriting all API repository calls off the Supabase client (only hot path).
- Redesigning tokenomics/economics.
- Major product UI redesigns (only client upload changes).

---

## 2) Current State (Repo Reality)

### Upload & processing
- Clients upload rides as base64 JSON:
  - iOS: `ios/BoulderRollers/Services/APIClient.swift` (uploads base64)
  - Web: `web/portal/src/lib/api.ts` (uploads base64)
  - Bot: `bot/backend_client.py` (uploads base64)
- API endpoint: `POST /rides/upload` in `backend/app/routes/rides.py` accepts `RideUploadRequest` (`file_data_b64`).
- Celery task: `backend/app/tasks.py` receives base64 payload and runs `RideProcessor`.
- Parser: `backend/app/services/ride_parser.py` decodes base64 and uses `fitparse`/`gpxpy`.

### Pattern + tiles
- Tile projection uses H3 (`h3` python pkg) in `backend/app/services/tile_service.py`.
- Tile samples stored in `activity_tile_samples` (`backend/sql/023_tile_infrastructure.sql`).
- Wallet tile history stored in `wallet_tile_history` (PK `(wallet, tile_id)`).
- Patterns stored in `patterns_*` tables (`backend/sql/024_pattern_tables.sql`).

### Mint/proof coupling
- Ride processing calls `ProofBuilder.create_ride_proof` before marking ride complete: `backend/app/services/ride_processor.py`.
- Proof/mint uses Solana direct RPC path in `backend/app/solana_client.py`.

### Known correctness/perf issues in-tree
- Normalized Power calculation is **O(n²)**: `backend/app/services/ride_metrics.py` (`_calculate_normalized_power`).
- `PatternResults` shape mismatch risk:
  - `PatternResults` defines `steady_pattern`/`exploration_pattern` singular: `backend/app/services/pattern_engine.py`
  - Proof/Achievement code iterates `steady_patterns`/`exploration_patterns`: `backend/app/services/proof_builder.py`, `backend/app/services/achievement_detector.py`

---

## 3) Goals / Non-Goals

### Goals
- **No file bytes** in JSON request bodies or queue messages.
- Fast, bounded ingestion: parsing + compute uses predictable memory and time.
- **At-least-once** processing with **exactly-once effects** (idempotent DB writes + no double mint).
- Decouple “ride processed” from “mint confirmed”.
- Keep migration safe: do not break current clients during rollout.

### Non-goals
- Perfect “universal file support” day 1. Prefer correctness + fast path for common Garmin/Wahoo/Strava exports first.
- Replacing Supabase Postgres immediately. (We can keep Supabase as Postgres host.)

---

## 4) Proposed Architecture (Target)

### 4.1 High-level diagram

Client
  ├─ POST /rides/upload/init  ──▶ API (FastAPI)
  │     ◀─ presigned PUT url + file_key + upload_id
  ├─ PUT file bytes ───────────▶ DO Spaces (S3-compatible)
  └─ POST /rides/upload/complete ─▶ API ─▶ JetStream: rides.process.v1
                                    │
                                    ▼
                             Rust ingest-worker
                                    │
                                    ├─ direct Postgres writes (hot path)
                                    └─ publish rides.mint.v1 (optional)
                                            │
                                            ▼
                                     proof-worker (Python first)
                                            │
                                            └─ Solana mint/proof updates

### 4.2 Why this matches BoulderRoller’s design
- Your “pattern-first” architecture is already present (`patterns_*`, `scored_patterns`, CAL-gated scoring).
- H3 tile quantization is already present and deduped (`TileService.deduplicate_tiles`).
- The missing piece is moving bytes out of JSON/Redis and ensuring the compute path is isolated + scalable.

---

## 5) API Design (v2 endpoints)

### 5.1 Keep legacy endpoint temporarily
- `POST /rides/upload` (base64 JSON) remains for backward compatibility.
- Mark as deprecated once v2 clients ship.

### 5.2 New endpoints

#### POST `/rides/upload/init`
Purpose: Create an upload session and return a presigned PUT URL.

Request (JSON):
```json
{
  "filename": "ride.fit",
  "content_type": "application/octet-stream",
  "content_length": 3145728,
  "declared_file_type": "fit"
}
```

Response:
```json
{
  "upload_id": "uuid",
  "file_key": "rides/<user_id>/<upload_id>/original",
  "put_url": "https://...presigned...",
  "required_headers": {
    "Content-Type": "application/octet-stream"
  },
  "expires_at": "2025-12-15T00:00:00Z"
}
```

Server responsibilities:
- Enforce per-user max file size (e.g. 50MB) and supported types.
- Record upload intent in DB (see `ride_uploads` table below).
- Prefer a short expiration (5–10 min).

#### POST `/rides/upload/complete`
Purpose: Finalize an upload session, create a ride row, enqueue ingest.

Request:
```json
{
  "upload_id": "uuid"
}
```

Response:
```json
{
  "ride_id": "uuid",
  "status": "queued",
  "message": "Ride uploaded. Processing in background."
}
```

Server responsibilities:
- Verify the object exists (HEAD) and size within limits.
- Compute/store immutable metadata (size, etag, sha256 if available).
- Create `rides` row with `file_key` and `processing_status='queued'`.
- Publish JetStream message `rides.process.v1`.

---

## 6) Queue / Job Contracts (JetStream)

### 6.1 Streams & subjects
- Stream: `br.rides`
  - Subject: `rides.process.v1`
  - Subject: `rides.mint.v1` (optional separation)
  - Subject: `rides.dlq.v1` (dead letter)

### 6.2 Message schema (rides.process.v1)
```json
{
  "v": 1,
  "ride_id": "uuid",
  "user_id": "uuid",
  "wallet": "base58",
  "file_key": "rides/<user_id>/<upload_id>/original",
  "declared_file_type": "fit",
  "uploaded_at": "RFC3339"
}
```

### 6.3 Delivery semantics
- JetStream is at-least-once.
- Enforce **exactly-once effects** by:
  - DB-level uniqueness + idempotent upserts.
  - Worker “short-circuit” if ride already completed.
  - Stable mint/proof identifiers (proof_id uniqueness).

### 6.4 Dedupe
- Set NATS msg-id header to `ride_id` for `rides.process.v1` publishes.

---

## 7) Worker Responsibilities

### 7.1 Rust ingest-worker (priority)
Inputs: `{ride_id, file_key, user_id, wallet}`

Steps:
1. Download bytes from DO Spaces (streaming).
2. Sniff true file kind (FIT/GPX/TCX; handle gzip/zip wrappers).
3. Parse into columnar streams (time, lat/lon, alt, hr, cad, power, speed, distance).
4. Compute metrics:
   - duration, distance, elevation gain
   - avg/max power/hr/speed
   - **Normalized Power in O(n)** (rolling window)
5. Produce:
   - GPS track representation (downsampled or full; decision below)
   - activity streams (power/hr/cad/speed)
   - tile samples (already dedupe-consecutive tiles is fine)
6. Detect patterns (climb/steady/exploration) consistent with `patterns_*` tables.
7. Bulk write results to Postgres.
8. Update ride status to `completed` (even if mint is pending).
9. Publish mint/proof job (optional).

### 7.2 proof-worker (Python first, can be Rust later)
Inputs: `{ride_id, user_id, wallet, proof_payload_hash}`

Steps:
1. Ensure proof row exists (idempotent).
2. Submit Solana proof/mint (retry with backoff).
3. Update `proofs` / `mint_events` / `rides.tx_signature` accordingly.

Rationale for “Python first”:
- You already have working Solana code paths (`backend/app/solana_client.py` + `solana_direct`).
- The main perf win is not Rust here; it’s **decoupling** and **idempotency**.

---

## 8) Database Changes (Minimal, High-Value)

### 8.1 Add upload tracking table
Create `ride_uploads`:
- `id uuid pk`
- `user_id uuid`
- `wallet text`
- `file_key text unique`
- `filename text`
- `content_length bigint`
- `content_type text`
- `status text` (INITIATED, FINALIZED, EXPIRED, FAILED)
- `expires_at timestamptz`
- `created_at timestamptz`
- `finalized_at timestamptz`

### 8.2 Add file metadata columns on `rides`
Add columns (suggested):
- `file_key text`
- `file_size_bytes bigint`
- `file_sha256 text`
- `original_filename text`
- `ingest_version text` (e.g. `v2-rust`)
- `ingested_at timestamptz`

### 8.3 Idempotency constraints
Recommended uniques (where missing):
- `proofs.ride_id` unique (one proof per ride) **or** explicit “proof_kind” if multiple.
- Pattern rows already have UUID PKs; consider unique `(activity_id, pattern_type, start_offset_s, end_offset_s)` if you ever re-run detection.

---

## 9) Direct Postgres vs Supabase Client

### 9.1 Recommendation
- Keep Supabase Postgres as your DB host if you like.
- For the hot ingest path, connect via `DATABASE_URL` using a role that bypasses RLS (server-side writes).
- Keep the Supabase Python client for non-hot endpoints while migrating gradually.

### 9.2 Why
- PostgREST adds overhead and can be painful for large bulk inserts (`gps_points`, `activity_streams`, `activity_tile_samples`).
- Direct SQL enables transactions, COPY/batch, and conflict handling.

---

## 10) Data Volume Decisions (Critical at 5k)

### 10.1 GPS points
`gps_points` is expensive if you store every second for every ride.

Options:
- **A (recommended):** store a downsampled track in DB for UI; store full-res in object storage.
- B: store only tile samples + derive track for UI (map polyline from tile centers) if acceptable.
- C: store full-res in DB (likely costly; do only if product needs it).

### 10.2 Streams
`activity_streams` stores arrays in Postgres; OK if you keep sizes bounded.
If streams get large, store compressed blobs in object storage and keep only summary stats + a pointer in DB.

---

## 11) Security / Abuse / Reliability

- Enforce upload size caps at init and at complete (HEAD check).
- Never trust file extension/type; sniff in worker.
- Decompression bombs: cap total decompressed bytes; cap nested archives.
- Rate-limit init/complete using existing rate limiter categories (extend `ride_upload` category if needed).
- Make worker idempotent; no double processing; no double mint.

---

## 12) Observability (What “Brap” Looks Like in Metrics)

### API metrics
You already have Prometheus middleware (`backend/app/middleware/metrics.py`).
Add explicit counters/histograms for:
- upload init latency
- upload complete latency
- enqueue success/failure

### Worker metrics
Emit structured logs and/or Prometheus:
- bytes_downloaded, decompressed_bytes
- parse_ms, metrics_ms, tiles_ms, patterns_ms, db_write_ms
- queue_lag_ms, redeliveries
- success/fail by reason

---

## 13) Rollout Plan (Safe, Incremental)

1. **Correctness fixes first**
   - Fix PatternResults shape mismatch (proof/achievements).
   - Fix NP O(n²) algorithm.
   - Decouple “ride completed” from mint confirmation (make mint async).
2. **Presigned upload v2 endpoints**
   - Add `/rides/upload/init` and `/rides/upload/complete`.
   - Keep `/rides/upload` base64.
3. **Stop sending bytes through Celery**
   - Change Celery task payload to `file_key` (even before Rust).
4. **Introduce JetStream + Rust ingest-worker**
   - Route v2 rides to JetStream worker.
5. **Move hot writes to direct Postgres**
   - Keep Supabase client for non-hot endpoints during migration.

---

## 14) Minting & Economics Surfaces (Don’t Double-Count)

Today BoulderRoller has (at least) two places that mint/record DUNG:

1. **Automatic ride mint on upload** via `ProofBuilder` (TSS-based reward) invoked during ride processing.
2. **Optional CAL-gated pattern scoring** via `/scoring/*` and `ScoringService`, which records `scored_patterns` and may attempt on-chain minting.

Decide explicitly which product/economic model you want:

- **A) Auto-mint only (simplest):** upload → DUNG minted based on ride metrics. `/scoring` becomes read-only or disabled.
- **B) Score-only mint (cleaner game loop):** upload detects patterns for free; users spend CAL to mint DUNG per pattern; no automatic DUNG on upload.
- **C) Hybrid (hardest):** small auto-mint + optional scoring for incremental rewards. Requires tight caps and clear accounting to prevent “mint inflation”.

If you keep Hybrid, enforce at the DB layer:
- Unambiguous “mint source” fields (e.g. `source_type`, `source_id`) on mint event records.
- Unique constraints that prevent double-mint per source.
- A clear UI and API contract for “what has already been minted and why”.

Also note: new v2 upload endpoints must be added to emergency controls (uploads kill-switch) alongside `/rides/upload`.

---

## 15) Open Questions / Decisions Needed

1. File retention: how long do we keep raw uploads (30 days? forever?).
2. GPS storage policy: downsampled in DB vs blob storage vs full-res DB.
3. Do we support zip/gzip immediately or phase in?
4. Where do we enforce checksum (client-provided sha256 vs server-computed)?
5. Mint policy: “one proof per ride” vs pattern-scoring-only mint vs both (avoid double counting).
