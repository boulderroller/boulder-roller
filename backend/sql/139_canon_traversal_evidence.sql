-- Preserve exact D11 traversal evidence across the phase-1/phase-2 worker handoff.
-- The rider map track remains compressed and is never authoritative for canon.

CREATE TABLE IF NOT EXISTS public.canon_traversal_evidence (
    ride_id UUID NOT NULL REFERENCES public.rides(id) ON DELETE CASCADE,
    ride_hash_hex TEXT NOT NULL CHECK (ride_hash_hex ~ '^[0-9a-f]{64}$'),
    ride_parser_version INTEGER NOT NULL CHECK (ride_parser_version > 0),
    evidence_version TEXT NOT NULL CHECK (
        evidence_version = 'canon_traversal_evidence_v1'
    ),
    sample_count INTEGER NOT NULL CHECK (sample_count BETWEEN 0 AND 250000),
    sample_digest TEXT NOT NULL CHECK (sample_digest ~ '^[0-9a-f]{64}$'),
    samples JSONB NOT NULL CHECK (
        jsonb_typeof(samples) = 'array'
        AND jsonb_array_length(samples) = sample_count
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ride_id, ride_hash_hex, ride_parser_version, evidence_version)
);

CREATE OR REPLACE FUNCTION public.br_guard_canon_traversal_evidence_immutable()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.ride_id IS DISTINCT FROM NEW.ride_id
       OR OLD.ride_hash_hex IS DISTINCT FROM NEW.ride_hash_hex
       OR OLD.ride_parser_version IS DISTINCT FROM NEW.ride_parser_version
       OR OLD.evidence_version IS DISTINCT FROM NEW.evidence_version
       OR OLD.sample_count IS DISTINCT FROM NEW.sample_count
       OR OLD.sample_digest IS DISTINCT FROM NEW.sample_digest
       OR OLD.samples IS DISTINCT FROM NEW.samples THEN
        RAISE EXCEPTION 'canon traversal evidence is immutable for a ride identity'
            USING ERRCODE = '22000';
    END IF;
    NEW.created_at := OLD.created_at;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_guard_canon_traversal_evidence_immutable
    ON public.canon_traversal_evidence;
CREATE TRIGGER trg_guard_canon_traversal_evidence_immutable
BEFORE UPDATE ON public.canon_traversal_evidence
FOR EACH ROW EXECUTE FUNCTION public.br_guard_canon_traversal_evidence_immutable();

ALTER TABLE public.canon_traversal_evidence ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.canon_traversal_evidence FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.br_guard_canon_traversal_evidence_immutable()
    FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.canon_traversal_evidence TO service_role;

COMMENT ON TABLE public.canon_traversal_evidence IS
  'Private, immutable, identity-bound raw GPS evidence for exact D11 canon traversal. The compressed rides.gps_track map projection is not authoritative.';
