-- Admission is an API preparation policy, never program authority.
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS cohort_admitted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS cohort_admitted_by TEXT;
