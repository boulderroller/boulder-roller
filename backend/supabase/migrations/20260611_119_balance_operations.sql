-- Durable ledger for Boulder Roller Balance transaction-coordinator attempts.

CREATE TABLE IF NOT EXISTS public.balance_operations (
  operation_id TEXT PRIMARY KEY,
  rider_account_id TEXT,
  protocol_wallet TEXT NOT NULL,
  action_type TEXT NOT NULL,
  authority_model TEXT NOT NULL,
  asset TEXT,
  amount TEXT,
  source TEXT,
  destination TEXT,
  idempotency_key TEXT NOT NULL,
  prepared_message_hash TEXT,
  fee_payer TEXT,
  policy_or_delegate_id TEXT,
  tx_signature TEXT,
  confirmation_status TEXT NOT NULL DEFAULT 'prepared',
  projection_status TEXT NOT NULL DEFAULT 'not_started',
  rider_state TEXT,
  retry_count INTEGER NOT NULL DEFAULT 0,
  failure_reason TEXT,
  reference_type TEXT,
  reference_id TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  confirmed_at TIMESTAMPTZ,
  CONSTRAINT balance_operations_confirmation_status_check CHECK (
    confirmation_status IN ('prepared', 'submitted', 'confirmed', 'finalized', 'failed', 'expired')
  ),
  CONSTRAINT balance_operations_projection_status_check CHECK (
    projection_status IN ('not_started', 'pending', 'recorded', 'delayed', 'needs_review')
  ),
  CONSTRAINT balance_operations_rider_state_check CHECK (
    rider_state IN ('Counted', 'Collectable', 'Collected', 'Pending', 'Delayed', 'Needs review')
  ),
  CONSTRAINT balance_operations_retry_count_check CHECK (retry_count >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_balance_operations_idempotency_key
  ON public.balance_operations(idempotency_key);

CREATE INDEX IF NOT EXISTS idx_balance_operations_wallet_created_at
  ON public.balance_operations(protocol_wallet, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_balance_operations_action_status
  ON public.balance_operations(action_type, confirmation_status, projection_status);

CREATE INDEX IF NOT EXISTS idx_balance_operations_reference
  ON public.balance_operations(reference_type, reference_id)
  WHERE reference_type IS NOT NULL AND reference_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_balance_operations_policy_or_delegate
  ON public.balance_operations(policy_or_delegate_id)
  WHERE policy_or_delegate_id IS NOT NULL;

ALTER TABLE public.balance_operations ENABLE ROW LEVEL SECURITY;

-- Backend/service-role owned ledger. Do not add anon/authenticated policies
-- until there is a dedicated rider or admin read model over this table.

COMMENT ON TABLE public.balance_operations IS
  'Transaction-coordinator ledger for Boulder Roller Balance operations, retries, support, and admin inspection.';

COMMENT ON COLUMN public.balance_operations.authority_model IS
  'backend_authorized, permissionless_for_rider, app_balance, privy_policy_signer, spl_delegate, or wallet_boundary.';

COMMENT ON COLUMN public.balance_operations.rider_state IS
  'Primary rider-facing state: Counted, Collectable, Collected, Pending, Delayed, or Needs review.';
