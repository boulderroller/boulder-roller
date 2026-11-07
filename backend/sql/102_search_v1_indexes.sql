-- search.v1 app-discovery indexes.
-- Keep this light for beta: Postgres trigram/prefix search over projected app
-- surfaces, not an external search service.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_users_username_trgm
ON public.users USING GIN (username gin_trgm_ops)
WHERE username IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_users_display_name_trgm
ON public.users USING GIN (display_name gin_trgm_ops)
WHERE display_name IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_users_wallet_prefix
ON public.users (wallet)
WHERE wallet IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_climb_vault_name_trgm
ON public.climb_vault USING GIN (name gin_trgm_ops)
WHERE active = TRUE;

CREATE INDEX IF NOT EXISTS idx_climb_vault_region_trgm
ON public.climb_vault USING GIN (region gin_trgm_ops)
WHERE active = TRUE AND region IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_indexed_vaults_name_trgm
ON public.indexed_vaults USING GIN (name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_rides_file_name_trgm
ON public.rides USING GIN (file_name gin_trgm_ops)
WHERE file_name IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_rides_user_started_search
ON public.rides (user_id, started_at DESC);
