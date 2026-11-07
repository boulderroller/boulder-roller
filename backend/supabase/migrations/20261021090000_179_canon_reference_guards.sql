-- FK-like row locking for new pattern references stored without an FK.
-- Allows online successor publication and safe deletion of unused successors.
SET LOCAL lock_timeout = '5s';

CREATE OR REPLACE FUNCTION public.br_lock_pattern_canon_reference()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE registry UUID;
BEGIN
    -- Patterns without a registry reference need no lock. Retired rows remain
    -- valid: a match already in flight may finish against its original gates.
    IF NEW.match_trace->>'registry_id' IS NULL THEN RETURN NEW; END IF;
    registry := (NEW.match_trace->>'registry_id')::UUID;
    PERFORM 1 FROM public.canon_climbs WHERE id=registry FOR KEY SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'canonical pattern references a removed registry row; retry matching'
            USING ERRCODE='23503';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.br_lock_pattern_canon_reference() FROM PUBLIC,anon,authenticated,service_role;
CREATE OR REPLACE TRIGGER br_pattern_canon_reference
BEFORE INSERT ON public.patterns_climb
FOR EACH ROW EXECUTE FUNCTION public.br_lock_pattern_canon_reference();
