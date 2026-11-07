-- Enable PostGIS and create segments table with spatial indexes
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

DROP TABLE IF EXISTS public.segments CASCADE;

CREATE TABLE public.segments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  geom geometry(LINESTRING, 4326) NOT NULL,
  length_m numeric NOT NULL,
  elev_gain_m numeric,
  avg_grade numeric,
  bbox geometry(POLYGON, 4326) GENERATED ALWAYS AS (ST_Envelope(geom)) STORED,
  difficulty smallint NOT NULL DEFAULT 1,
  verified boolean NOT NULL DEFAULT false,
  created_by text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_segments_geom ON public.segments USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_segments_length_m ON public.segments USING BTREE (length_m);
CREATE INDEX IF NOT EXISTS idx_segments_name_trgm ON public.segments USING GIN (name gin_trgm_ops);

CREATE OR REPLACE FUNCTION public.segments_search(
  west double precision DEFAULT NULL,
  south double precision DEFAULT NULL,
  east double precision DEFAULT NULL,
  north double precision DEFAULT NULL,
  name_query text DEFAULT NULL
)
RETURNS SETOF public.segments
LANGUAGE sql
STABLE
AS $$
  SELECT *
  FROM public.segments
  WHERE (
        west IS NULL OR south IS NULL OR east IS NULL OR north IS NULL
        OR geom && ST_MakeEnvelope(west, south, east, north, 4326)
      )
    AND (
        name_query IS NULL OR name ILIKE '%' || name_query || '%'
      );
$$;
