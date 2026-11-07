-- Derived Threshold authority: immutable ride evidence, a bounded lifetime
-- power-duration envelope, and exactly one append-only Monday version.

ALTER TABLE public.reward_ftp_authorities
    DROP CONSTRAINT IF EXISTS reward_ftp_authorities_source_check;
ALTER TABLE public.reward_ftp_authorities
    ADD CONSTRAINT reward_ftp_authorities_source_check CHECK (
        source IN (
            'operator_verified', 'trusted_provider', 'verified_power_test',
            'derived_eftp'
        )
    );

ALTER TABLE public.rides
    ADD COLUMN IF NOT EXISTS upload_verified_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS threshold_recording_source TEXT,
    ADD COLUMN IF NOT EXISTS threshold_power_source_id UUID,
    ADD COLUMN IF NOT EXISTS threshold_source_identity_complete BOOLEAN,
    ADD COLUMN IF NOT EXISTS threshold_source_evidence JSONB;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conrelid = 'public.rides'::pg_catalog.regclass
          AND conname = 'rides_threshold_recording_source_check'
    ) THEN
        ALTER TABLE public.rides
            ADD CONSTRAINT rides_threshold_recording_source_check
            CHECK (
                threshold_recording_source IS NULL
                OR threshold_recording_source = 'br_ios'
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conrelid = 'public.rides'::pg_catalog.regclass
          AND conname = 'rides_threshold_source_evidence_object'
    ) THEN
        ALTER TABLE public.rides
            ADD CONSTRAINT rides_threshold_source_evidence_object
            CHECK (
                threshold_source_evidence IS NULL
                OR pg_catalog.jsonb_typeof(threshold_source_evidence) = 'object'
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conrelid = 'public.rides'::pg_catalog.regclass
          AND conname = 'rides_threshold_meter_requires_br_source'
    ) THEN
        ALTER TABLE public.rides
            ADD CONSTRAINT rides_threshold_meter_requires_br_source
            CHECK (
                threshold_power_source_id IS NULL
                OR (
                    threshold_recording_source = 'br_ios'
                    AND threshold_source_identity_complete IS TRUE
                )
            );
    END IF;
END;
$$;

COMMENT ON COLUMN public.rides.upload_verified_at IS
    'First server time at which the durable raw object and declared hash matched; immutable evidence-arrival clock.';
COMMENT ON COLUMN public.rides.threshold_power_source_id IS
    'Single durable paired-meter UUID recovered from the BR iOS GPX contract; NULL for absent, malformed, or mixed sources.';

CREATE OR REPLACE FUNCTION public.enforce_ride_threshold_evidence()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF OLD.upload_verified_at IS NOT NULL
           AND NEW.upload_verified_at IS DISTINCT FROM OLD.upload_verified_at THEN
            RAISE EXCEPTION 'ride upload verification time is immutable';
        END IF;
        IF OLD.threshold_source_evidence IS NOT NULL AND (
            NEW.threshold_recording_source IS DISTINCT FROM OLD.threshold_recording_source
            OR NEW.threshold_power_source_id IS DISTINCT FROM OLD.threshold_power_source_id
            OR NEW.threshold_source_identity_complete IS DISTINCT FROM OLD.threshold_source_identity_complete
            OR NEW.threshold_source_evidence IS DISTINCT FROM OLD.threshold_source_evidence
        ) THEN
            RAISE EXCEPTION 'ride Threshold source evidence is immutable';
        END IF;
    END IF;

    IF NEW.threshold_source_evidence IS NULL THEN
        IF NEW.threshold_recording_source IS NOT NULL
           OR NEW.threshold_power_source_id IS NOT NULL
           OR NEW.threshold_source_identity_complete IS NOT NULL THEN
            RAISE EXCEPTION 'partial ride Threshold source evidence is forbidden';
        END IF;
    ELSIF NEW.threshold_source_identity_complete IS NULL THEN
        RAISE EXCEPTION 'Threshold source evidence requires completeness state';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_rides_threshold_evidence ON public.rides;
CREATE TRIGGER trg_rides_threshold_evidence
    BEFORE INSERT OR UPDATE ON public.rides
    FOR EACH ROW EXECUTE FUNCTION public.enforce_ride_threshold_evidence();

CREATE TABLE public.reward_threshold_efforts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ride_id UUID UNIQUE,
    user_id UUID NOT NULL REFERENCES public.users(id),
    upload_verified_at TIMESTAMPTZ,
    evidence_received_at TIMESTAMPTZ NOT NULL,
    accepted_at TIMESTAMPTZ NOT NULL,
    file_hash CHAR(64) CHECK (file_hash IS NULL OR file_hash ~ '^[0-9a-f]{64}$'),
    recording_source TEXT,
    power_source_id UUID,
    provenance_tier TEXT,
    canonical_match BOOLEAN,
    structural_source_eligible BOOLEAN NOT NULL,
    source_decision TEXT NOT NULL CHECK (btrim(source_decision) <> ''),
    best_180s_w NUMERIC,
    best_420s_w NUMERIC,
    best_900s_w NUMERIC,
    model_version TEXT NOT NULL CHECK (model_version = 'threshold_cp_3_7_15_v1'),
    evidence JSONB NOT NULL CHECK (pg_catalog.jsonb_typeof(evidence) = 'object'),
    evidence_hash BYTEA NOT NULL CHECK (octet_length(evidence_hash) = 32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (best_180s_w IS NULL OR best_180s_w >= 0),
    CHECK (best_420s_w IS NULL OR best_420s_w >= 0),
    CHECK (best_900s_w IS NULL OR best_900s_w >= 0),
    CONSTRAINT reward_threshold_efforts_ride_id_fkey
        FOREIGN KEY (ride_id) REFERENCES public.rides(id) ON DELETE SET NULL,
    CHECK (
        NOT structural_source_eligible
        OR (
            recording_source = 'br_ios'
            AND file_hash IS NOT NULL
            AND power_source_id IS NOT NULL
            AND provenance_tier = 'first_party_recorded'
            AND canonical_match IS TRUE
        )
    )
);

CREATE TABLE public.reward_threshold_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    effort_id UUID NOT NULL UNIQUE REFERENCES public.reward_threshold_efforts(id),
    ride_id UUID UNIQUE,
    user_id UUID NOT NULL REFERENCES public.users(id),
    power_source_id UUID,
    display_best_180s_w NUMERIC,
    display_best_420s_w NUMERIC,
    display_best_900s_w NUMERIC,
    display_candidate_w NUMERIC,
    display_work_capacity_j NUMERIC,
    proposed_best_180s_w NUMERIC,
    proposed_best_420s_w NUMERIC,
    proposed_best_900s_w NUMERIC,
    fitted_candidate_w NUMERIC,
    fitted_work_capacity_j NUMERIC,
    economic_candidate_w NUMERIC,
    economic_work_capacity_j NUMERIC,
    baseline_authority_id UUID REFERENCES public.reward_ftp_authorities(id),
    baseline_ftp_w INTEGER,
    target_ftp_w INTEGER,
    disposition TEXT NOT NULL CHECK (disposition IN (
        'display_only', 'insufficient_history', 'invalid_fit_review',
        'below_bounds_review', 'above_bounds_review', 'below_deadband',
        'pending_establishment', 'pending_initialization', 'pending_raise',
        'superseded'
    )),
    target_effective_at TIMESTAMPTZ,
    superseded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT reward_threshold_candidates_ride_id_fkey
        FOREIGN KEY (ride_id) REFERENCES public.rides(id) ON DELETE SET NULL,
    CHECK (baseline_ftp_w IS NULL OR baseline_ftp_w BETWEEN 50 AND 500),
    CHECK (target_ftp_w IS NULL OR target_ftp_w BETWEEN 50 AND 500),
    CHECK (economic_candidate_w IS NULL OR economic_candidate_w BETWEEN 50 AND 500),
    CHECK (
        (disposition LIKE 'pending_%' AND target_ftp_w IS NOT NULL AND target_effective_at IS NOT NULL)
        OR (disposition NOT LIKE 'pending_%' AND target_ftp_w IS NULL AND target_effective_at IS NULL)
    ),
    CHECK ((disposition = 'superseded') = (superseded_at IS NOT NULL)),
    CHECK (economic_candidate_w IS NULL OR power_source_id IS NOT NULL)
);
COMMENT ON COLUMN public.reward_threshold_candidates.disposition IS
    'Registration disposition; current commitment lifecycle is reward_threshold_pending_promotions.status.';

CREATE TABLE public.reward_threshold_source_envelopes (
    user_id UUID NOT NULL REFERENCES public.users(id),
    power_source_id UUID NOT NULL,
    accepted_best_180s_w NUMERIC,
    accepted_best_420s_w NUMERIC,
    accepted_best_900s_w NUMERIC,
    accepted_candidate_w NUMERIC,
    accepted_work_capacity_j NUMERIC,
    last_accepted_candidate_id UUID REFERENCES public.reward_threshold_candidates(id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (user_id, power_source_id),
    CHECK (accepted_best_180s_w IS NULL OR accepted_best_180s_w >= 0),
    CHECK (accepted_best_420s_w IS NULL OR accepted_best_420s_w >= 0),
    CHECK (accepted_best_900s_w IS NULL OR accepted_best_900s_w >= 0),
    CHECK (accepted_candidate_w IS NULL OR accepted_candidate_w BETWEEN 50 AND 500)
);

CREATE TABLE public.reward_threshold_ratchets (
    user_id UUID PRIMARY KEY REFERENCES public.users(id),
    display_best_180s_w NUMERIC,
    display_best_420s_w NUMERIC,
    display_best_900s_w NUMERIC,
    display_candidate_w NUMERIC,
    economic_candidate_w NUMERIC,
    economic_work_capacity_j NUMERIC,
    economic_power_source_id UUID,
    sealed_authority_id UUID REFERENCES public.reward_ftp_authorities(id),
    sealed_ftp_w INTEGER CHECK (sealed_ftp_w IS NULL OR sealed_ftp_w BETWEEN 50 AND 500),
    established_at TIMESTAMPTZ,
    last_raised_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (economic_candidate_w IS NULL OR economic_candidate_w BETWEEN 50 AND 500)
);

CREATE TABLE public.reward_threshold_pending_promotions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(id),
    effective_at TIMESTAMPTZ NOT NULL,
    candidate_id UUID REFERENCES public.reward_threshold_candidates(id),
    baseline_authority_id UUID REFERENCES public.reward_ftp_authorities(id),
    promotion_kind TEXT NOT NULL CHECK (promotion_kind IN (
        'initialization', 'establishment', 'raise'
    )),
    target_candidate_w NUMERIC,
    target_ftp_w INTEGER NOT NULL CHECK (target_ftp_w BETWEEN 50 AND 500),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'sealed', 'repair_required', 'superseded'
    )),
    sealed_authority_id UUID REFERENCES public.reward_ftp_authorities(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    sealed_at TIMESTAMPTZ,
    failure_code TEXT,
    failure_message TEXT,
    failed_at TIMESTAMPTZ,
    resolution_reason TEXT,
    resolved_at TIMESTAMPTZ,
    UNIQUE (user_id, effective_at),
    CHECK (
        effective_at = (
            pg_catalog.date_trunc('week', effective_at AT TIME ZONE 'UTC')
            + INTERVAL '12 hours'
        ) AT TIME ZONE 'UTC'
    ),
    CHECK (
        (promotion_kind = 'initialization' AND baseline_authority_id IS NOT NULL)
        OR (promotion_kind <> 'initialization' AND candidate_id IS NOT NULL)
    ),
    CHECK (
        (status IN ('pending', 'repair_required', 'superseded')
            AND sealed_authority_id IS NULL AND sealed_at IS NULL)
        OR (status = 'sealed' AND sealed_authority_id IS NOT NULL AND sealed_at IS NOT NULL)
    ),
    CHECK (target_candidate_w IS NULL OR target_candidate_w BETWEEN 50 AND 500)
);

CREATE INDEX idx_reward_threshold_efforts_user
    ON public.reward_threshold_efforts(user_id);
CREATE INDEX idx_reward_threshold_candidates_user
    ON public.reward_threshold_candidates(user_id);
CREATE INDEX idx_reward_threshold_pending_due
    ON public.reward_threshold_pending_promotions(effective_at)
    WHERE status = 'pending';

ALTER TABLE public.reward_threshold_efforts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reward_threshold_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reward_threshold_source_envelopes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reward_threshold_ratchets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reward_threshold_pending_promotions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.reward_threshold_efforts FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON public.reward_threshold_candidates FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON public.reward_threshold_source_envelopes FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON public.reward_threshold_ratchets FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON public.reward_threshold_pending_promotions FROM PUBLIC, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION public.prevent_reward_threshold_append_only_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND pg_catalog.pg_trigger_depth() > 1
       AND OLD.ride_id IS NOT NULL
       AND NEW.ride_id IS NULL
       AND (pg_catalog.to_jsonb(NEW) - 'ride_id')
            = (pg_catalog.to_jsonb(OLD) - 'ride_id') THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE'
       AND TG_TABLE_NAME = 'reward_threshold_candidates'
       AND pg_catalog.to_jsonb(OLD)->>'disposition' LIKE 'pending_%'
       AND pg_catalog.to_jsonb(NEW)->>'disposition' = 'superseded'
       AND pg_catalog.to_jsonb(NEW)->'target_ftp_w' = 'null'::JSONB
       AND pg_catalog.to_jsonb(NEW)->'target_effective_at' = 'null'::JSONB
       AND pg_catalog.to_jsonb(NEW)->'superseded_at' <> 'null'::JSONB
       AND (pg_catalog.to_jsonb(NEW) - 'disposition' - 'target_ftp_w'
            - 'target_effective_at' - 'superseded_at')
           = (pg_catalog.to_jsonb(OLD) - 'disposition' - 'target_ftp_w'
              - 'target_effective_at' - 'superseded_at') THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'reward Threshold evidence is append-only';
END;
$$;

CREATE TRIGGER trg_reward_threshold_efforts_immutable
    BEFORE UPDATE OR DELETE ON public.reward_threshold_efforts
    FOR EACH ROW EXECUTE FUNCTION public.prevent_reward_threshold_append_only_mutation();
CREATE TRIGGER trg_reward_threshold_candidates_immutable
    BEFORE UPDATE OR DELETE ON public.reward_threshold_candidates
    FOR EACH ROW EXECUTE FUNCTION public.prevent_reward_threshold_append_only_mutation();

-- Account deletion 152 landed before these economic tables. Extend its
-- blocker and writer-fence authority forward without rewriting that migration.
ALTER FUNCTION public.br_account_deletion_db_blockers(UUID, TEXT)
    RENAME TO br_account_deletion_db_blockers_pre_threshold;
REVOKE ALL ON FUNCTION public.br_account_deletion_db_blockers_pre_threshold(UUID, TEXT)
    FROM PUBLIC, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION public.br_account_deletion_db_blockers(
    p_user_id UUID,
    p_wallet TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_blockers JSONB;
    v_count BIGINT;
BEGIN
    v_blockers := COALESCE(
        public.br_account_deletion_db_blockers_pre_threshold(p_user_id, p_wallet),
        '[]'::JSONB
    );
    SELECT
        (SELECT count(*) FROM public.reward_threshold_efforts
         WHERE user_id = p_user_id)
        + (SELECT count(*) FROM public.reward_threshold_candidates
           WHERE user_id = p_user_id)
        + (SELECT count(*) FROM public.reward_threshold_source_envelopes
           WHERE user_id = p_user_id)
        + (SELECT count(*) FROM public.reward_threshold_ratchets
           WHERE user_id = p_user_id)
        + (SELECT count(*) FROM public.reward_threshold_pending_promotions
           WHERE user_id = p_user_id)
    INTO v_count;
    IF v_count > 0 THEN
        v_blockers := v_blockers || pg_catalog.jsonb_build_array(
            pg_catalog.jsonb_build_object(
                'code', 'policy_review_required',
                'category', 'policy',
                'count', v_count,
                'source', 'reward_threshold_evidence',
                'action', 'contact_support'
            )
        );
    END IF;
    RETURN v_blockers;
END;
$$;
REVOKE ALL ON FUNCTION public.br_account_deletion_db_blockers(UUID, TEXT)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.br_account_deletion_db_blockers(UUID, TEXT)
    TO service_role;

-- The generic deletion fence intentionally fast-paths while no committed
-- deletion request exists. Threshold evidence cannot use that optimization:
-- a request may already own the user row in another uncommitted transaction.
-- Take a key-share lock first so the winning transaction is deterministic:
-- either evidence commits before deletion checks blockers, or deletion commits
-- first and this writer observes the non-active account state and fails closed.
CREATE OR REPLACE FUNCTION public.reward_threshold_account_owner_fence()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_user_id UUID;
    v_account_state TEXT;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.user_id IS DISTINCT FROM OLD.user_id THEN
        RAISE EXCEPTION 'account_identity_write_fenced'
            USING ERRCODE = '55000';
    END IF;
    v_user_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.user_id ELSE NEW.user_id END;
    SELECT "user".account_state INTO v_account_state
    FROM public.users AS "user"
    WHERE "user".id = v_user_id
    FOR KEY SHARE;
    IF NOT FOUND OR v_account_state <> 'active' THEN
        RAISE EXCEPTION 'account_identity_write_fenced'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.reward_threshold_account_owner_fence()
    FROM PUBLIC, anon, authenticated, service_role;

DO $$
DECLARE
    v_table TEXT;
BEGIN
    FOREACH v_table IN ARRAY ARRAY[
        'reward_threshold_efforts',
        'reward_threshold_candidates',
        'reward_threshold_source_envelopes',
        'reward_threshold_ratchets',
        'reward_threshold_pending_promotions'
    ] LOOP
        -- PostgreSQL fires same-kind triggers by name. This owner lock must run
        -- before account_deletion_write_fence can take its no-request fast path.
        EXECUTE pg_catalog.format(
            'CREATE TRIGGER account_deletion_00_threshold_owner_lock '
            'BEFORE INSERT OR UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION '
            'public.reward_threshold_account_owner_fence()',
            v_table
        );
        EXECUTE pg_catalog.format(
            'CREATE TRIGGER account_deletion_write_fence '
            'BEFORE INSERT OR UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION '
            'public.account_deletion_write_fence(''false'')',
            v_table
        );
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.next_reward_threshold_monday(
    p_evidence_at TIMESTAMPTZ
) RETURNS TIMESTAMPTZ
LANGUAGE sql
IMMUTABLE
SET search_path = ''
AS $$
    SELECT CASE
        WHEN p_evidence_at < (
            pg_catalog.date_trunc('week', p_evidence_at AT TIME ZONE 'UTC')
            + INTERVAL '12 hours'
        ) AT TIME ZONE 'UTC'
        THEN (
            pg_catalog.date_trunc('week', p_evidence_at AT TIME ZONE 'UTC')
            + INTERVAL '12 hours'
        ) AT TIME ZONE 'UTC'
        ELSE (
            pg_catalog.date_trunc('week', p_evidence_at AT TIME ZONE 'UTC')
            + INTERVAL '1 week 12 hours'
        ) AT TIME ZONE 'UTC'
    END
$$;

CREATE OR REPLACE FUNCTION public.reward_threshold_monday_on_or_after(
    p_not_before TIMESTAMPTZ
) RETURNS TIMESTAMPTZ
LANGUAGE sql
IMMUTABLE
SET search_path = ''
AS $$
    SELECT CASE
        WHEN p_not_before = (
            pg_catalog.date_trunc('week', p_not_before AT TIME ZONE 'UTC')
            + INTERVAL '12 hours'
        ) AT TIME ZONE 'UTC'
        THEN p_not_before
        ELSE public.next_reward_threshold_monday(p_not_before)
    END
$$;

-- Lock only legacy-authority owners that remain active. If deletion already
-- owns a user row, the lock recheck observes deletion_pending and skips the
-- economic backfill. If this statement wins first, deletion waits and then
-- sees the new Threshold blocker before it can authorize storage removal.
WITH active_authority_users AS MATERIALIZED (
    SELECT "user".id
    FROM public.users AS "user"
    WHERE "user".account_state = 'active'
      AND EXISTS (
          SELECT 1
          FROM public.reward_ftp_authorities AS authority
          WHERE authority.user_id = "user".id
      )
    FOR KEY SHARE
), ranked_authorities AS (
    SELECT
        authority.*,
        pg_catalog.row_number() OVER (
            PARTITION BY authority.user_id
            ORDER BY authority.ftp_w DESC, authority.verified_at DESC,
                     authority.effective_at DESC, authority.id DESC
        ) AS authority_rank,
        min(authority.effective_at) OVER (
            PARTITION BY authority.user_id
        ) AS first_effective_at,
        max(authority.effective_at) OVER (
            PARTITION BY authority.user_id
        ) AS latest_effective_at
    FROM public.reward_ftp_authorities AS authority
    JOIN active_authority_users AS active
      ON active.id = authority.user_id
), highest AS (
    SELECT * FROM ranked_authorities WHERE authority_rank = 1
)
INSERT INTO public.reward_threshold_ratchets (
    user_id, sealed_authority_id, sealed_ftp_w, established_at,
    last_raised_at, updated_at
)
SELECT
    highest.user_id,
    highest.id,
    highest.ftp_w,
    highest.first_effective_at,
    CASE WHEN EXISTS (
        SELECT 1
        FROM public.reward_ftp_authorities AS earlier
        WHERE earlier.user_id = highest.user_id
          AND earlier.effective_at < highest.effective_at
          AND earlier.ftp_w < highest.ftp_w
    ) THEN highest.effective_at ELSE NULL END,
    pg_catalog.clock_timestamp()
FROM highest;

WITH authority_state AS (
    SELECT
        ratchet.user_id,
        ratchet.sealed_authority_id,
        ratchet.sealed_ftp_w,
        max(authority.effective_at) AS latest_effective_at
    FROM public.reward_threshold_ratchets AS ratchet
    JOIN public.reward_ftp_authorities AS authority
      ON authority.user_id = ratchet.user_id
    GROUP BY ratchet.user_id, ratchet.sealed_authority_id, ratchet.sealed_ftp_w
), proposed AS (
    SELECT
        state.*,
        greatest(
            public.next_reward_threshold_monday(pg_catalog.clock_timestamp()),
            public.reward_threshold_monday_on_or_after(state.latest_effective_at)
        ) AS proposed_effective_at
    FROM authority_state AS state
), available AS (
    SELECT
        proposed.*,
        CASE WHEN EXISTS (
            SELECT 1
            FROM public.reward_ftp_authorities AS occupied
            WHERE occupied.user_id = proposed.user_id
              AND occupied.effective_at = proposed.proposed_effective_at
        ) THEN public.next_reward_threshold_monday(proposed.proposed_effective_at)
        ELSE proposed.proposed_effective_at END AS target_effective_at
    FROM proposed
)
INSERT INTO public.reward_threshold_pending_promotions (
    user_id, effective_at, candidate_id, baseline_authority_id,
    promotion_kind, target_candidate_w, target_ftp_w, status
)
SELECT
    available.user_id,
    available.target_effective_at,
    NULL,
    available.sealed_authority_id,
    'initialization',
    available.sealed_ftp_w,
    available.sealed_ftp_w,
    'pending'
FROM available;

CREATE OR REPLACE FUNCTION public.derive_reward_threshold_cp(
    p_best_180s_w NUMERIC,
    p_best_420s_w NUMERIC,
    p_best_900s_w NUMERIC
) RETURNS TABLE (cp_w NUMERIC, work_capacity_j NUMERIC)
LANGUAGE sql
IMMUTABLE
SET search_path = ''
AS $$
    WITH observations(x, y) AS (
        VALUES
            (1::NUMERIC / 180::NUMERIC, p_best_180s_w),
            (1::NUMERIC / 420::NUMERIC, p_best_420s_w),
            (1::NUMERIC / 900::NUMERIC, p_best_900s_w)
    ), means AS (
        SELECT pg_catalog.avg(x) AS mean_x, pg_catalog.avg(y) AS mean_y
        FROM observations
    ), fitted AS (
        SELECT
            pg_catalog.sum((o.x - m.mean_x) * (o.y - m.mean_y))
                / pg_catalog.sum((o.x - m.mean_x) * (o.x - m.mean_x)) AS slope,
            m.mean_x,
            m.mean_y
        FROM observations AS o CROSS JOIN means AS m
        GROUP BY m.mean_x, m.mean_y
    )
    SELECT
        pg_catalog.round(mean_y - slope * mean_x, 6),
        pg_catalog.round(slope, 6)
    FROM fitted
    WHERE p_best_180s_w IS NOT NULL
      AND p_best_420s_w IS NOT NULL
      AND p_best_900s_w IS NOT NULL
      AND p_best_180s_w >= 0
      AND p_best_420s_w >= 0
      AND p_best_900s_w >= 0
      AND slope > 0
      AND mean_y - slope * mean_x > 0
$$;

CREATE OR REPLACE FUNCTION public.seal_due_reward_threshold_promotions_for_user_at(
    p_user_id UUID,
    p_as_of TIMESTAMPTZ
) RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
SET TimeZone = 'UTC'
AS $$
DECLARE
    v_pending public.reward_threshold_pending_promotions%ROWTYPE;
    v_candidate public.reward_threshold_candidates%ROWTYPE;
    v_existing public.reward_ftp_authorities%ROWTYPE;
    v_authority public.reward_ftp_authorities%ROWTYPE;
    v_supersedes_id UUID;
    v_highest_w INTEGER;
    v_evidence JSONB;
    v_sealed_count INTEGER := 0;
BEGIN
    IF p_user_id IS NULL OR p_as_of IS NULL THEN
        RAISE EXCEPTION 'Threshold seal user and clock are required';
    END IF;

    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(p_user_id::TEXT, 2982)
    );
    IF EXISTS (
        SELECT 1
        FROM public.reward_threshold_pending_promotions AS pending
        WHERE pending.user_id = p_user_id
          AND pending.status = 'repair_required'
          AND pending.effective_at <= p_as_of
    ) THEN
        RAISE EXCEPTION 'Threshold authority requires operator repair';
    END IF;
    FOR v_pending IN
        SELECT pending.*
        FROM public.reward_threshold_pending_promotions AS pending
        WHERE pending.user_id = p_user_id
          AND pending.status = 'pending'
          AND pending.effective_at <= p_as_of
        ORDER BY pending.effective_at, pending.id
        FOR UPDATE
    LOOP
        v_candidate := NULL;
        IF v_pending.candidate_id IS NOT NULL THEN
            SELECT * INTO v_candidate
            FROM public.reward_threshold_candidates AS candidate
            WHERE candidate.id = v_pending.candidate_id;
            IF NOT FOUND OR v_candidate.disposition NOT LIKE 'pending_%' THEN
                RAISE EXCEPTION 'pending Threshold promotion lacks its accepted candidate';
            END IF;
        ELSIF v_pending.promotion_kind IS DISTINCT FROM 'initialization' THEN
            RAISE EXCEPTION 'non-initialization Threshold promotion lacks a candidate';
        END IF;

        IF v_pending.baseline_authority_id IS NOT NULL AND NOT EXISTS (
            SELECT 1
            FROM public.reward_ftp_authorities AS baseline
            WHERE baseline.id = v_pending.baseline_authority_id
              AND baseline.user_id = v_pending.user_id
        ) THEN
            RAISE EXCEPTION 'pending Threshold promotion lacks its baseline authority';
        END IF;

        SELECT max(authority.ftp_w) INTO v_highest_w
        FROM public.reward_ftp_authorities AS authority
        WHERE authority.user_id = v_pending.user_id;
        IF v_highest_w IS NOT NULL AND v_pending.target_ftp_w < v_highest_w THEN
            RAISE EXCEPTION 'Threshold seal would lower lifetime authority';
        END IF;

        v_evidence := pg_catalog.jsonb_build_object(
            'policy_version', 'reward_ftp_policy_2026_08_24_threshold_v1',
            'model_version', 'threshold_cp_3_7_15_v1',
            'promotion_kind', v_pending.promotion_kind,
            'baseline_authority_id', v_pending.baseline_authority_id,
            'candidate_id', v_pending.candidate_id,
            'ride_id', v_candidate.ride_id,
            'fitted_candidate_w', v_candidate.fitted_candidate_w,
            'economic_candidate_w', v_pending.target_candidate_w,
            'sealed_ftp_w', v_pending.target_ftp_w,
            'closure', 'lifetime_max_valid_cp_fit_v1',
            'promotion_deadband_percent', 2.5,
            'rounding', 'ceil_after_raw_deadband',
            'effective_at', v_pending.effective_at
        );

        SELECT authority.* INTO v_existing
        FROM public.reward_ftp_authorities AS authority
        WHERE authority.user_id = v_pending.user_id
          AND authority.effective_at = v_pending.effective_at;
        IF FOUND THEN
            IF v_existing.source IS DISTINCT FROM 'derived_eftp'
               OR v_existing.ftp_w IS DISTINCT FROM v_pending.target_ftp_w
               OR v_existing.verified_by IS DISTINCT FROM 'derived-threshold-v1'
               OR v_existing.evidence IS DISTINCT FROM v_evidence THEN
                RAISE EXCEPTION 'Threshold Monday authority conflicts with an existing sealed version';
            END IF;
            v_authority := v_existing;
        ELSE
            SELECT authority.id INTO v_supersedes_id
            FROM public.reward_ftp_authorities AS authority
            WHERE authority.user_id = v_pending.user_id
            ORDER BY authority.effective_at DESC, authority.verified_at DESC,
                     authority.id DESC
            LIMIT 1;

            INSERT INTO public.reward_ftp_authorities (
                user_id, ftp_w, source, evidence, evidence_hash, verified_by,
                verified_at, effective_at, supersedes_id
            ) VALUES (
                v_pending.user_id, v_pending.target_ftp_w, 'derived_eftp',
                v_evidence,
                pg_catalog.sha256(pg_catalog.convert_to(v_evidence::TEXT, 'UTF8')),
                'derived-threshold-v1', p_as_of, v_pending.effective_at,
                v_supersedes_id
            ) RETURNING * INTO v_authority;
        END IF;

        INSERT INTO public.reward_threshold_ratchets (user_id)
        VALUES (v_pending.user_id)
        ON CONFLICT (user_id) DO NOTHING;
        UPDATE public.reward_threshold_ratchets AS ratchet
        SET sealed_authority_id = v_authority.id,
            sealed_ftp_w = v_authority.ftp_w,
            established_at = COALESCE(ratchet.established_at, v_authority.effective_at),
            last_raised_at = CASE
                WHEN v_pending.promotion_kind = 'raise'
                    THEN v_authority.effective_at
                ELSE ratchet.last_raised_at
            END,
            updated_at = p_as_of
        WHERE ratchet.user_id = v_pending.user_id;

        UPDATE public.reward_threshold_pending_promotions AS pending
        SET status = 'sealed',
            sealed_authority_id = v_authority.id,
            sealed_at = p_as_of,
            updated_at = p_as_of
        WHERE pending.id = v_pending.id;
        v_sealed_count := v_sealed_count + 1;
    END LOOP;
    RETURN v_sealed_count;
END;
$$;

CREATE OR REPLACE FUNCTION public.register_reward_threshold_effort_at(
    p_ride_id UUID,
    p_best_180s_w NUMERIC,
    p_best_420s_w NUMERIC,
    p_best_900s_w NUMERIC,
    p_accepted_at TIMESTAMPTZ
) RETURNS public.reward_threshold_candidates
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
SET TimeZone = 'UTC'
AS $$
DECLARE
    v_ride public.rides%ROWTYPE;
    v_effort public.reward_threshold_efforts%ROWTYPE;
    v_candidate public.reward_threshold_candidates%ROWTYPE;
    v_ratchet public.reward_threshold_ratchets%ROWTYPE;
    v_source_envelope public.reward_threshold_source_envelopes%ROWTYPE;
    v_standing_pending public.reward_threshold_pending_promotions%ROWTYPE;
    v_received_at TIMESTAMPTZ;
    v_schedule_anchor_at TIMESTAMPTZ;
    v_upload_target_at TIMESTAMPTZ;
    v_source_eligible BOOLEAN;
    v_source_decision TEXT;
    v_evidence JSONB;
    v_display_180 NUMERIC;
    v_display_420 NUMERIC;
    v_display_900 NUMERIC;
    v_display_cp NUMERIC;
    v_display_work NUMERIC;
    v_proposed_180 NUMERIC;
    v_proposed_420 NUMERIC;
    v_proposed_900 NUMERIC;
    v_fitted_cp NUMERIC;
    v_fitted_work NUMERIC;
    v_economic_cp NUMERIC;
    v_economic_work NUMERIC;
    v_standing_fitted_cp NUMERIC;
    v_previous_candidate_id UUID;
    v_candidate_id UUID := gen_random_uuid();
    v_baseline_id UUID;
    v_baseline_w INTEGER;
    v_baseline_effective_at TIMESTAMPTZ;
    v_first_existing_effective_at TIMESTAMPTZ;
    v_latest_existing_effective_at TIMESTAMPTZ;
    v_disposition TEXT;
    v_promotion_kind TEXT;
    v_target_w INTEGER;
    v_target_at TIMESTAMPTZ;
BEGIN
    IF p_accepted_at IS NULL THEN
        RAISE EXCEPTION 'Threshold acceptance time is required';
    END IF;
    IF p_best_180s_w IS NULL
       AND p_best_420s_w IS NULL
       AND p_best_900s_w IS NULL THEN
        RAISE EXCEPTION 'Threshold evidence requires at least one power anchor';
    END IF;
    IF p_best_180s_w::TEXT IN ('NaN', 'Infinity', '-Infinity')
       OR p_best_420s_w::TEXT IN ('NaN', 'Infinity', '-Infinity')
       OR p_best_900s_w::TEXT IN ('NaN', 'Infinity', '-Infinity')
       OR p_best_180s_w < 0 OR p_best_420s_w < 0 OR p_best_900s_w < 0 THEN
        RAISE EXCEPTION 'Threshold anchors must be finite nonnegative watts';
    END IF;

    SELECT * INTO v_ride
    FROM public.rides AS ride
    WHERE ride.id = p_ride_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ride not found for Threshold evidence: %', p_ride_id;
    END IF;

    SELECT candidate.* INTO v_candidate
    FROM public.reward_threshold_candidates AS candidate
    WHERE candidate.ride_id = p_ride_id;
    IF FOUND THEN
        RETURN v_candidate;
    END IF;

    IF v_ride.upload_verified_at > p_accepted_at + INTERVAL '10 minutes' THEN
        RAISE EXCEPTION 'Threshold upload verification clock skew exceeds 10 minutes';
    END IF;
    v_received_at := least(
        COALESCE(v_ride.upload_verified_at, p_accepted_at), p_accepted_at
    );
    v_schedule_anchor_at := greatest(
        COALESCE(v_ride.upload_verified_at, p_accepted_at), p_accepted_at
    );

    v_source_eligible := COALESCE((
        v_ride.upload_verified_at IS NOT NULL
        AND COALESCE(
            lower(btrim(v_ride.file_hash::TEXT)) ~ '^[0-9a-f]{64}$',
            FALSE
        )
        AND v_ride.threshold_recording_source = 'br_ios'
        AND v_ride.threshold_power_source_id IS NOT NULL
        AND v_ride.threshold_source_identity_complete IS TRUE
        AND v_ride.import_diagnostics->>'provenance_tier' = 'first_party_recorded'
        AND v_ride.canonical_match IS TRUE
    ), FALSE);
    v_source_decision := CASE
        WHEN v_ride.upload_verified_at IS NULL THEN 'missing_upload_verification'
        WHEN v_ride.file_hash IS NULL
             OR lower(btrim(v_ride.file_hash::TEXT)) !~ '^[0-9a-f]{64}$'
            THEN 'missing_raw_file_hash'
        WHEN v_ride.threshold_recording_source IS DISTINCT FROM 'br_ios'
            THEN 'not_br_ios_recording'
        WHEN v_ride.threshold_power_source_id IS NULL
             OR v_ride.threshold_source_identity_complete IS NOT TRUE
            THEN 'missing_or_mixed_power_source_identity'
        WHEN v_ride.import_diagnostics->>'provenance_tier'
             IS DISTINCT FROM 'first_party_recorded'
            THEN 'not_first_party_recorded'
        WHEN v_ride.canonical_match IS NOT TRUE THEN 'canonical_mismatch_or_absent'
        ELSE 'eligible'
    END;

    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(v_ride.user_id::TEXT, 2982)
    );

    PERFORM public.seal_due_reward_threshold_promotions_for_user_at(
        v_ride.user_id, p_accepted_at
    );
    v_upload_target_at := public.next_reward_threshold_monday(
        v_schedule_anchor_at
    );

    SELECT authority.id, authority.ftp_w, authority.effective_at
    INTO v_baseline_id, v_baseline_w, v_baseline_effective_at
    FROM public.reward_ftp_authorities AS authority
    WHERE authority.user_id = v_ride.user_id
    ORDER BY authority.ftp_w DESC, authority.verified_at DESC,
             authority.effective_at DESC, authority.id DESC
    LIMIT 1;
    SELECT min(authority.effective_at), max(authority.effective_at)
    INTO v_first_existing_effective_at, v_latest_existing_effective_at
    FROM public.reward_ftp_authorities AS authority
    WHERE authority.user_id = v_ride.user_id;

    INSERT INTO public.reward_threshold_ratchets (
        user_id, sealed_authority_id, sealed_ftp_w, established_at
    ) VALUES (
        v_ride.user_id, v_baseline_id, v_baseline_w, v_first_existing_effective_at
    )
    ON CONFLICT (user_id) DO NOTHING;
    UPDATE public.reward_threshold_ratchets AS ratchet
    SET sealed_authority_id = v_baseline_id,
        sealed_ftp_w = v_baseline_w,
        established_at = COALESCE(
            ratchet.established_at, v_first_existing_effective_at
        ),
        updated_at = p_accepted_at
    WHERE ratchet.user_id = v_ride.user_id
      AND v_baseline_w IS NOT NULL
      AND (
          ratchet.sealed_ftp_w IS NULL
          OR ratchet.sealed_ftp_w < v_baseline_w
      );
    SELECT * INTO v_ratchet
    FROM public.reward_threshold_ratchets AS ratchet
    WHERE ratchet.user_id = v_ride.user_id
    FOR UPDATE;

    v_display_180 := greatest(v_ratchet.display_best_180s_w, p_best_180s_w);
    v_display_420 := greatest(v_ratchet.display_best_420s_w, p_best_420s_w);
    v_display_900 := greatest(v_ratchet.display_best_900s_w, p_best_900s_w);
    SELECT cp_w, work_capacity_j INTO v_display_cp, v_display_work
    FROM public.derive_reward_threshold_cp(
        v_display_180, v_display_420, v_display_900
    );

    IF v_source_eligible THEN
        INSERT INTO public.reward_threshold_source_envelopes (
            user_id, power_source_id
        ) VALUES (
            v_ride.user_id, v_ride.threshold_power_source_id
        )
        ON CONFLICT (user_id, power_source_id) DO NOTHING;
        SELECT * INTO v_source_envelope
        FROM public.reward_threshold_source_envelopes AS envelope
        WHERE envelope.user_id = v_ride.user_id
          AND envelope.power_source_id = v_ride.threshold_power_source_id
        FOR UPDATE;

        v_proposed_180 := greatest(
            v_source_envelope.accepted_best_180s_w, p_best_180s_w
        );
        v_proposed_420 := greatest(
            v_source_envelope.accepted_best_420s_w, p_best_420s_w
        );
        v_proposed_900 := greatest(
            v_source_envelope.accepted_best_900s_w, p_best_900s_w
        );
        SELECT cp_w, work_capacity_j INTO v_fitted_cp, v_fitted_work
        FROM public.derive_reward_threshold_cp(
            v_proposed_180, v_proposed_420, v_proposed_900
        );
        IF v_fitted_cp BETWEEN 50 AND 500 THEN
            IF v_ratchet.economic_candidate_w IS NULL
               OR v_fitted_cp > v_ratchet.economic_candidate_w THEN
                v_economic_cp := v_fitted_cp;
                v_economic_work := v_fitted_work;
            ELSE
                v_economic_cp := v_ratchet.economic_candidate_w;
                v_economic_work := v_ratchet.economic_work_capacity_j;
            END IF;
        ELSE
            v_economic_cp := v_ratchet.economic_candidate_w;
            v_economic_work := v_ratchet.economic_work_capacity_j;
        END IF;
    ELSE
        v_proposed_180 := NULL;
        v_proposed_420 := NULL;
        v_proposed_900 := NULL;
    END IF;

    IF NOT v_source_eligible THEN
        v_disposition := 'display_only';
    ELSIF v_fitted_cp IS NULL THEN
        IF v_proposed_180 IS NULL OR v_proposed_420 IS NULL OR v_proposed_900 IS NULL THEN
            v_disposition := 'insufficient_history';
        ELSE
            v_disposition := 'invalid_fit_review';
        END IF;
    ELSIF v_fitted_cp < 50 THEN
        v_disposition := 'below_bounds_review';
    ELSIF v_fitted_cp > 500 THEN
        v_disposition := 'above_bounds_review';
    ELSE
        v_target_w := pg_catalog.ceil(v_economic_cp)::INTEGER;
        v_target_at := v_upload_target_at;
        IF v_baseline_w IS NULL THEN
            v_disposition := 'pending_establishment';
            v_promotion_kind := 'establishment';
        ELSIF v_economic_cp < v_baseline_w::NUMERIC * 1.025 THEN
            v_disposition := 'below_deadband';
            v_target_w := NULL;
            v_target_at := NULL;
        ELSE
            v_disposition := 'pending_raise';
            v_promotion_kind := 'raise';
            v_target_at := greatest(
                v_target_at,
                public.reward_threshold_monday_on_or_after(
                    v_latest_existing_effective_at
                )
            );
        END IF;
    END IF;

    IF v_disposition LIKE 'pending_%' THEN
        WHILE EXISTS (
            SELECT 1
            FROM public.reward_ftp_authorities AS authority
            WHERE authority.user_id = v_ride.user_id
              AND authority.effective_at = v_target_at
        ) OR EXISTS (
            SELECT 1
            FROM public.reward_threshold_pending_promotions AS occupied
            WHERE occupied.user_id = v_ride.user_id
              AND occupied.effective_at = v_target_at
              AND occupied.status <> 'pending'
        ) LOOP
            v_target_at := public.next_reward_threshold_monday(v_target_at);
        END LOOP;

        SELECT pending.* INTO v_standing_pending
        FROM public.reward_threshold_pending_promotions AS pending
        WHERE pending.user_id = v_ride.user_id
          AND pending.effective_at = v_target_at
          AND pending.status = 'pending'
        FOR UPDATE;
        IF FOUND THEN
            SELECT candidate.fitted_candidate_w INTO v_standing_fitted_cp
            FROM public.reward_threshold_candidates AS candidate
            WHERE candidate.id = v_standing_pending.candidate_id;
            IF NOT (
                v_target_w > v_standing_pending.target_ftp_w
                OR (
                    v_target_w = v_standing_pending.target_ftp_w
                    AND v_economic_cp > v_standing_pending.target_candidate_w
                )
                OR (
                    v_target_w = v_standing_pending.target_ftp_w
                    AND v_economic_cp = v_standing_pending.target_candidate_w
                    AND v_fitted_cp > COALESCE(v_standing_fitted_cp, 0)
                )
                OR (
                    v_target_w = v_standing_pending.target_ftp_w
                    AND v_economic_cp = v_standing_pending.target_candidate_w
                    AND v_fitted_cp = v_standing_fitted_cp
                    AND v_candidate_id::TEXT
                        < COALESCE(
                            v_standing_pending.candidate_id::TEXT,
                            'ffffffff-ffff-ffff-ffff-ffffffffffff'
                        )
                )
            ) THEN
                v_disposition := 'superseded';
                v_target_w := NULL;
                v_target_at := NULL;
            ELSE
                v_previous_candidate_id := v_standing_pending.candidate_id;
            END IF;
        END IF;
    END IF;

    v_evidence := pg_catalog.jsonb_build_object(
        'ride_id', p_ride_id,
        'file_hash', lower(btrim(v_ride.file_hash::TEXT)),
        'upload_verified_at', v_ride.upload_verified_at,
        'accepted_at', p_accepted_at,
        'recording_source', v_ride.threshold_recording_source,
        'power_source_id', v_ride.threshold_power_source_id,
        'provenance_tier', v_ride.import_diagnostics->>'provenance_tier',
        'canonical_match', v_ride.canonical_match,
        'source_decision', v_source_decision,
        'best_180s_w', p_best_180s_w,
        'best_420s_w', p_best_420s_w,
        'best_900s_w', p_best_900s_w,
        'model_version', 'threshold_cp_3_7_15_v1',
        'rounding', 'ceil_after_raw_deadband'
    );
    INSERT INTO public.reward_threshold_efforts (
        ride_id, user_id, upload_verified_at, evidence_received_at,
        accepted_at, file_hash,
        recording_source, power_source_id, provenance_tier, canonical_match,
        structural_source_eligible, source_decision,
        best_180s_w, best_420s_w, best_900s_w, model_version,
        evidence, evidence_hash
    ) VALUES (
        p_ride_id, v_ride.user_id, v_ride.upload_verified_at, v_received_at,
        p_accepted_at,
        NULLIF(lower(btrim(v_ride.file_hash::TEXT)), ''),
        v_ride.threshold_recording_source, v_ride.threshold_power_source_id,
        v_ride.import_diagnostics->>'provenance_tier', v_ride.canonical_match,
        v_source_eligible, v_source_decision,
        p_best_180s_w, p_best_420s_w, p_best_900s_w,
        'threshold_cp_3_7_15_v1', v_evidence,
        pg_catalog.sha256(pg_catalog.convert_to(v_evidence::TEXT, 'UTF8'))
    ) RETURNING * INTO v_effort;

    INSERT INTO public.reward_threshold_candidates (
        id, effort_id, ride_id, user_id, power_source_id,
        display_best_180s_w, display_best_420s_w, display_best_900s_w,
        display_candidate_w, display_work_capacity_j,
        proposed_best_180s_w, proposed_best_420s_w, proposed_best_900s_w,
        fitted_candidate_w, fitted_work_capacity_j,
        economic_candidate_w, economic_work_capacity_j,
        baseline_authority_id, baseline_ftp_w, target_ftp_w,
        disposition, target_effective_at, superseded_at
    ) VALUES (
        v_candidate_id, v_effort.id, p_ride_id, v_ride.user_id,
        CASE WHEN v_source_eligible
            THEN v_ride.threshold_power_source_id ELSE NULL END,
        v_display_180, v_display_420, v_display_900,
        v_display_cp, v_display_work,
        v_proposed_180, v_proposed_420, v_proposed_900,
        v_fitted_cp, v_fitted_work,
        v_economic_cp, v_economic_work,
        v_baseline_id, v_baseline_w, v_target_w, v_disposition, v_target_at,
        CASE WHEN v_disposition = 'superseded' THEN p_accepted_at ELSE NULL END
    ) RETURNING * INTO v_candidate;

    UPDATE public.reward_threshold_ratchets AS ratchet
    SET display_best_180s_w = v_display_180,
        display_best_420s_w = v_display_420,
        display_best_900s_w = v_display_900,
        display_candidate_w = CASE
            WHEN v_display_cp BETWEEN 50 AND 500
                THEN greatest(ratchet.display_candidate_w, v_display_cp)
            ELSE ratchet.display_candidate_w
        END,
        economic_candidate_w = CASE
            WHEN v_source_eligible AND v_fitted_cp BETWEEN 50 AND 500
                THEN greatest(ratchet.economic_candidate_w, v_fitted_cp)
            ELSE ratchet.economic_candidate_w
        END,
        economic_work_capacity_j = CASE
            WHEN v_source_eligible AND v_fitted_cp BETWEEN 50 AND 500
                 AND (
                    ratchet.economic_candidate_w IS NULL
                    OR v_fitted_cp > ratchet.economic_candidate_w
                 ) THEN v_fitted_work
            ELSE ratchet.economic_work_capacity_j
        END,
        economic_power_source_id = CASE
            WHEN v_source_eligible AND v_fitted_cp BETWEEN 50 AND 500
                 AND (
                    ratchet.economic_candidate_w IS NULL
                    OR v_fitted_cp > ratchet.economic_candidate_w
                 ) THEN v_ride.threshold_power_source_id
            ELSE ratchet.economic_power_source_id
        END,
        updated_at = p_accepted_at
    WHERE ratchet.user_id = v_ride.user_id;

    IF v_source_eligible THEN
        UPDATE public.reward_threshold_source_envelopes AS envelope
        SET accepted_best_180s_w = v_proposed_180,
            accepted_best_420s_w = v_proposed_420,
            accepted_best_900s_w = v_proposed_900,
            accepted_candidate_w = CASE
                WHEN v_fitted_cp BETWEEN 50 AND 500
                    THEN greatest(envelope.accepted_candidate_w, v_fitted_cp)
                ELSE envelope.accepted_candidate_w
            END,
            accepted_work_capacity_j = CASE
                WHEN v_fitted_cp BETWEEN 50 AND 500
                     AND (
                        envelope.accepted_candidate_w IS NULL
                        OR v_fitted_cp > envelope.accepted_candidate_w
                     ) THEN v_fitted_work
                ELSE envelope.accepted_work_capacity_j
            END,
            last_accepted_candidate_id = CASE
                WHEN v_fitted_cp BETWEEN 50 AND 500
                     AND (
                        envelope.accepted_candidate_w IS NULL
                        OR v_fitted_cp > envelope.accepted_candidate_w
                     ) THEN v_candidate.id
                ELSE envelope.last_accepted_candidate_id
            END,
            updated_at = p_accepted_at
        WHERE envelope.user_id = v_ride.user_id
          AND envelope.power_source_id = v_ride.threshold_power_source_id;
    END IF;

    IF v_disposition LIKE 'pending_%' THEN
        INSERT INTO public.reward_threshold_pending_promotions (
            user_id, effective_at, candidate_id, baseline_authority_id,
            promotion_kind, target_candidate_w, target_ftp_w, status, updated_at
        ) VALUES (
            v_ride.user_id, v_target_at, v_candidate.id, v_baseline_id,
            v_promotion_kind, v_economic_cp, v_target_w, 'pending', p_accepted_at
        )
        ON CONFLICT (user_id, effective_at) DO UPDATE
        SET candidate_id = EXCLUDED.candidate_id,
            baseline_authority_id = EXCLUDED.baseline_authority_id,
            promotion_kind = EXCLUDED.promotion_kind,
            target_candidate_w = EXCLUDED.target_candidate_w,
            target_ftp_w = EXCLUDED.target_ftp_w,
            updated_at = EXCLUDED.updated_at
        WHERE public.reward_threshold_pending_promotions.status = 'pending';

        IF v_previous_candidate_id IS NOT NULL
           AND v_previous_candidate_id IS DISTINCT FROM v_candidate.id THEN
            UPDATE public.reward_threshold_candidates AS previous
            SET disposition = 'superseded',
                target_ftp_w = NULL,
                target_effective_at = NULL,
                superseded_at = p_accepted_at
            WHERE previous.id = v_previous_candidate_id;
        END IF;
    END IF;

    SELECT * INTO v_candidate
    FROM public.reward_threshold_candidates AS candidate
    WHERE candidate.id = v_candidate_id;
    RETURN v_candidate;
END;
$$;

CREATE OR REPLACE FUNCTION public.register_reward_threshold_effort(
    p_ride_id UUID,
    p_best_180s_w NUMERIC,
    p_best_420s_w NUMERIC,
    p_best_900s_w NUMERIC
) RETURNS public.reward_threshold_candidates
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT public.register_reward_threshold_effort_at(
        p_ride_id, p_best_180s_w, p_best_420s_w, p_best_900s_w,
        pg_catalog.clock_timestamp()
    )
$$;

CREATE OR REPLACE FUNCTION public.seal_due_reward_threshold_promotions_at(
    p_as_of TIMESTAMPTZ
) RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_user_id UUID;
    v_sealed_count INTEGER := 0;
    v_failure_code TEXT;
    v_failure_message TEXT;
BEGIN
    IF p_as_of IS NULL THEN
        RAISE EXCEPTION 'Threshold seal clock is required';
    END IF;

    FOR v_user_id IN
        SELECT DISTINCT pending.user_id
        FROM public.reward_threshold_pending_promotions AS pending
        WHERE pending.status = 'pending'
          AND pending.effective_at <= p_as_of
        ORDER BY pending.user_id
    LOOP
        BEGIN
            v_sealed_count := v_sealed_count
                + public.seal_due_reward_threshold_promotions_for_user_at(
                    v_user_id, p_as_of
                );
        EXCEPTION WHEN OTHERS THEN
            v_failure_code := SQLSTATE;
            v_failure_message := SQLERRM;
            BEGIN
                UPDATE public.reward_threshold_pending_promotions AS pending
                SET status = 'repair_required',
                    failure_code = v_failure_code,
                    failure_message = v_failure_message,
                    failed_at = p_as_of,
                    updated_at = p_as_of
                WHERE pending.user_id = v_user_id
                  AND pending.status = 'pending'
                  AND pending.effective_at <= p_as_of;
            EXCEPTION WHEN OTHERS THEN
                -- A deletion fence can intentionally forbid even the failure
                -- state write. Keep the original pending commitment intact and
                -- continue the batch; the database warning preserves an
                -- operator-visible trace without weakening that fence.
                RAISE WARNING
                    'Threshold seal failure for user % could not be recorded: [%] %',
                    v_user_id, SQLSTATE, SQLERRM;
            END;
        END;
    END LOOP;
    RETURN v_sealed_count;
END;
$$;

CREATE OR REPLACE FUNCTION public.seal_due_reward_threshold_promotions()
RETURNS INTEGER
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT public.seal_due_reward_threshold_promotions_at(
        pg_catalog.clock_timestamp()
    )
$$;

CREATE OR REPLACE FUNCTION public.repair_reward_threshold_promotion(
    p_pending_id UUID,
    p_action TEXT,
    p_reason TEXT
) RETURNS public.reward_threshold_pending_promotions
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
SET TimeZone = 'UTC'
AS $$
DECLARE
    v_pending public.reward_threshold_pending_promotions%ROWTYPE;
    v_highest_w INTEGER;
BEGIN
    IF p_pending_id IS NULL
       OR p_action NOT IN ('retry', 'supersede')
       OR btrim(COALESCE(p_reason, '')) = '' THEN
        RAISE EXCEPTION 'Threshold repair requires exact id, action, and reason';
    END IF;
    SELECT * INTO v_pending
    FROM public.reward_threshold_pending_promotions AS pending
    WHERE pending.id = p_pending_id
    FOR UPDATE;
    IF NOT FOUND OR v_pending.status <> 'repair_required' THEN
        RAISE EXCEPTION 'Threshold promotion is not repairable';
    END IF;

    IF p_action = 'supersede' THEN
        SELECT max(authority.ftp_w) INTO v_highest_w
        FROM public.reward_ftp_authorities AS authority
        WHERE authority.user_id = v_pending.user_id;
        IF v_highest_w IS NULL OR v_highest_w < v_pending.target_ftp_w THEN
            RAISE EXCEPTION 'Threshold repair cannot supersede an uncovered target';
        END IF;
        UPDATE public.reward_threshold_pending_promotions AS pending
        SET status = 'superseded',
            resolution_reason = p_reason,
            resolved_at = pg_catalog.clock_timestamp(),
            updated_at = pg_catalog.clock_timestamp()
        WHERE pending.id = p_pending_id
        RETURNING * INTO v_pending;
        IF v_pending.candidate_id IS NOT NULL THEN
            UPDATE public.reward_threshold_candidates AS candidate
            SET disposition = 'superseded',
                target_ftp_w = NULL,
                target_effective_at = NULL,
                superseded_at = pg_catalog.clock_timestamp()
            WHERE candidate.id = v_pending.candidate_id
              AND candidate.disposition LIKE 'pending_%';
        END IF;
    ELSE
        UPDATE public.reward_threshold_pending_promotions AS pending
        SET status = 'pending',
            resolution_reason = p_reason,
            resolved_at = pg_catalog.clock_timestamp(),
            updated_at = pg_catalog.clock_timestamp()
        WHERE pending.id = p_pending_id
        RETURNING * INTO v_pending;
    END IF;
    RETURN v_pending;
END;
$$;

CREATE OR REPLACE FUNCTION public.enforce_derived_only_reward_ftp_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF NEW.source IS DISTINCT FROM 'derived_eftp' THEN
        RAISE EXCEPTION 'reward FTP authority is derived-only after Threshold cutover';
    END IF;
    IF NEW.effective_at IS DISTINCT FROM (
        pg_catalog.date_trunc('week', NEW.effective_at AT TIME ZONE 'UTC')
        + INTERVAL '12 hours'
    ) AT TIME ZONE 'UTC' THEN
        RAISE EXCEPTION 'derived reward Threshold authorities seal Monday at 12:00 UTC';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM public.reward_ftp_authorities AS prior
        WHERE prior.user_id = NEW.user_id
          AND prior.ftp_w > NEW.ftp_w
    ) THEN
        RAISE EXCEPTION 'derived reward Threshold authority cannot lower lifetime authority';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM public.reward_ftp_authorities AS prior
        WHERE prior.user_id = NEW.user_id
          AND prior.effective_at >= NEW.effective_at
    ) THEN
        RAISE EXCEPTION 'derived reward Threshold authority cannot reopen a sealed boundary';
    END IF;
    IF NEW.verified_by IS DISTINCT FROM 'derived-threshold-v1'
       OR NEW.evidence->>'policy_version'
            IS DISTINCT FROM 'reward_ftp_policy_2026_08_24_threshold_v1'
       OR NEW.evidence->>'model_version'
            IS DISTINCT FROM 'threshold_cp_3_7_15_v1'
       OR NOT EXISTS (
            SELECT 1
            FROM public.reward_threshold_pending_promotions AS pending
            WHERE pending.user_id = NEW.user_id
              AND pending.effective_at = NEW.effective_at
              AND pending.status = 'pending'
              AND pending.target_ftp_w = NEW.ftp_w
              AND pending.promotion_kind
                    IS NOT DISTINCT FROM NEW.evidence->>'promotion_kind'
              AND pending.candidate_id::TEXT
                    IS NOT DISTINCT FROM NEW.evidence->>'candidate_id'
              AND pending.baseline_authority_id::TEXT
                    IS NOT DISTINCT FROM NEW.evidence->>'baseline_authority_id'
       ) THEN
        RAISE EXCEPTION 'derived reward Threshold authority lacks its pending commitment';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_reward_ftp_derived_only_insert
    ON public.reward_ftp_authorities;
CREATE TRIGGER trg_reward_ftp_derived_only_insert
    BEFORE INSERT ON public.reward_ftp_authorities
    FOR EACH ROW EXECUTE FUNCTION public.enforce_derived_only_reward_ftp_insert();

CREATE OR REPLACE FUNCTION public.enforce_ride_reward_ftp_snapshot()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_existing_snapshot BOOLEAN := (
        TG_OP = 'UPDATE' AND OLD.reward_ftp_w IS NOT NULL
    );
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF OLD.reward_ftp_w IS NOT NULL AND (
            NEW.reward_ftp_w IS DISTINCT FROM OLD.reward_ftp_w
            OR NEW.reward_ftp_source IS DISTINCT FROM OLD.reward_ftp_source
            OR NEW.reward_ftp_authority_id IS DISTINCT FROM OLD.reward_ftp_authority_id
            OR NEW.reward_ftp_policy_version IS DISTINCT FROM OLD.reward_ftp_policy_version
            OR NEW.reward_ftp_activity_started_at IS DISTINCT FROM OLD.reward_ftp_activity_started_at
        ) THEN
            RAISE EXCEPTION 'ride reward FTP snapshot is immutable';
        END IF;
        IF OLD.economic_tss IS NOT NULL
           AND NEW.economic_tss IS DISTINCT FROM OLD.economic_tss THEN
            RAISE EXCEPTION 'ride economic TSS snapshot is immutable';
        END IF;
    END IF;

    IF NEW.reward_ftp_w IS NULL THEN
        IF NEW.reward_ftp_source IS NOT NULL
           OR NEW.reward_ftp_authority_id IS NOT NULL
           OR NEW.reward_ftp_policy_version IS NOT NULL
           OR NEW.reward_ftp_activity_started_at IS NOT NULL THEN
            RAISE EXCEPTION 'partial ride reward FTP snapshot is forbidden';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.reward_ftp_w NOT BETWEEN 50 AND 500
       OR NEW.reward_ftp_activity_started_at IS NULL
       OR NEW.reward_ftp_policy_version NOT IN (
            'reward_ftp_policy_2026_07_14',
            'reward_ftp_policy_2026_08_24_threshold_v1'
       ) THEN
        RAISE EXCEPTION 'invalid ride reward FTP snapshot';
    END IF;
    IF NEW.reward_ftp_policy_version = 'reward_ftp_policy_2026_07_14'
       AND NOT v_existing_snapshot THEN
        RAISE EXCEPTION 'new rides require the current reward Threshold policy';
    END IF;

    IF NEW.reward_ftp_source = 'network_default' THEN
        IF NEW.reward_ftp_w <> 200 OR NEW.reward_ftp_authority_id IS NOT NULL THEN
            RAISE EXCEPTION 'inconsistent network-default reward FTP snapshot';
        END IF;
    ELSIF NOT EXISTS (
        SELECT 1
        FROM public.reward_ftp_authorities AS authority
        WHERE authority.id = NEW.reward_ftp_authority_id
          AND authority.user_id = NEW.user_id
          AND authority.ftp_w = NEW.reward_ftp_w
          AND authority.source = NEW.reward_ftp_source
          AND authority.effective_at <= NEW.reward_ftp_activity_started_at
    ) THEN
        RAISE EXCEPTION 'ride reward FTP snapshot lacks matching verified authority';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.enforce_plan_reward_ftp_snapshot()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.reward_ftp_w IS NOT NULL AND (
        NEW.reward_ftp_w IS DISTINCT FROM OLD.reward_ftp_w
        OR NEW.reward_ftp_source IS DISTINCT FROM OLD.reward_ftp_source
        OR NEW.reward_ftp_authority_id IS DISTINCT FROM OLD.reward_ftp_authority_id
        OR NEW.reward_ftp_policy_version IS DISTINCT FROM OLD.reward_ftp_policy_version
    ) THEN
        RAISE EXCEPTION 'frozen plan reward FTP provenance cannot be changed';
    END IF;

    IF NEW.reward_ftp_w IS NULL THEN
        IF NEW.reward_ftp_source IS NOT NULL
           OR NEW.reward_ftp_authority_id IS NOT NULL
           OR NEW.reward_ftp_policy_version IS NOT NULL THEN
            RAISE EXCEPTION 'partial plan reward FTP snapshot is forbidden';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.reward_ftp_w NOT BETWEEN 50 AND 500
       OR NEW.reward_ftp_policy_version NOT IN (
            'reward_ftp_policy_2026_07_14',
            'reward_ftp_policy_2026_08_24_threshold_v1'
       ) THEN
        RAISE EXCEPTION 'invalid frozen plan reward FTP snapshot';
    END IF;
    IF NEW.reward_ftp_source = 'network_default' THEN
        IF NEW.reward_ftp_w <> 200 OR NEW.reward_ftp_authority_id IS NOT NULL THEN
            RAISE EXCEPTION 'inconsistent plan network-default reward FTP';
        END IF;
    ELSIF NOT EXISTS (
        SELECT 1
        FROM public.reward_ftp_authorities AS authority
        WHERE authority.id = NEW.reward_ftp_authority_id
          AND authority.user_id = NEW.user_id
          AND authority.ftp_w = NEW.reward_ftp_w
          AND authority.source = NEW.reward_ftp_source
          AND authority.effective_at <= NEW.started_at
    ) THEN
        RAISE EXCEPTION 'frozen plan lacks matching verified reward FTP authority';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.rides AS ride
        WHERE ride.id = NEW.ride_id
          AND ride.user_id = NEW.user_id
          AND ride.reward_ftp_w = NEW.reward_ftp_w
          AND ride.reward_ftp_source = NEW.reward_ftp_source
          AND ride.reward_ftp_authority_id IS NOT DISTINCT FROM NEW.reward_ftp_authority_id
          AND ride.reward_ftp_policy_version = NEW.reward_ftp_policy_version
          AND ride.reward_ftp_activity_started_at = NEW.started_at
          AND ride.economic_tss IS NOT NULL
          AND pg_catalog.trunc(ride.economic_tss)::BIGINT = NEW.total_tss
    ) THEN
        RAISE EXCEPTION 'frozen plan reward FTP or economic TSS differs from ride snapshot';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.bind_ride_reward_ftp(
    p_ride_id UUID,
    p_activity_started_at TIMESTAMPTZ DEFAULT NULL
) RETURNS TABLE (
    reward_ftp_w INTEGER,
    reward_ftp_source TEXT,
    reward_ftp_authority_id UUID,
    reward_ftp_policy_version TEXT,
    reward_ftp_activity_started_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    v_ride public.rides%ROWTYPE;
    v_authority public.reward_ftp_authorities%ROWTYPE;
    v_activity_started_at TIMESTAMPTZ;
BEGIN
    SELECT * INTO v_ride
    FROM public.rides AS ride
    WHERE ride.id = p_ride_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ride not found for reward FTP binding: %', p_ride_id;
    END IF;

    IF v_ride.reward_ftp_w IS NOT NULL THEN
        RETURN QUERY
        SELECT ride.reward_ftp_w, ride.reward_ftp_source,
               ride.reward_ftp_authority_id, ride.reward_ftp_policy_version,
               ride.reward_ftp_activity_started_at
        FROM public.rides AS ride WHERE ride.id = p_ride_id;
        RETURN;
    END IF;

    PERFORM public.seal_due_reward_threshold_promotions_for_user_at(
        v_ride.user_id, pg_catalog.clock_timestamp()
    );

    v_activity_started_at := COALESCE(
        p_activity_started_at, pg_catalog.clock_timestamp()
    );
    SELECT authority.* INTO v_authority
    FROM public.reward_ftp_authorities AS authority
    WHERE authority.user_id = v_ride.user_id
      AND authority.effective_at <= v_activity_started_at
    ORDER BY authority.effective_at DESC, authority.verified_at DESC,
             authority.id DESC
    LIMIT 1;

    UPDATE public.rides AS ride
    SET reward_ftp_w = CASE WHEN FOUND THEN v_authority.ftp_w ELSE 200 END,
        reward_ftp_source = CASE
            WHEN FOUND THEN v_authority.source ELSE 'network_default'
        END,
        reward_ftp_authority_id = CASE WHEN FOUND THEN v_authority.id ELSE NULL END,
        reward_ftp_policy_version = 'reward_ftp_policy_2026_08_24_threshold_v1',
        reward_ftp_activity_started_at = v_activity_started_at
    WHERE ride.id = p_ride_id;

    RETURN QUERY
    SELECT ride.reward_ftp_w, ride.reward_ftp_source,
           ride.reward_ftp_authority_id, ride.reward_ftp_policy_version,
           ride.reward_ftp_activity_started_at
    FROM public.rides AS ride WHERE ride.id = p_ride_id;
END;
$$;

REVOKE ALL ON FUNCTION public.register_reward_ftp_authority(
    UUID, INTEGER, TEXT, JSONB, TEXT, TIMESTAMPTZ
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.register_reward_threshold_effort_at(
    UUID, NUMERIC, NUMERIC, NUMERIC, TIMESTAMPTZ
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.register_reward_threshold_effort(
    UUID, NUMERIC, NUMERIC, NUMERIC
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.seal_due_reward_threshold_promotions_at(
    TIMESTAMPTZ
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.seal_due_reward_threshold_promotions_for_user_at(
    UUID, TIMESTAMPTZ
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.seal_due_reward_threshold_promotions()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.repair_reward_threshold_promotion(UUID, TEXT, TEXT)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.next_reward_threshold_monday(TIMESTAMPTZ)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.reward_threshold_monday_on_or_after(TIMESTAMPTZ)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.derive_reward_threshold_cp(NUMERIC, NUMERIC, NUMERIC)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.enforce_ride_threshold_evidence()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.prevent_reward_threshold_append_only_mutation()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.enforce_derived_only_reward_ftp_insert()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.enforce_ride_reward_ftp_snapshot()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.enforce_plan_reward_ftp_snapshot()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.bind_ride_reward_ftp(UUID, TIMESTAMPTZ)
    FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.register_reward_threshold_effort(
    UUID, NUMERIC, NUMERIC, NUMERIC
) TO service_role;
GRANT EXECUTE ON FUNCTION public.seal_due_reward_threshold_promotions()
    TO service_role;
GRANT EXECUTE ON FUNCTION public.repair_reward_threshold_promotion(UUID, TEXT, TEXT)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.bind_ride_reward_ftp(UUID, TIMESTAMPTZ)
    TO service_role;
