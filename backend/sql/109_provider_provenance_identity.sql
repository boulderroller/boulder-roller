-- Enforce trusted-provider ride provenance identity for future writes.

CREATE OR REPLACE FUNCTION public.br_normalize_provider_import_source(provider_source text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT CASE
    WHEN provider_source IN ('strava', 'strava_stream_reconstructed_gpx') THEN 'strava'
    WHEN provider_source = 'garmin' THEN 'garmin'
    WHEN provider_source = 'wahoo' THEN 'wahoo'
    ELSE NULL
  END;
$$;

CREATE INDEX IF NOT EXISTS idx_rides_provider_activity_identity_lookup
  ON public.rides(user_id, import_source_id)
  WHERE public.br_normalize_provider_import_source(import_source) IS NOT NULL
    AND import_source_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.enforce_ride_provider_activity_identity()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  normalized_source text;
  normalized_source_id text;
BEGIN
  normalized_source := public.br_normalize_provider_import_source(NEW.import_source);
  IF normalized_source IS NULL THEN
    RETURN NEW;
  END IF;

  normalized_source_id := lower(btrim(coalesce(NEW.import_source_id, '')));
  IF normalized_source_id = '' THEN
    RAISE EXCEPTION 'trusted provider ride import_source_id is required'
      USING ERRCODE = '23514';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM public.rides existing
    WHERE existing.user_id = NEW.user_id
      AND existing.id IS DISTINCT FROM NEW.id
      AND public.br_normalize_provider_import_source(existing.import_source) = normalized_source
      AND lower(btrim(coalesce(existing.import_source_id, ''))) = normalized_source_id
    LIMIT 1
  ) THEN
    RAISE EXCEPTION 'duplicate trusted provider ride identity: %, %',
      normalized_source,
      NEW.import_source_id
      USING ERRCODE = '23505';
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_enforce_ride_provider_activity_identity ON public.rides;
CREATE TRIGGER trg_enforce_ride_provider_activity_identity
  BEFORE INSERT OR UPDATE OF user_id, import_source, import_source_id
  ON public.rides
  FOR EACH ROW
  EXECUTE FUNCTION public.enforce_ride_provider_activity_identity();

COMMENT ON FUNCTION public.enforce_ride_provider_activity_identity() IS
  'Requires trusted provider rides to carry a provider activity id and rejects duplicate provider activity identity for future writes.';
