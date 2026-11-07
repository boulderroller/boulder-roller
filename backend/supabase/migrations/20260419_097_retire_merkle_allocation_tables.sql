-- =============================================================================
-- 097: Retire V4-A deleted allocation tables
--
-- V4-A replaced batched CAL allocation with receipt-protected
-- RideAttestation -> credit_cal -> record_climb_completion flows. These tables
-- and helper function are no longer written by runtime code or the indexer.
-- =============================================================================

DROP TABLE IF EXISTS indexed_alloc_batches;

DROP FUNCTION IF EXISTS mark_staging_allocated_atomic(BIGINT[], BIGINT);
DROP TABLE IF EXISTS cal_allocation_leaves;
DROP TABLE IF EXISTS cal_allocation_staging;
DROP TABLE IF EXISTS cal_allocation_batches;
