-- =============================================================================
-- 076: Atomic CAL Allocation Staging Update
--
-- Fixes CRITICAL atomicity bug in CalAllocator.allocate_epoch():
--   The allocator inserts batches/leaves THEN marks staging rows as allocated
--   in separate DB calls. If it crashes between insert and update, retries
--   reprocess the same rows, creating duplicate batches.
--
-- Solution: atomic function that marks staging rows as allocated and links
-- them to a batch_id in a single transaction with an advisory lock.
-- =============================================================================

CREATE OR REPLACE FUNCTION mark_staging_allocated_atomic(
    p_staging_ids BIGINT[],
    p_batch_id BIGINT
) RETURNS INT AS $$
DECLARE
    v_updated INT;
BEGIN
    -- Advisory lock on a fixed key to serialize allocation updates
    -- (prevents concurrent allocate_epoch calls from racing)
    PERFORM pg_advisory_xact_lock(hashtext('cal_alloc_staging'));

    -- Atomically mark staging rows as allocated, but ONLY if they
    -- are not already allocated (idempotency guard)
    UPDATE cal_allocation_staging
    SET allocated = TRUE,
        batch_id = p_batch_id
    WHERE id = ANY(p_staging_ids)
      AND allocated = FALSE;

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION mark_staging_allocated_atomic IS
'Atomically mark CAL allocation staging rows as allocated and link to batch.
Skips rows already allocated (idempotency). Uses advisory lock to prevent
concurrent allocate_epoch calls from racing.';
