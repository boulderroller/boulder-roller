-- One unresolved Stage 1 action per owner and economic intent, across tabs.
-- Operation insertion precedes submission. Terminal ledger updates release
-- this exclusion; elapsed wall time never does. Existing RLS remains intact.
BEGIN;
SET LOCAL lock_timeout = '5s';
-- A normal build blocks writes even after it acquires its lock. Bound that
-- duration too; production table size/build time has not been measured here.
-- If this cap is insufficient, prebuild the exact index CONCURRENTLY outside
-- a transaction and verify its definition/indisvalid before retrying 174.
-- CONCURRENTLY cannot run inside the required atomic migration wrapper.
SET LOCAL statement_timeout = '10s';
CREATE UNIQUE INDEX IF NOT EXISTS idx_balance_stage1_pending_intent
ON public.balance_operations (
  rider_account_id, protocol_wallet, action_type,
  (metadata->>'program'), (metadata->>'genesis'), (metadata->>'intent_key')
)
WHERE left(action_type, 7) = 'stage1_'
  AND confirmation_status IN ('prepared', 'submitted')
  AND metadata->>'intent_key' IS NOT NULL;
COMMIT;
