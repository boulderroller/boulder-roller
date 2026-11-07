-- Canonical creation for the previously Supabase-only Balance ledger.
-- Keep the historical 20260611_119 mirror immutable. This additive repair also
-- succeeds where that mirror was applied; it does not enable Balance rollout.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '10s';

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

-- 152 only fenced tables present when it ran. Production had no Balance
-- ledger then. Attach that same ratified fence now, without replacing an
-- existing trigger on installations that already applied the old mirror.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_trigger
    WHERE tgrelid = 'public.balance_operations'::regclass
      AND tgname = 'account_deletion_write_fence' AND NOT tgisinternal
  ) THEN
    CREATE TRIGGER account_deletion_write_fence
      BEFORE INSERT OR UPDATE OR DELETE ON public.balance_operations
      FOR EACH ROW EXECUTE FUNCTION public.account_deletion_write_fence('true');
  END IF;
END;
$$;

-- Preserve 152's Balance policy, while Stage 1 receipts only block while
-- their persisted confirmation status is in flight. 170/171 keep their own
-- keeper blockers in the public wrapper; 154/155 also wrap the original 152
-- function. Patch that innermost predecessor, never any of those wrappers.
DO $stage1_deletion_blockers$
DECLARE
    v_signature REGPROCEDURE := COALESCE(
        pg_catalog.to_regprocedure('public.br_account_deletion_db_blockers_pre_threshold(uuid,text)'),
        pg_catalog.to_regprocedure('public.br_account_deletion_db_blockers_pre_keeper(uuid,text)'),
        pg_catalog.to_regprocedure('public.br_account_deletion_db_blockers(uuid,text)')
    );
    v_definition TEXT;
    v_old_claim TEXT := $old$WHERE (operation.rider_account_id = $1::TEXT OR operation.protocol_wallet = $2)
              AND NOT ($old$;
    v_new_claim TEXT := $new$WHERE (operation.rider_account_id = $1::TEXT OR operation.protocol_wallet = $2)
              AND pg_catalog.left(operation.action_type, 7) IS DISTINCT FROM 'stage1_'
              AND NOT ($new$;
    v_old_policy TEXT := $old$WHERE operation.rider_account_id = $1::TEXT OR operation.protocol_wallet = $2$old$;
    v_new_policy TEXT := $new$WHERE (operation.rider_account_id = $1::TEXT OR operation.protocol_wallet = $2)
              AND pg_catalog.left(operation.action_type, 7) IS DISTINCT FROM 'stage1_'$new$;
    v_anchor TEXT := $anchor$    SELECT COALESCE(pg_catalog.sum(source_count), 0)::BIGINT$anchor$;
    v_pending TEXT := $pending$    -- Stage 1 temporary operations follow, never suppress, the Balance fallback.
    IF pg_catalog.to_regclass('public.balance_operations') IS NOT NULL THEN
        EXECUTE $query$
            SELECT count(*) FROM public.balance_operations AS operation
            WHERE (operation.rider_account_id = $1::TEXT OR operation.protocol_wallet = $2)
              AND pg_catalog.left(operation.action_type, 7) = 'stage1_'
              AND operation.confirmation_status IN ('prepared', 'submitted')
        $query$ INTO v_count USING p_user_id, p_wallet;
        IF v_count > 0 THEN
            v_blockers := v_blockers || pg_catalog.jsonb_build_array(
                pg_catalog.jsonb_build_object(
                    'code', 'claim_remains', 'category', 'processing',
                    'count', v_count, 'source', 'balance_operations',
                    'action', 'retry'
                )
            );
        END IF;
    END IF;

$pending$;
BEGIN
    IF v_signature IS NULL THEN
        RAISE EXCEPTION 'account deletion blocker function is missing';
    END IF;
    SELECT pg_catalog.pg_get_functiondef(v_signature) INTO v_definition;
    IF pg_catalog.strpos(v_definition, v_new_claim) > 0
       AND pg_catalog.strpos(v_definition, v_new_policy) > 0
       AND pg_catalog.strpos(v_definition, v_pending) > 0
       AND pg_catalog.strpos(v_definition, v_old_claim) = 0
       AND pg_catalog.strpos(v_definition, v_old_policy) = 0 THEN
        RETURN;
    END IF;
    IF (pg_catalog.length(v_definition) - pg_catalog.length(pg_catalog.replace(v_definition, v_old_claim, ''))) <> pg_catalog.length(v_old_claim)
       OR (pg_catalog.length(v_definition) - pg_catalog.length(pg_catalog.replace(v_definition, v_old_policy, ''))) <> pg_catalog.length(v_old_policy)
       OR (pg_catalog.length(v_definition) - pg_catalog.length(pg_catalog.replace(v_definition, v_anchor, ''))) <> pg_catalog.length(v_anchor)
       OR pg_catalog.strpos(v_definition, v_pending) > 0 THEN
        RAISE EXCEPTION 'account deletion Balance blocker source drifted';
    END IF;
    v_definition := pg_catalog.replace(v_definition, v_old_claim, v_new_claim);
    v_definition := pg_catalog.replace(v_definition, v_old_policy, v_new_policy);
    v_definition := pg_catalog.replace(v_definition, v_anchor, v_pending || v_anchor);
    -- CREATE OR REPLACE retains the function's owner, ACL and identity.
    EXECUTE v_definition;
END;
$stage1_deletion_blockers$;

-- Removing a preflight blocker must not strand the same rider at the final
-- residue check. Follow PROTOCOL_TRUTHS 10.1 and 152's token_transactions rule:
-- retain economic facts privately, anonymize the actor, remove personal traces.
DO $stage1_deletion_retention$
DECLARE
    v_signature REGPROCEDURE := COALESCE(
        pg_catalog.to_regprocedure('public.finalize_account_anonymization_pre_keeper(uuid,uuid,uuid)'),
        pg_catalog.to_regprocedure('public.finalize_account_anonymization(uuid,uuid,uuid)')
    );
    v_definition TEXT;
    v_anchor TEXT := $anchor$    DELETE FROM public.auth_refresh_tokens WHERE wallet = v_wallet;$anchor$;
    v_retention TEXT := $retention$    -- Retain terminal Stage 1 facts under the already-created anonymous actor.
    -- This runs only after 152's lease, storage, wallet fence and blocker checks.
    IF pg_catalog.to_regclass('public.balance_operations') IS NOT NULL THEN
        EXECUTE $query$
            UPDATE public.balance_operations
            SET operation_id = 'anonymous:' || pg_catalog.gen_random_uuid()::TEXT,
                idempotency_key = 'anonymous:' || pg_catalog.gen_random_uuid()::TEXT,
                rider_account_id = $3::TEXT, protocol_wallet = $4,
                metadata = '{}'::JSONB, tx_signature = NULL,
                source = NULL, destination = NULL, fee_payer = NULL,
                prepared_message_hash = NULL, policy_or_delegate_id = NULL,
                failure_reason = NULL, reference_type = NULL, reference_id = NULL
            WHERE (rider_account_id = $1::TEXT OR protocol_wallet = $2)
              AND pg_catalog.left(action_type, 7) = 'stage1_'
              AND confirmation_status IN ('confirmed', 'finalized', 'failed', 'expired')
        $query$ USING p_user_id, v_wallet, v_marker, v_anonymous_wallet;
    END IF;

$retention$;
BEGIN
    IF v_signature IS NULL THEN
        RAISE EXCEPTION 'account deletion finalizer is missing';
    END IF;
    SELECT pg_catalog.pg_get_functiondef(v_signature) INTO v_definition;
    IF pg_catalog.strpos(v_definition, v_retention || v_anchor) > 0 THEN
        RETURN;
    END IF;
    IF (pg_catalog.length(v_definition) - pg_catalog.length(pg_catalog.replace(v_definition, v_anchor, ''))) <> pg_catalog.length(v_anchor)
       OR pg_catalog.strpos(v_definition, v_retention) > 0 THEN
        RAISE EXCEPTION 'account deletion finalizer source drifted';
    END IF;
    EXECUTE pg_catalog.replace(v_definition, v_anchor, v_retention || v_anchor);
END;
$stage1_deletion_retention$;

COMMIT;
