-- Migration: 030_user_preferences.sql
-- Description: Add theme, dark mode, rider type, location preferences to users table
-- Date: 2024-12-24

-- =============================================================================
-- PART 1: Add new preference columns
-- =============================================================================

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS theme_id text DEFAULT 'hoo-breddin',
  ADD COLUMN IF NOT EXISTS is_dark_mode boolean DEFAULT true,
  ADD COLUMN IF NOT EXISTS rider_type text DEFAULT 'climber',
  ADD COLUMN IF NOT EXISTS location text;

-- =============================================================================
-- PART 2: Constraints for theme_id
-- =============================================================================

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_users_theme_id'
  ) THEN
    ALTER TABLE public.users
      ADD CONSTRAINT chk_users_theme_id
      CHECK (theme_id IN ('hoo-breddin', 'water', 'sunny', 'safari', 'moss', 'foundries'));
  END IF;
END $$;

-- =============================================================================
-- PART 3: Constraints for rider_type
-- =============================================================================

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_users_rider_type'
  ) THEN
    ALTER TABLE public.users
      ADD CONSTRAINT chk_users_rider_type
      CHECK (rider_type IN ('climber', 'sprinter', 'tt', 'rouleur', 'allrounder', 'diesel'));
  END IF;
END $$;

-- =============================================================================
-- PART 4: Comments
-- =============================================================================

COMMENT ON COLUMN public.users.theme_id IS 'Color theme preference (hoo-breddin, water, sunny, safari, moss, foundries)';
COMMENT ON COLUMN public.users.is_dark_mode IS 'Dark/light mode preference';
COMMENT ON COLUMN public.users.rider_type IS 'Rider archetype for UI customization';
COMMENT ON COLUMN public.users.location IS 'User location for profile display';
