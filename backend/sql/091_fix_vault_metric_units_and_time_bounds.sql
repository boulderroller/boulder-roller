-- Normalize indexed vault metric semantics and recalculate validation bounds.
--
-- On-chain Vault.vert_m is stored as meters * 10 and avg_gradient_pct as
-- percent * 100. The indexed_vaults read model stores human units: meters and
-- percent. Time validation also needs VAM seconds, not minutes.

CREATE OR REPLACE FUNCTION calculate_vault_time_bounds(
    p_distance_m INTEGER,
    p_vert_m DOUBLE PRECISION
) RETURNS TABLE(min_time_s INTEGER, max_time_s INTEGER) AS $$
DECLARE
    distance_min_time INTEGER;
    vam_min_time INTEGER;
    distance_max_time INTEGER;
BEGIN
    distance_min_time := GREATEST(30, CEIL(GREATEST(p_distance_m, 1) / 11.1)::INTEGER);

    IF p_vert_m > 0 THEN
        vam_min_time := CEIL(p_vert_m * 3600 / 2000)::INTEGER;
    ELSE
        vam_min_time := 0;
    END IF;

    distance_max_time := CEIL(GREATEST(p_distance_m, 1) / 1.4)::INTEGER;

    RETURN QUERY SELECT
        GREATEST(30, distance_min_time, vam_min_time) AS min_time_s,
        GREATEST(
            GREATEST(30, distance_min_time, vam_min_time) * 2,
            LEAST(21600, distance_max_time)
        ) AS max_time_s;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

CREATE OR REPLACE FUNCTION trg_calculate_vault_time_bounds()
RETURNS TRIGGER AS $$
DECLARE
    v_min INTEGER;
    v_max INTEGER;
BEGIN
    SELECT min_time_s, max_time_s INTO v_min, v_max
    FROM calculate_vault_time_bounds(NEW.distance_m, NEW.vert_m);

    NEW.min_valid_time_s := v_min;
    NEW.max_valid_time_s := v_max;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_indexed_vaults_time_bounds ON indexed_vaults;

CREATE TRIGGER trg_indexed_vaults_time_bounds
    BEFORE INSERT OR UPDATE OF distance_m, vert_m ON indexed_vaults
    FOR EACH ROW
    WHEN (NEW.validation_enabled IS DISTINCT FROM FALSE)
    EXECUTE FUNCTION trg_calculate_vault_time_bounds();

WITH raw_metric_rows AS (
    SELECT id
    FROM indexed_vaults
    WHERE avg_gradient_pct >= 100
)
UPDATE indexed_vaults v
SET vert_m = v.vert_m / 10.0
FROM raw_metric_rows r
WHERE v.id = r.id;

UPDATE indexed_vaults
SET avg_gradient_pct = avg_gradient_pct / 100.0
WHERE avg_gradient_pct >= 100;

UPDATE indexed_vaults v
SET (min_valid_time_s, max_valid_time_s) = (
    SELECT min_time_s, max_time_s
    FROM calculate_vault_time_bounds(v.distance_m, v.vert_m)
)
WHERE v.validation_enabled IS DISTINCT FROM FALSE;

COMMENT ON COLUMN indexed_vaults.vert_m IS
'Vertical gain in meters. On-chain stores this as meters * 10.';

COMMENT ON COLUMN indexed_vaults.avg_gradient_pct IS
'Average gradient percentage. On-chain stores this as pct * 100.';

COMMENT ON TRIGGER trg_indexed_vaults_time_bounds ON indexed_vaults IS
'Automatically calculate time bounds when vault distance or vertical gain changes.';
