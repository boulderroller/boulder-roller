-- Read-side analytics for every accepted canonical traversal. No economic writes.
SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.climb_efforts (
    id UUID PRIMARY KEY REFERENCES public.patterns_climb(id) ON DELETE CASCADE,
    ride_id UUID NOT NULL REFERENCES public.rides(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    climb_id UUID NOT NULL REFERENCES public.canon_climbs(id),
    canon_version INTEGER NOT NULL CHECK (canon_version > 0),
    start_offset_s DOUBLE PRECISION NOT NULL CHECK (start_offset_s >= 0),
    end_offset_s DOUBLE PRECISION NOT NULL CHECK (end_offset_s > start_offset_s),
    achieved_at TIMESTAMPTZ NOT NULL,
    time_s INTEGER NOT NULL CHECK (time_s > 0),
    avg_power_w DOUBLE PRECISION CHECK (avg_power_w >= 0 AND avg_power_w < 'Infinity'),
    estimated_power_w DOUBLE PRECISION CHECK (estimated_power_w >= 0 AND estimated_power_w < 'Infinity'),
    estimated_power_range_w JSONB,
    power_kind TEXT NOT NULL CHECK (power_kind IN ('measured', 'estimated')),
    w_per_kg DOUBLE PRECISION CHECK (w_per_kg >= 0 AND w_per_kg < 'Infinity'),
    metrics JSONB NOT NULL CHECK (jsonb_typeof(metrics) = 'object'),
    engine_version INTEGER NOT NULL CHECK (engine_version > 0),
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (power_kind = 'measured' OR (w_per_kg IS NULL AND avg_power_w IS NULL))
);
CREATE INDEX IF NOT EXISTS climb_efforts_best ON public.climb_efforts(climb_id, user_id, time_s, achieved_at, id);
CREATE INDEX IF NOT EXISTS climb_efforts_ride ON public.climb_efforts(ride_id);
ALTER TABLE public.climb_efforts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.climb_efforts FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON public.climb_efforts TO service_role;

CREATE OR REPLACE FUNCTION public.store_climb_efforts(
    p_ride_id UUID, p_user_id UUID, p_inputs JSONB, p_efforts JSONB
) RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE v_ride public.rides; e JSONB; p public.patterns_climb;
BEGIN
    PERFORM 1 FROM public.users WHERE id=p_user_id AND account_state='active' FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'effort owner unavailable'; END IF;
    SELECT * INTO STRICT v_ride FROM public.rides WHERE id=p_ride_id AND user_id=p_user_id FOR UPDATE;
    IF coalesce(v_ride.processing_status = ANY(public.training_counted_statuses()),false) IS NOT TRUE
    THEN RAISE EXCEPTION 'training ride ineligible'; END IF;
    IF NOT public.training_payment_idle(p_ride_id) THEN RAISE EXCEPTION 'training payment attempt active'; END IF;
    IF v_ride.training_inputs IS DISTINCT FROM p_inputs THEN RAISE EXCEPTION 'training input snapshot conflict'; END IF;
    IF jsonb_typeof(p_efforts) IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'effort array required'; END IF;
    FOR e IN SELECT value FROM jsonb_array_elements(p_efforts) LOOP
        SELECT * INTO STRICT p FROM public.patterns_climb WHERE id=(e->>'id')::UUID AND activity_id=p_ride_id;
        IF p.detector_version IS DISTINCT FROM 'canon_traversal_v1'
            OR p.match_trace->>'authority' = 'discovery_only'
            OR (p.match_trace->>'registry_id')::UUID IS DISTINCT FROM (e->>'climb_id')::UUID
            OR (p.match_trace->>'canon_version')::INTEGER IS DISTINCT FROM (e->>'canon_version')::INTEGER
            OR (p.match_trace->'gate_crossings'->>'start_time_s_raw')::DOUBLE PRECISION
                IS DISTINCT FROM (e->>'start_offset_s')::DOUBLE PRECISION
            OR (p.match_trace->'gate_crossings'->>'finish_time_s_raw')::DOUBLE PRECISION
                IS DISTINCT FROM (e->>'end_offset_s')::DOUBLE PRECISION
            OR p.time_s IS DISTINCT FROM (e->'metrics'->>'time_s')::INTEGER
        THEN RAISE EXCEPTION 'effort canonical span conflict'; END IF;
        IF EXISTS (SELECT FROM public.climb_efforts WHERE id=p.id
            AND engine_version > (e->'metrics'->>'engine_version')::INTEGER)
        THEN RAISE EXCEPTION 'effort version regression'; END IF;
        INSERT INTO public.climb_efforts(id,ride_id,user_id,climb_id,canon_version,
            start_offset_s,end_offset_s,achieved_at,time_s,avg_power_w,estimated_power_w,estimated_power_range_w,power_kind,w_per_kg,metrics,engine_version)
        VALUES(p.id,p_ride_id,p_user_id,(e->>'climb_id')::UUID,(e->>'canon_version')::INTEGER,
            (e->>'start_offset_s')::DOUBLE PRECISION,(e->>'end_offset_s')::DOUBLE PRECISION,
            (e->>'achieved_at')::TIMESTAMPTZ,p.time_s,(e->'metrics'->>'avg_power_w')::DOUBLE PRECISION,
            (e->'metrics'->>'estimated_power_w')::DOUBLE PRECISION,e->'metrics'->'estimated_power_range_w',
            e->'metrics'->>'power_kind',(e->'metrics'->>'w_per_kg')::DOUBLE PRECISION,
            e->'metrics',(e->'metrics'->>'engine_version')::INTEGER)
        ON CONFLICT(id) DO UPDATE SET
            achieved_at=excluded.achieved_at,avg_power_w=excluded.avg_power_w,
            estimated_power_w=excluded.estimated_power_w,estimated_power_range_w=excluded.estimated_power_range_w,
            power_kind=excluded.power_kind,w_per_kg=excluded.w_per_kg,
            metrics=excluded.metrics,engine_version=excluded.engine_version,computed_at=now();
    END LOOP;
END $$;
REVOKE ALL ON FUNCTION public.store_climb_efforts(UUID,UUID,JSONB,JSONB) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.store_climb_efforts(UUID,UUID,JSONB,JSONB) TO service_role;

-- Migration 152 detaches retained patterns before checking all ride/user FKs.
-- Purge these private reads at that detachment, in the same transaction, so
-- its fail-closed residue checks still pass. Pending deletion is reversible.
CREATE OR REPLACE FUNCTION public.clear_detached_climb_effort() RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    DELETE FROM public.climb_efforts WHERE id=OLD.id;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.clear_detached_climb_effort() FROM PUBLIC,anon,authenticated;
CREATE OR REPLACE TRIGGER clear_detached_climb_effort AFTER UPDATE OF activity_id ON public.patterns_climb
FOR EACH ROW WHEN (OLD.activity_id IS DISTINCT FROM NEW.activity_id)
EXECUTE FUNCTION public.clear_detached_climb_effort();
