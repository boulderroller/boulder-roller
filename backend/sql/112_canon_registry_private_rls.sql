-- Keep canon registry tables private until a deliberate public read API exists.
-- Complements backend/sql/111_canon_climb_registry.sql.

ALTER TABLE public.canon_climbs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.canon_corridor_cells ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.canon_climbs FROM anon, authenticated;
REVOKE ALL ON TABLE public.canon_corridor_cells FROM anon, authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.canon_climbs TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.canon_corridor_cells TO service_role;

COMMENT ON TABLE public.canon_climbs IS
  'Versioned climb canon rows compiled from OSM road graph plus DEM and ratified before runtime use. Private by default; exposed only through server-owned APIs.';
COMMENT ON TABLE public.canon_corridor_cells IS
  'H3 resolution-10 cells covering canon climb corridors and gates for fast ride/canon membership queries. Private by default; exposed only through server-owned APIs.';
