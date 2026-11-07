# RETIRED Supabase migration directory

This top-level directory is retained only as historical evidence for eight
legacy one-off SQL files. It is not a deployment or migration authority.

Current migrations live in `backend/sql`, are mirrored under
`backend/supabase/migrations`, and are applied only by
`backend/scripts/apply_sql_migrations.py`. Do not run `supabase db push` from
the repository root and do not add new SQL files here.
