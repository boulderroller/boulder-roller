SET LOCAL lock_timeout = '5s';

-- Read one exact revision without scanning every ride's canonical patterns.
CREATE INDEX IF NOT EXISTS patterns_climb_registry_traversal
    ON public.patterns_climb ((match_trace->>'registry_id'), id)
    WHERE detector_version = 'canon_traversal_v1';
