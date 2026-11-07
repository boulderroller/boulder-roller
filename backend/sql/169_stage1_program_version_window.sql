-- Service observations are separate from finalized account projections.
-- Both services persist before exposing a version-gated capability. This
-- atomic high-water mark survives restarts and RPC-provider changes.
CREATE TABLE public.program_version_observations (
    genesis_hash TEXT NOT NULL CHECK (length(genesis_hash) > 0),
    program_id TEXT NOT NULL CHECK (length(program_id) > 0),
    highest_version SMALLINT NOT NULL CHECK (highest_version BETWEEN 0 AND 255),
    PRIMARY KEY (genesis_hash, program_id)
);

ALTER TABLE public.program_version_observations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.program_version_observations FROM PUBLIC, anon, authenticated, service_role;

CREATE FUNCTION public.observe_program_version(
    p_genesis_hash TEXT, p_program_id TEXT, p_version SMALLINT
) RETURNS SMALLINT
LANGUAGE sql VOLATILE SECURITY INVOKER SET search_path = ''
AS $$
    INSERT INTO public.program_version_observations AS seen
        (genesis_hash, program_id, highest_version)
    VALUES (p_genesis_hash, p_program_id, p_version)
    ON CONFLICT (genesis_hash, program_id) DO UPDATE
        SET highest_version = GREATEST(seen.highest_version, EXCLUDED.highest_version)
    RETURNING highest_version;
$$;

REVOKE ALL ON FUNCTION public.observe_program_version(TEXT, TEXT, SMALLINT)
    FROM PUBLIC, anon, authenticated, service_role;
