-- Canon climb registry and H3 corridor fast path.
-- Implements boulderroller-v2-4crx.8.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.canon_climbs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  canon_id uuid,
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  status text NOT NULL DEFAULT 'candidate'
    CHECK (status IN ('candidate', 'ratified', 'retired')),
  candidate_fingerprint text NOT NULL,
  display_name text NOT NULL,
  route_name text,
  direction text NOT NULL DEFAULT 'ascending'
    CHECK (direction = 'ascending'),
  centerline_polyline text NOT NULL,
  centerline_geom geometry(LINESTRING, 4326) NOT NULL,
  corridor_geom geometry(MULTIPOLYGON, 4326) NOT NULL,
  gate_start_line geometry(LINESTRING, 4326) NOT NULL,
  gate_end_line geometry(LINESTRING, 4326) NOT NULL,
  canonical_profile jsonb NOT NULL
    CHECK (jsonb_typeof(canonical_profile) = 'array'),
  length_m numeric(10, 2) NOT NULL CHECK (length_m > 0),
  vert_m numeric(10, 2) NOT NULL CHECK (vert_m >= 0),
  avg_gradient_pct numeric(6, 3) NOT NULL,
  max_gradient_pct numeric(6, 3),
  worthiness_score numeric(8, 4) NOT NULL DEFAULT 0
    CHECK (worthiness_score >= 0),
  confidence text NOT NULL DEFAULT 'needs_review'
    CHECK (confidence IN ('needs_review', 'low', 'medium', 'high')),
  dem_source text NOT NULL,
  compiler_version text NOT NULL,
  osm_way_refs bigint[] NOT NULL DEFAULT '{}',
  odbl_source text NOT NULL DEFAULT 'OpenStreetMap contributors',
  odbl_extract_at timestamptz,
  provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
  low_confidence_flags text[] NOT NULL DEFAULT '{}',
  ratified_by text,
  ratified_at timestamptz,
  retired_at timestamptz,
  supersedes_climb_id uuid REFERENCES public.canon_climbs(id),
  record_continuity_policy text NOT NULL DEFAULT 'new_record_board'
    CHECK (
      record_continuity_policy IN (
        'new_record_board',
        'carry_records_forward',
        'retire_without_successor'
      )
    ),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (ST_NPoints(centerline_geom) >= 2),
  CHECK (ST_NPoints(gate_start_line) = 2),
  CHECK (ST_NPoints(gate_end_line) = 2),
  CHECK (status = 'candidate' OR canon_id IS NOT NULL),
  CHECK (status = 'candidate' OR ratified_at IS NOT NULL),
  CHECK (status <> 'retired' OR retired_at IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_canon_climbs_candidate_fingerprint
  ON public.canon_climbs(candidate_fingerprint);

CREATE UNIQUE INDEX IF NOT EXISTS idx_canon_climbs_canon_version
  ON public.canon_climbs(canon_id, version)
  WHERE canon_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_canon_climbs_status
  ON public.canon_climbs(status);

CREATE INDEX IF NOT EXISTS idx_canon_climbs_centerline_geom
  ON public.canon_climbs USING gist(centerline_geom);

CREATE INDEX IF NOT EXISTS idx_canon_climbs_corridor_geom
  ON public.canon_climbs USING gist(corridor_geom);

CREATE INDEX IF NOT EXISTS idx_canon_climbs_gate_start_line
  ON public.canon_climbs USING gist(gate_start_line);

CREATE INDEX IF NOT EXISTS idx_canon_climbs_gate_end_line
  ON public.canon_climbs USING gist(gate_end_line);

CREATE TABLE IF NOT EXISTS public.canon_corridor_cells (
  canon_climb_id uuid NOT NULL
    REFERENCES public.canon_climbs(id) ON DELETE CASCADE,
  h3_resolution smallint NOT NULL DEFAULT 10 CHECK (h3_resolution = 10),
  tile_id text NOT NULL,
  coverage_role text NOT NULL DEFAULT 'corridor'
    CHECK (coverage_role IN ('corridor', 'gate_start', 'gate_end')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (canon_climb_id, h3_resolution, tile_id, coverage_role)
);

CREATE INDEX IF NOT EXISTS idx_canon_corridor_cells_resolution_tile
  ON public.canon_corridor_cells(h3_resolution, tile_id);

CREATE INDEX IF NOT EXISTS idx_canon_corridor_cells_climb
  ON public.canon_corridor_cells(canon_climb_id);

COMMENT ON TABLE public.canon_climbs IS
  'Versioned climb canon rows compiled from OSM road graph plus DEM and ratified before runtime use.';
COMMENT ON COLUMN public.canon_climbs.canon_id IS
  'Stable registry-owned UUID assigned at ratification. Candidate rows remain fingerprint-keyed until ratified.';
COMMENT ON COLUMN public.canon_climbs.version IS
  'Canon version for record-continuity policy. Initial ratified rows start at version 1.';
COMMENT ON COLUMN public.canon_climbs.candidate_fingerprint IS
  'Compiler fingerprint over ordered OSM way refs and span endpoints, used to dedupe candidates across recompiles.';
COMMENT ON COLUMN public.canon_climbs.centerline_polyline IS
  'Google-encoded polyline for compact API transport.';
COMMENT ON COLUMN public.canon_climbs.centerline_geom IS
  'PostGIS centerline geometry in EPSG:4326.';
COMMENT ON COLUMN public.canon_climbs.corridor_geom IS
  'Buffered canon corridor geometry in EPSG:4326, approximately 25m around the centerline.';
COMMENT ON COLUMN public.canon_climbs.gate_start_line IS
  'Start gate line segment in EPSG:4326. Traversal timing interpolates raw GPS segment crossing.';
COMMENT ON COLUMN public.canon_climbs.gate_end_line IS
  'End gate line segment in EPSG:4326. Traversal timing interpolates raw GPS segment crossing.';
COMMENT ON COLUMN public.canon_climbs.canonical_profile IS
  'Ordered JSONB array of profile samples at compiler spacing, shaped as dist_m/elev_m objects.';
COMMENT ON COLUMN public.canon_climbs.dem_source IS
  'DEM provenance, e.g. USGS 3DEP 10m local tile set.';
COMMENT ON COLUMN public.canon_climbs.osm_way_refs IS
  'Ordered OSM way references used for ODbL provenance and compiler dedupe.';
COMMENT ON COLUMN public.canon_climbs.odbl_source IS
  'ODbL attribution source for the map-derived geometry.';
COMMENT ON COLUMN public.canon_climbs.record_continuity_policy IS
  'Whether this version starts a new record board, carries records forward, or retires without a successor.';
COMMENT ON TABLE public.canon_corridor_cells IS
  'H3 resolution-10 cells covering canon climb corridors and gates for fast ride/canon membership queries.';
COMMENT ON COLUMN public.canon_corridor_cells.tile_id IS
  'H3 index as text, matching activity_tile_samples.tile_id representation.';
