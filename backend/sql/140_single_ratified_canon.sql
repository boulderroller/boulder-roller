-- A canon_id has one active ratified version. Successors retire predecessors.

CREATE UNIQUE INDEX IF NOT EXISTS idx_canon_climbs_one_ratified_version
    ON public.canon_climbs(canon_id)
    WHERE status = 'ratified';
