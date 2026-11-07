-- Migration: Update epoch anchor to Sunday 12:00 UTC
-- Per TOKENOMICS_V2.md line 234 and DECISIONS.md line 19
-- Old anchor: 1704067200 (Jan 1, 2024 00:00:00 UTC - Monday)
-- New anchor: 1704020400 (Dec 31, 2023 12:00:00 UTC - Sunday)

-- Update get_current_epoch() function with new anchor
CREATE OR REPLACE FUNCTION get_current_epoch()
RETURNS INTEGER AS $$
DECLARE
    epoch_anchor BIGINT := 1704020400;  -- Sun Dec 31 2023 12:00:00 UTC
    epoch_duration INTEGER := 604800;    -- 7 days in seconds
    current_epoch INTEGER;
BEGIN
    current_epoch := FLOOR((EXTRACT(EPOCH FROM NOW()) - epoch_anchor) / epoch_duration);
    RETURN current_epoch;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_current_epoch() IS
'Calculate current epoch number. Epochs run Sunday 12:00 UTC to Sunday 12:00 UTC per TOKENOMICS_V2.md line 234.';
