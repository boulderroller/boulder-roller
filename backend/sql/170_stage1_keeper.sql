-- boulderroller-v2-4a2s1. Additive, opt-in Stage 1 keeper persistence.
-- No legacy table, settlement queue, or payout meaning is changed.
BEGIN;
SET LOCAL lock_timeout = '5s';
-- One keeper database belongs to one genesis, including unsigned plans and
-- boundary archives. Binding never alters the claim/Merkle namespace.
CREATE TABLE public.stage1_keeper_network (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    genesis TEXT NOT NULL CHECK (length(genesis) > 0)
);
CREATE FUNCTION public.stage1_keeper_network_immutable() RETURNS trigger
LANGUAGE plpgsql SET search_path='' AS $$
BEGIN
 RAISE EXCEPTION 'Stage 1 keeper genesis binding is immutable';
END $$;
CREATE TRIGGER stage1_keeper_network_immutable BEFORE UPDATE OR DELETE
ON public.stage1_keeper_network FOR EACH ROW EXECUTE FUNCTION public.stage1_keeper_network_immutable();
ALTER TABLE public.stage1_keeper_network ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.stage1_keeper_network FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.stage1_keeper_network_immutable() FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT,INSERT ON public.stage1_keeper_network TO service_role;
CREATE TABLE public.stage1_keeper_scopes (
    id TEXT PRIMARY KEY,
    program TEXT NOT NULL,
    city TEXT NOT NULL,
    hill TEXT NOT NULL,
    mint TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'cash' CHECK (kind IN ('cash','dung')),
    canon_id UUID NOT NULL,
    launch BIGINT NOT NULL,
    next_week BIGINT NOT NULL CHECK (next_week >= 0),
    blocked BOOLEAN NOT NULL DEFAULT FALSE,
    block_kind TEXT,
    lease_token UUID,
    lease_until TIMESTAMPTZ,
    retry_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(program,hill,mint)
);
-- Historical chain inputs, captured by an authorized boundary attestor. The
-- keeper never overwrites these with the current indexer projection. Evidence
-- includes the finalized slot, exact boundary and account bytes/digests.
CREATE TABLE public.stage1_keeper_boundaries (
    scope_id TEXT NOT NULL REFERENCES public.stage1_keeper_scopes(id),
    week BIGINT NOT NULL CHECK (week >= 0),
    inputs JSONB NOT NULL CHECK (jsonb_typeof(inputs)='object'),
    digest TEXT NOT NULL CHECK (digest ~ '^[0-9a-f]{64}$'),
    commitment_inputs JSONB NOT NULL,
    request_digest TEXT NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(scope_id,week)
);
-- Cash assets share one hill/week measurement, including receipt ownership.
-- Private ride deletion cannot erase an already admitted sporting fact.
CREATE TABLE public.stage1_keeper_measurements (
    program TEXT NOT NULL,
    hill TEXT NOT NULL,
    week BIGINT NOT NULL CHECK (week >= 0),
    inputs JSONB NOT NULL,
    PRIMARY KEY(program,hill,week)
);
CREATE TABLE public.stage1_keeper_jobs (
    id TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL REFERENCES public.stage1_keeper_scopes(id),
    week BIGINT NOT NULL CHECK (week >= 0),
    through_week BIGINT NOT NULL CHECK (through_week >= week),
    state TEXT NOT NULL CHECK (state IN ('planning','running','complete','blocked')),
    snapshot JSONB,
    sources JSONB,
    allocation JSONB,
    claims JSONB,
    operations JSONB,
    operation_index INTEGER NOT NULL DEFAULT 0 CHECK (operation_index >= 0),
    signed JSONB,
    lookup_address TEXT,
    floor_slot BIGINT NOT NULL DEFAULT 0 CHECK (floor_slot >= 0),
    export_path TEXT,
    export_digest TEXT,
    export_suspended BOOLEAN NOT NULL DEFAULT FALSE,
    erasure_request_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    publications JSONB NOT NULL DEFAULT '{}'::jsonb,
    dung_publication JSONB,
    funding_publication JSONB,
    payout_retry_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    payout_done BOOLEAN NOT NULL DEFAULT false,
    UNIQUE(scope_id,week)
);
CREATE TABLE public.stage1_keeper_proofs (
    job_id TEXT NOT NULL REFERENCES public.stage1_keeper_jobs(id),
    role SMALLINT NOT NULL DEFAULT -1 CHECK (role IN (-1,0,1)),
    leaf_index INTEGER NOT NULL CHECK (leaf_index BETWEEN 0 AND 65535),
    person TEXT NOT NULL,
    leaf JSONB NOT NULL,
    paid_slot BIGINT CHECK (paid_slot > 0),
    PRIMARY KEY(job_id,role,leaf_index),
    UNIQUE(job_id,role,person)
);
-- Every signature/byte sequence survives retries and restarts, including an
-- expired attempt. This is an audit trail, not a second source of pay truth.
CREATE TABLE public.stage1_keeper_attempts (
    job_id TEXT NOT NULL REFERENCES public.stage1_keeper_jobs(id),
    signature TEXT NOT NULL,
    operation_index INTEGER NOT NULL,
    signed JSONB NOT NULL,
    finalized_slot BIGINT,
    fee_lamports BIGINT CHECK (fee_lamports >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(job_id,signature)
);
CREATE TABLE public.stage1_keeper_reconciliations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES public.stage1_keeper_jobs(id),
    evidence JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE public.stage1_keeper_alerts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scope_id TEXT NOT NULL REFERENCES public.stage1_keeper_scopes(id),
    job_id TEXT REFERENCES public.stage1_keeper_jobs(id),
    kind TEXT NOT NULL,
    details JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Payout work stores proof references, never another copy of rider identity.
-- Signed bytes precede network IO. Only invalid destinations are terminal;
-- a rider can still self-claim those leaves. Other failures wait and retry.
CREATE TABLE public.stage1_keeper_payout_actions (
    id TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL REFERENCES public.stage1_keeper_scopes(id),
    job_id TEXT NOT NULL REFERENCES public.stage1_keeper_jobs(id),
    operation JSONB NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('ready','complete','failed')),
    signed JSONB,
    attempts JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence JSONB,
    retry_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    retries INTEGER NOT NULL DEFAULT 0 CHECK (retries >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX stage1_keeper_payout_due ON public.stage1_keeper_jobs(payout_retry_at) WHERE NOT payout_done;
ALTER TABLE public.stage1_keeper_payout_actions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.stage1_keeper_payout_actions FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.stage1_keeper_payout_actions TO service_role;
-- Permanent one-way account fingerprints prevent repeated rent sponsorship.
-- No wallet, recipient, ATA preimage or ride link is retained here.
CREATE TABLE public.stage1_keeper_token_accounts (
    fingerprint TEXT PRIMARY KEY CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    observed_slot BIGINT NOT NULL CHECK (observed_slot > 0),
    established BOOLEAN NOT NULL DEFAULT true,
    attempt_signature TEXT,
    creation_excluded BOOLEAN NOT NULL DEFAULT false,
    creation_signature TEXT,
    sponsored_lamports BIGINT NOT NULL DEFAULT 0 CHECK (sponsored_lamports >= 0)
);
ALTER TABLE public.stage1_keeper_token_accounts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.stage1_keeper_token_accounts FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT,INSERT,UPDATE ON public.stage1_keeper_token_accounts TO service_role;
-- Reserve each authority/recent-slot address once across all scopes. Addresses
-- and owner keys are public/one-way; erasure cannot orphan the rent obligation.
CREATE TABLE public.stage1_keeper_lookup_tables (
    address TEXT PRIMARY KEY,
    owner_key TEXT NOT NULL,
    scope_id TEXT NOT NULL REFERENCES public.stage1_keeper_scopes(id),
    job_id TEXT NOT NULL REFERENCES public.stage1_keeper_jobs(id),
    closed BOOLEAN NOT NULL DEFAULT false,
    deposited_lamports BIGINT CHECK (deposited_lamports >= 0)
);
ALTER TABLE public.stage1_keeper_lookup_tables ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.stage1_keeper_lookup_tables FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.stage1_keeper_lookup_tables TO service_role;
-- A private transaction capability allows erasure only inside the existing
-- finalizer, after its lease/storage/value checks. GUC spoofing is insufficient.
CREATE TABLE public.stage1_keeper_erasure_sessions (
    transaction_id BIGINT PRIMARY KEY,
    request_id UUID NOT NULL,
    lease_token UUID NOT NULL
);
CREATE TABLE public.stage1_keeper_erasure_exports (
    request_id UUID NOT NULL,
    job_id TEXT NOT NULL REFERENCES public.stage1_keeper_jobs(id),
    path TEXT NOT NULL,
    digest TEXT NOT NULL,
    payload JSONB,
    redacted_digest TEXT CHECK (redacted_digest ~ '^[0-9a-f]{64}$'),
    removed_at TIMESTAMPTZ,
    PRIMARY KEY(request_id,job_id)
);
CREATE FUNCTION public.stage1_keeper_erasing() RETURNS boolean
LANGUAGE sql SECURITY DEFINER SET search_path='' AS $$
 SELECT EXISTS(SELECT 1 FROM public.stage1_keeper_erasure_sessions s
 JOIN public.deletion_requests r ON r.id=s.request_id
 WHERE s.transaction_id=pg_catalog.txid_current()
 AND r.status='processing' AND r.worker_lease_token=s.lease_token
 AND r.worker_lease_until>pg_catalog.clock_timestamp()
 AND r.storage_authorized_at IS NOT NULL AND r.storage_completed_at IS NOT NULL
 AND s.request_id::text=pg_catalog.current_setting('app.account_deletion_request_id',true))
$$;
CREATE FUNCTION public.stage1_keeper_immutable_boundary() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF TG_OP='UPDATE' AND public.stage1_keeper_erasing() THEN RETURN NEW; END IF;
 RAISE EXCEPTION 'Stage 1 frozen boundary evidence is immutable';
END $$;
CREATE TRIGGER stage1_keeper_boundary_immutable BEFORE UPDATE OR DELETE
ON public.stage1_keeper_boundaries FOR EACH ROW EXECUTE FUNCTION public.stage1_keeper_immutable_boundary();
CREATE TRIGGER stage1_keeper_measurement_immutable BEFORE UPDATE OR DELETE
ON public.stage1_keeper_measurements FOR EACH ROW EXECUTE FUNCTION public.stage1_keeper_immutable_boundary();

ALTER TABLE public.stage1_keeper_scopes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stage1_keeper_boundaries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stage1_keeper_measurements ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stage1_keeper_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stage1_keeper_proofs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stage1_keeper_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stage1_keeper_reconciliations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stage1_keeper_alerts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.stage1_keeper_scopes, public.stage1_keeper_boundaries, public.stage1_keeper_measurements,
 public.stage1_keeper_jobs, public.stage1_keeper_proofs, public.stage1_keeper_attempts,
 public.stage1_keeper_reconciliations, public.stage1_keeper_alerts FROM PUBLIC,anon,authenticated;
GRANT SELECT,INSERT,UPDATE ON public.stage1_keeper_scopes, public.stage1_keeper_jobs,
 public.stage1_keeper_attempts TO service_role;
GRANT SELECT,INSERT ON public.stage1_keeper_boundaries, public.stage1_keeper_measurements, public.stage1_keeper_proofs,
 public.stage1_keeper_reconciliations, public.stage1_keeper_alerts TO service_role;
GRANT USAGE ON SEQUENCE public.stage1_keeper_reconciliations_id_seq, public.stage1_keeper_alerts_id_seq TO service_role;

-- Enumerate keys as well as values: person identities also key allocation maps.
CREATE FUNCTION public.stage1_keeper_strings(v jsonb) RETURNS SETOF text
LANGUAGE plpgsql IMMUTABLE SET search_path='' AS $$
DECLARE r record; item jsonb;
BEGIN
 IF pg_catalog.jsonb_typeof(v)='object' THEN
  FOR r IN SELECT * FROM pg_catalog.jsonb_each(v) LOOP
   RETURN NEXT r.key; RETURN QUERY SELECT * FROM public.stage1_keeper_strings(r.value);
  END LOOP;
 ELSIF pg_catalog.jsonb_typeof(v)='array' THEN
  FOR item IN SELECT * FROM pg_catalog.jsonb_array_elements(v) LOOP
   RETURN QUERY SELECT * FROM public.stage1_keeper_strings(item);
  END LOOP;
 ELSIF pg_catalog.jsonb_typeof(v)='string' THEN RETURN NEXT v #>> '{}';
 END IF;
END $$;
CREATE FUNCTION public.stage1_keeper_personal_write_fence() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE wallet text;
BEGIN
 IF public.stage1_keeper_erasing() THEN RETURN NEW; END IF;
 FOR wallet IN SELECT DISTINCT matched[1] FROM public.stage1_keeper_strings(pg_catalog.to_jsonb(NEW)) s
   CROSS JOIN LATERAL pg_catalog.regexp_matches(s,'(?<![1-9A-HJ-NP-Za-km-z])([1-9A-HJ-NP-Za-km-z]{32,44})(?![1-9A-HJ-NP-Za-km-z])','g') matched ORDER BY 1 LOOP
  PERFORM public.br_account_deletion_assert_wallet_write_allowed(wallet);
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER stage1_keeper_boundary_fence BEFORE INSERT OR UPDATE ON public.stage1_keeper_boundaries
 FOR EACH ROW EXECUTE FUNCTION public.stage1_keeper_personal_write_fence();
CREATE TRIGGER stage1_keeper_measurement_fence BEFORE INSERT OR UPDATE ON public.stage1_keeper_measurements
 FOR EACH ROW EXECUTE FUNCTION public.stage1_keeper_personal_write_fence();
CREATE TRIGGER stage1_keeper_job_fence BEFORE INSERT OR UPDATE OF snapshot,sources,allocation,claims ON public.stage1_keeper_jobs
 FOR EACH ROW EXECUTE FUNCTION public.stage1_keeper_personal_write_fence();
CREATE TRIGGER stage1_keeper_proof_fence BEFORE INSERT OR UPDATE OF person,leaf ON public.stage1_keeper_proofs
 FOR EACH ROW EXECUTE FUNCTION public.stage1_keeper_personal_write_fence();
-- Frozen financial obligations must finish while deletion is pending. Once
-- finalized erasure creates the tombstone, stale chain metadata cannot restore
-- its identity. Opaque signed bytes additionally require the worker's state CAS.
CREATE FUNCTION public.stage1_keeper_settlement_write_fence() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE candidate_wallet text; fingerprint text;
BEGIN
 IF public.stage1_keeper_erasing() THEN RETURN NEW; END IF;
 FOR candidate_wallet IN SELECT DISTINCT matched[1] FROM public.stage1_keeper_strings(pg_catalog.to_jsonb(NEW)) s
 CROSS JOIN LATERAL pg_catalog.regexp_matches(s,'(?<![1-9A-HJ-NP-Za-km-z])([1-9A-HJ-NP-Za-km-z]{32,44})(?![1-9A-HJ-NP-Za-km-z])','g') matched ORDER BY 1 LOOP
  fingerprint := public.br_account_deletion_wallet_fingerprint(candidate_wallet);
  PERFORM public.br_lock_account_deletion_wallet(fingerprint);
  IF EXISTS(SELECT 1 FROM public.deleted_account_tombstones WHERE wallet_fingerprint=fingerprint)
  OR EXISTS(SELECT 1 FROM public.deleted_wallets d WHERE d.wallet=candidate_wallet)
  THEN RAISE EXCEPTION 'account_deleted' USING ERRCODE='55000'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER stage1_keeper_witness_fence BEFORE INSERT OR UPDATE OF publications,funding_publication,dung_publication,signed ON public.stage1_keeper_jobs
 FOR EACH ROW EXECUTE FUNCTION public.stage1_keeper_settlement_write_fence();
CREATE TRIGGER stage1_keeper_attempt_fence BEFORE INSERT OR UPDATE OF signed ON public.stage1_keeper_attempts
 FOR EACH ROW EXECUTE FUNCTION public.stage1_keeper_settlement_write_fence();
CREATE TRIGGER stage1_keeper_reconciliation_fence BEFORE INSERT OR UPDATE ON public.stage1_keeper_reconciliations
 FOR EACH ROW EXECUTE FUNCTION public.stage1_keeper_settlement_write_fence();
CREATE TRIGGER stage1_keeper_payout_fence BEFORE INSERT OR UPDATE OF operation,signed,attempts,evidence ON public.stage1_keeper_payout_actions
 FOR EACH ROW EXECUTE FUNCTION public.stage1_keeper_settlement_write_fence();
CREATE FUNCTION public.stage1_keeper_alert_privacy() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE wallet text;
BEGIN
 IF public.stage1_keeper_erasing() THEN RETURN NEW; END IF;
 FOR wallet IN SELECT DISTINCT matched[1] FROM public.stage1_keeper_strings(NEW.details) s
 CROSS JOIN LATERAL pg_catalog.regexp_matches(s,'(?<![1-9A-HJ-NP-Za-km-z])([1-9A-HJ-NP-Za-km-z]{32,44})(?![1-9A-HJ-NP-Za-km-z])','g') matched ORDER BY 1 LOOP
  BEGIN
   PERFORM public.br_account_deletion_assert_wallet_write_allowed(wallet);
  EXCEPTION WHEN object_not_in_prerequisite_state THEN
   -- Keep the operational alert even if an old chain response contains an
   -- erased identity. No private preimages or times from that detail survive.
   NEW.details := pg_catalog.jsonb_build_object('withheld_private_details_sha256',
    pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(NEW.details::text,'UTF8')),'hex'));
   RETURN NEW;
  END;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER stage1_keeper_alert_fence BEFORE INSERT OR UPDATE ON public.stage1_keeper_alerts
 FOR EACH ROW EXECUTE FUNCTION public.stage1_keeper_alert_privacy();

CREATE FUNCTION public.stage1_keeper_redact(v jsonb, wallet text, marker text, owned boolean DEFAULT false) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path='' AS $$
DECLARE result jsonb; r record; item jsonb; personal boolean; k text;
BEGIN
 IF pg_catalog.jsonb_typeof(v)='object' THEN
  personal := owned OR v->>'person'=wallet OR v->>'wallet'=wallet OR v->>'owner'=wallet;
  result := '{}'::jsonb;
  FOR r IN SELECT * FROM pg_catalog.jsonb_each(v) LOOP
   IF v->>'owner'=wallet AND r.key=ANY(ARRAY['address','deposit_id','exit_request','pending_request','deposited_at']) THEN CONTINUE; END IF;
   IF personal AND r.key=ANY(ARRAY['ridden_at','ridden_at_us','uploaded_at','uploaded_at_us',
     'verified_at','verified_at_us','recorded_at','term_start','term_end','registered_at','ride_day_key']) THEN CONTINUE; END IF;
   k := CASE WHEN r.key=wallet THEN marker ELSE r.key END;
   result := result || pg_catalog.jsonb_build_object(k,
    public.stage1_keeper_redact(r.value,wallet,marker,r.key=wallet));
  END LOOP;
  RETURN result;
 ELSIF pg_catalog.jsonb_typeof(v)='array' THEN
  SELECT coalesce(pg_catalog.jsonb_agg(public.stage1_keeper_redact(x,wallet,marker,owned)), '[]'::jsonb)
   INTO result FROM pg_catalog.jsonb_array_elements(v) x;
  RETURN result;
 ELSIF pg_catalog.jsonb_typeof(v)='string' THEN
  RETURN pg_catalog.to_jsonb(pg_catalog.replace(v #>> '{}',wallet,marker));
 END IF;
 RETURN v;
END $$;

CREATE FUNCTION public.stage1_keeper_export_redact(v jsonb, wallet text) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE SET search_path='' AS $$
DECLARE r record; result jsonb; erased boolean;
BEGIN
 IF pg_catalog.jsonb_typeof(v)='object' THEN
  erased := v->>'person'=wallet OR v->>'recipient'=wallet OR v->>'person' LIKE 'anonymous:%' OR v->>'recipient' LIKE 'anonymous:%';
  result := CASE WHEN erased THEN '{"identity_erased":true}'::jsonb ELSE '{}'::jsonb END;
  FOR r IN SELECT * FROM pg_catalog.jsonb_each(v) LOOP
   IF erased AND r.key IN ('person','recipient') THEN CONTINUE; END IF;
   result := result || pg_catalog.jsonb_build_object(r.key,public.stage1_keeper_export_redact(r.value,wallet));
  END LOOP;
  RETURN result;
 ELSIF pg_catalog.jsonb_typeof(v)='array' THEN
  SELECT coalesce(pg_catalog.jsonb_agg(public.stage1_keeper_export_redact(x,wallet)),'[]'::jsonb) INTO result
  FROM pg_catalog.jsonb_array_elements(v) x;
  RETURN result;
 END IF;
 RETURN v;
END $$;
REVOKE ALL ON FUNCTION public.stage1_keeper_export_redact(jsonb,text) FROM PUBLIC,anon,authenticated,service_role;

CREATE FUNCTION public.stage1_keeper_personal_jobs(wallet text) RETURNS SETOF text
LANGUAGE sql STABLE SET search_path='' AS $$
 SELECT id FROM public.stage1_keeper_jobs j WHERE pg_catalog.strpos(pg_catalog.to_jsonb(j)::text,wallet)>0
 UNION SELECT job_id FROM public.stage1_keeper_proofs p WHERE pg_catalog.strpos(pg_catalog.to_jsonb(p)::text,wallet)>0
 UNION SELECT job_id FROM public.stage1_keeper_attempts a WHERE pg_catalog.strpos(pg_catalog.to_jsonb(a)::text,wallet)>0
 UNION SELECT job_id FROM public.stage1_keeper_reconciliations r WHERE pg_catalog.strpos(r.evidence::text,wallet)>0
 UNION SELECT job_id FROM public.stage1_keeper_payout_actions a WHERE pg_catalog.strpos(pg_catalog.to_jsonb(a)::text,wallet)>0
$$;
-- Settled history is erasable. Only unpaid leaves, latest attributed holds,
-- unresolved rent refunds and an in-flight publication remain obligations.
CREATE FUNCTION public.stage1_keeper_has_personal_data(wallet text) RETURNS boolean
LANGUAGE sql STABLE SET search_path='' AS $$
 SELECT coalesce(wallet,'')<>'' AND (
 EXISTS(SELECT 1 FROM public.stage1_keeper_boundaries WHERE pg_catalog.strpos(inputs::text,wallet)>0)
 OR EXISTS(SELECT 1 FROM public.stage1_keeper_measurements WHERE pg_catalog.strpos(inputs::text,wallet)>0)
 OR EXISTS(SELECT 1 FROM public.stage1_keeper_personal_jobs(wallet))
 OR EXISTS(SELECT 1 FROM public.stage1_keeper_alerts WHERE pg_catalog.strpos(details::text,wallet)>0)
 OR EXISTS(SELECT 1 FROM public.stage1_keeper_erasure_exports WHERE pg_catalog.strpos(payload::text,wallet)>0))
$$;
ALTER FUNCTION public.br_account_deletion_db_blockers(uuid,text) RENAME TO br_account_deletion_db_blockers_pre_keeper;
CREATE FUNCTION public.br_account_deletion_db_blockers(p_user_id uuid,p_wallet text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE result jsonb; n bigint;
BEGIN
 result := public.br_account_deletion_db_blockers_pre_keeper(p_user_id,p_wallet);
 SELECT count(*) INTO n FROM public.stage1_keeper_proofs
 WHERE (person=p_wallet OR leaf->>'recipient'=p_wallet) AND paid_slot IS NULL;
 SELECT n+count(*) INTO n FROM (
  SELECT DISTINCT ON(scope_id) allocation FROM public.stage1_keeper_jobs WHERE state='complete' ORDER BY scope_id,week DESC
 ) latest CROSS JOIN LATERAL pg_catalog.jsonb_each(coalesce(latest.allocation->'reserved','{}')) source
 WHERE coalesce((source.value->>p_wallet)::numeric,0)>0;
 SELECT n+count(*) INTO n FROM public.stage1_keeper_jobs j
 WHERE state <> 'complete' AND id IN (SELECT public.stage1_keeper_personal_jobs(p_wallet));
 SELECT n+count(*) INTO n FROM public.stage1_keeper_jobs j CROSS JOIN LATERAL (
  SELECT value AS record FROM pg_catalog.jsonb_each(j.publications)
  UNION ALL SELECT j.funding_publication UNION ALL SELECT j.dung_publication
 ) retained WHERE retained.record->'account'->>'rent_payer'=p_wallet
 AND coalesce(retained.record->'closed','null'::jsonb)='null'::jsonb;
 IF n>0 THEN result := result || pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
  'code','claim_remains','category','claim','count',n,'source','stage1_keeper','action','contact_support')); END IF;
 SELECT count(*) INTO n FROM public.stage1_keeper_jobs j
 WHERE erasure_request_id IS NOT NULL AND erasure_request_id IS DISTINCT FROM
 (SELECT account_deletion_request_id FROM public.users WHERE id=p_user_id)
 AND id IN (SELECT public.stage1_keeper_personal_jobs(p_wallet));
 IF n>0 THEN result := result || pg_catalog.jsonb_build_array(pg_catalog.jsonb_build_object(
  'code','policy_review_required','category','policy','count',n,'source','stage1_keeper','action','contact_support')); END IF;
 RETURN result;
END $$;

CREATE FUNCTION public.stage1_keeper_prepare_erasure(p_request_id uuid,p_lease_token uuid)
RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE r public.deletion_requests; asset record; v_blockers jsonb; exports jsonb;
BEGIN
 SELECT * INTO r FROM public.deletion_requests WHERE id=p_request_id FOR UPDATE;
 -- Persisted data, not the worker flag, decides whether erasure is needed.
 -- Otherwise the unchanged legacy finalizer owns every outcome and check.
 IF NOT public.stage1_keeper_has_personal_data(r.wallet)
 THEN RETURN '{"exports":[],"request":null}'::jsonb; END IF;
 IF r.status IS DISTINCT FROM 'processing' OR r.worker_lease_token IS DISTINCT FROM p_lease_token
 OR p_lease_token IS NULL OR r.worker_lease_until IS NULL
 OR r.worker_lease_until<=pg_catalog.clock_timestamp() OR r.storage_completed_at IS NULL
 OR r.storage_authorized_at IS NULL THEN RAISE EXCEPTION 'keeper_erasure_lease_required'; END IF;
 -- Same locks as publication; a suspended bit spans the subsequent filesystem IO.
 FOR asset IN SELECT DISTINCT s.program,s.mint FROM public.stage1_keeper_scopes s
 JOIN public.stage1_keeper_jobs j ON j.scope_id=s.id
 WHERE j.id IN (SELECT public.stage1_keeper_personal_jobs(r.wallet)) ORDER BY s.program,s.mint LOOP
  PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('stage1:'||asset.program||':'||asset.mint,0));
 END LOOP;
 v_blockers := public.br_account_deletion_db_blockers(r.user_id,r.wallet);
 IF pg_catalog.jsonb_array_length(v_blockers)>0 THEN
  -- Match the existing post-storage finalizer outcome atomically. Returning
  -- this durable row avoids a second RPC race if the blocker disappears.
  UPDATE public.deletion_requests SET status='needs_support',blockers=v_blockers,
   failure_code='blocker_after_storage_authorization',worker_id=NULL,
   worker_lease_token=NULL,worker_lease_until=NULL,updated_at=pg_catalog.clock_timestamp()
   WHERE id=r.id RETURNING * INTO r;
  RETURN pg_catalog.jsonb_build_object('exports','[]'::jsonb,'request',pg_catalog.to_jsonb(r));
 END IF;
 UPDATE public.stage1_keeper_jobs j SET export_suspended=true,erasure_request_id=r.id
 WHERE j.id IN (SELECT public.stage1_keeper_personal_jobs(r.wallet));
 INSERT INTO public.stage1_keeper_erasure_exports(request_id,job_id,path,digest,payload)
 SELECT r.id,id,export_path,export_digest,pg_catalog.jsonb_build_object(
 'schema',1,'cap',allocation->'cap','snapshot_commitment',snapshot->'commitment','claim_instruction',CASE WHEN claims->>'kind'='dung' THEN 'claim_stage1_dung_batch' ELSE 'claim_stage1' END,
 'cash_skipped',NOT EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(operations) op WHERE op->>'kind'='publish'),
 'claims',public.stage1_keeper_export_redact(claims,r.wallet)) FROM public.stage1_keeper_jobs j
 WHERE export_suspended AND export_path IS NOT NULL AND j.id IN (SELECT public.stage1_keeper_personal_jobs(r.wallet))
 ON CONFLICT(request_id,job_id) DO UPDATE SET path=EXCLUDED.path,digest=EXCLUDED.digest,payload=EXCLUDED.payload;
 SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(e) ORDER BY job_id),'[]'::jsonb)
 INTO exports FROM public.stage1_keeper_erasure_exports e WHERE request_id=r.id;
 RETURN pg_catalog.jsonb_build_object('exports',exports,'request',NULL);
END $$;
CREATE FUNCTION public.stage1_keeper_validate_erasure(p_request_id uuid,p_lease_token uuid,p_job_id text,p_digest text,p_payload jsonb)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.deletion_requests d
 JOIN public.stage1_keeper_erasure_exports e ON e.request_id=d.id
 JOIN public.stage1_keeper_jobs j ON j.id=e.job_id
 WHERE d.id=p_request_id AND d.status='processing' AND d.worker_lease_token=p_lease_token
 AND d.worker_lease_until>pg_catalog.clock_timestamp() AND d.storage_completed_at IS NOT NULL
 AND d.storage_authorized_at IS NOT NULL AND j.export_suspended AND j.erasure_request_id=d.id
 AND e.job_id=p_job_id AND e.digest=p_digest AND e.payload=p_payload
 AND e.path=j.export_path AND e.digest=j.export_digest)
 THEN RAISE EXCEPTION 'keeper_erasure_lease_or_manifest_changed'; END IF;
 RETURN true;
END $$;
CREATE FUNCTION public.stage1_keeper_record_erasure(p_request_id uuid,p_lease_token uuid,p_job_id text,p_digest text,p_redacted_digest text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.deletion_requests WHERE id=p_request_id AND status='processing'
 AND worker_lease_token=p_lease_token AND worker_lease_until>pg_catalog.clock_timestamp()
 AND storage_completed_at IS NOT NULL) THEN RAISE EXCEPTION 'keeper_erasure_lease_required'; END IF;
 UPDATE public.stage1_keeper_erasure_exports SET removed_at=pg_catalog.clock_timestamp(),redacted_digest=p_redacted_digest
 WHERE request_id=p_request_id AND job_id=p_job_id AND digest=p_digest;
 IF NOT FOUND THEN RAISE EXCEPTION 'keeper_erasure_manifest_mismatch'; END IF;
 RETURN true;
END $$;

CREATE FUNCTION public.stage1_keeper_anonymize() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE r public.deletion_requests; wallet text; marker text;
BEGIN
 IF NEW.account_state <> 'anonymized' THEN RETURN NEW; END IF;
 SELECT d.* INTO r FROM public.deletion_requests d
 WHERE d.id::text=pg_catalog.current_setting('app.account_deletion_request_id',true);
 IF NOT FOUND THEN RAISE EXCEPTION 'keeper_erasure_finalizer_required'; END IF;
 IF NOT public.stage1_keeper_has_personal_data(r.wallet) THEN RETURN NEW; END IF;
 IF NOT public.stage1_keeper_erasing() THEN RAISE EXCEPTION 'keeper_erasure_finalizer_required'; END IF;
 SELECT d.* INTO r FROM public.deletion_requests d JOIN public.stage1_keeper_erasure_sessions s ON s.request_id=d.id
 WHERE s.transaction_id=pg_catalog.txid_current();
 wallet := r.wallet; marker := NEW.wallet;
 IF NEW.id IS DISTINCT FROM NEW.anonymous_marker OR marker IS DISTINCT FROM 'anonymous:'||NEW.id::text
 OR NOT EXISTS(SELECT 1 FROM public.users WHERE id=r.user_id AND account_state='deletion_pending'
 AND account_deletion_request_id=r.id AND users.wallet=r.wallet) THEN RAISE EXCEPTION 'keeper_erasure_identity_fence'; END IF;
 IF EXISTS(SELECT 1 FROM public.stage1_keeper_jobs j WHERE export_path IS NOT NULL
 AND j.id IN (SELECT public.stage1_keeper_personal_jobs(wallet))
 AND (NOT export_suspended OR NOT EXISTS(SELECT 1 FROM public.stage1_keeper_erasure_exports e
 WHERE e.request_id=r.id AND e.job_id=j.id AND e.path=j.export_path AND e.digest=j.export_digest AND e.redacted_digest IS NOT NULL AND e.removed_at IS NOT NULL)))
 THEN RAISE EXCEPTION 'keeper_erasure_exports_not_removed'; END IF;
 -- A paid transaction contains recoverable person/recipient bytes. Retain
 -- public signature/fee/slot and commitments, never those private preimages.
 UPDATE public.stage1_keeper_payout_actions a SET signed=public.stage1_keeper_redact(signed-'bytes',wallet,marker),
 attempts=(SELECT coalesce(pg_catalog.jsonb_agg(public.stage1_keeper_redact(item-'bytes',wallet,marker)),'[]'::jsonb) FROM pg_catalog.jsonb_array_elements(a.attempts) item),
 operation=public.stage1_keeper_redact(operation-'addresses'-'lookup_addresses',wallet,marker),
 evidence=public.stage1_keeper_redact(evidence,wallet,marker),
 state=CASE WHEN a.state='ready' THEN 'complete' ELSE a.state END
 WHERE pg_catalog.strpos(pg_catalog.to_jsonb(a)::text,wallet)>0
 OR EXISTS(SELECT 1 FROM pg_catalog.jsonb_array_elements(coalesce(a.operation->'refs','[]'::jsonb)) ref
 JOIN public.stage1_keeper_proofs p ON p.job_id=ref->>'job_id' AND p.role=(ref->>'role')::smallint
 AND p.leaf_index=(ref->>'index')::integer WHERE p.person=wallet OR p.leaf->>'recipient'=wallet);
 UPDATE public.stage1_keeper_attempts a SET signed=public.stage1_keeper_redact(signed-'bytes',wallet,marker)
 WHERE a.job_id IN (SELECT public.stage1_keeper_personal_jobs(wallet))
 OR EXISTS(SELECT 1 FROM public.stage1_keeper_jobs j WHERE j.id=a.job_id AND j.erasure_request_id=r.id);
 UPDATE public.stage1_keeper_reconciliations SET evidence=public.stage1_keeper_redact(evidence,wallet,marker)
 WHERE pg_catalog.strpos(evidence::text,wallet)>0;
 UPDATE public.stage1_keeper_boundaries SET inputs=public.stage1_keeper_redact(inputs,wallet,marker)
 WHERE pg_catalog.strpos(inputs::text,wallet)>0;
 UPDATE public.stage1_keeper_measurements SET inputs=public.stage1_keeper_redact(inputs,wallet,marker)
 WHERE pg_catalog.strpos(inputs::text,wallet)>0;
 UPDATE public.stage1_keeper_jobs j SET snapshot=public.stage1_keeper_redact(snapshot,wallet,marker),
 sources=public.stage1_keeper_redact(sources,wallet,marker),allocation=public.stage1_keeper_redact(allocation,wallet,marker),
 claims=public.stage1_keeper_redact(claims,wallet,marker),
 operations=public.stage1_keeper_redact(operations,wallet,marker),
 signed=public.stage1_keeper_redact(signed-'bytes',wallet,marker),
 publications=public.stage1_keeper_redact(publications,wallet,marker),
 funding_publication=public.stage1_keeper_redact(funding_publication,wallet,marker),
 dung_publication=public.stage1_keeper_redact(dung_publication,wallet,marker),
 export_digest=coalesce((SELECT e.redacted_digest FROM public.stage1_keeper_erasure_exports e WHERE e.request_id=r.id AND e.job_id=j.id),j.export_digest),
 export_suspended=false,erasure_request_id=NULL
 WHERE j.erasure_request_id=r.id OR j.id IN (SELECT public.stage1_keeper_personal_jobs(wallet));
 UPDATE public.stage1_keeper_proofs SET person=CASE WHEN person=wallet THEN marker ELSE person END,
 leaf=public.stage1_keeper_redact(leaf,wallet,marker) WHERE person=wallet OR pg_catalog.strpos(leaf::text,wallet)>0;
 UPDATE public.stage1_keeper_alerts SET details=public.stage1_keeper_redact(details,wallet,marker)
 WHERE pg_catalog.strpos(details::text,wallet)>0;
 UPDATE public.stage1_keeper_erasure_exports SET payload=NULL WHERE request_id=r.id;
 RETURN NEW;
END $$;
CREATE TRIGGER stage1_keeper_anonymize AFTER INSERT ON public.users FOR EACH ROW EXECUTE FUNCTION public.stage1_keeper_anonymize();
ALTER FUNCTION public.finalize_account_anonymization(uuid,uuid,uuid) RENAME TO finalize_account_anonymization_pre_keeper;
CREATE FUNCTION public.finalize_account_anonymization(p_request_id uuid,p_user_id uuid,p_lease_token uuid)
RETURNS SETOF public.deletion_requests LANGUAGE plpgsql SECURITY DEFINER SET search_path='' AS $$
DECLARE asset record; keeper_wallet text;
BEGIN
 IF NOT public.stage1_keeper_has_personal_data((SELECT wallet FROM public.deletion_requests WHERE id=p_request_id)) THEN
  RETURN QUERY SELECT * FROM public.finalize_account_anonymization_pre_keeper(p_request_id,p_user_id,p_lease_token);
  RETURN;
 END IF;
 SELECT d.wallet INTO keeper_wallet FROM public.deletion_requests d WHERE d.id=p_request_id FOR UPDATE;
 -- Export IO ends before this RPC. Reacquire the same asset locks so a payout
 -- cannot restore a private signed payload after final identity erasure.
 FOR asset IN SELECT DISTINCT s.program,s.mint FROM public.stage1_keeper_scopes s
 JOIN public.stage1_keeper_jobs j ON j.scope_id=s.id
 WHERE j.id IN (SELECT public.stage1_keeper_personal_jobs(keeper_wallet)) ORDER BY s.program,s.mint LOOP
  PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('stage1:'||asset.program||':'||asset.mint,0));
 END LOOP;
 INSERT INTO public.stage1_keeper_erasure_sessions VALUES(pg_catalog.txid_current(),p_request_id,p_lease_token);
 RETURN QUERY SELECT * FROM public.finalize_account_anonymization_pre_keeper(p_request_id,p_user_id,p_lease_token);
 DELETE FROM public.stage1_keeper_erasure_sessions WHERE transaction_id=pg_catalog.txid_current();
END $$;
ALTER TABLE public.stage1_keeper_erasure_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stage1_keeper_erasure_exports ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.stage1_keeper_erasure_sessions,public.stage1_keeper_erasure_exports FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.stage1_keeper_erasing(),public.stage1_keeper_strings(jsonb),public.stage1_keeper_has_personal_data(text),
 public.stage1_keeper_personal_jobs(text),public.stage1_keeper_settlement_write_fence(),
 public.stage1_keeper_redact(jsonb,text,text,boolean),public.stage1_keeper_anonymize(),
 public.stage1_keeper_personal_write_fence(),public.stage1_keeper_alert_privacy(),public.stage1_keeper_immutable_boundary(),
 public.br_account_deletion_db_blockers_pre_keeper(uuid,text),public.finalize_account_anonymization_pre_keeper(uuid,uuid,uuid),
 public.stage1_keeper_prepare_erasure(uuid,uuid),public.stage1_keeper_validate_erasure(uuid,uuid,text,text,jsonb),public.stage1_keeper_record_erasure(uuid,uuid,text,text,text),
 public.br_account_deletion_db_blockers(uuid,text),public.finalize_account_anonymization(uuid,uuid,uuid) FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION public.stage1_keeper_prepare_erasure(uuid,uuid),public.stage1_keeper_validate_erasure(uuid,uuid,text,text,jsonb),public.stage1_keeper_record_erasure(uuid,uuid,text,text,text),
 public.br_account_deletion_db_blockers(uuid,text),public.finalize_account_anonymization(uuid,uuid,uuid) TO service_role;
GRANT UPDATE ON public.stage1_keeper_proofs TO service_role;
GRANT DELETE ON public.stage1_keeper_proofs TO service_role;
COMMIT;
