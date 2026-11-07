BEGIN;
CREATE TABLE IF NOT EXISTS public.access_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor UUID NOT NULL,
    action TEXT NOT NULL,
    target TEXT,
    at TIMESTAMPTZ NOT NULL DEFAULT now(),
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);
ALTER TABLE public.access_audit ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.access_audit FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT ON public.access_audit TO service_role;

-- One transaction for action + audit: a failed audit cannot leave an unaudited change.
CREATE OR REPLACE FUNCTION public.access_admin_action(
    p_actor UUID, p_action TEXT, p_target TEXT DEFAULT NULL,
    p_details JSONB DEFAULT '{}'::jsonb, p_code_hash TEXT DEFAULT NULL
) RETURNS JSONB LANGUAGE plpgsql SET search_path = public AS $$
DECLARE
    v_result JSONB;
    v_invite public.invite_codes%ROWTYPE;
    v_user UUID;
    v_users UUID[];
    v_count INTEGER;
    v_details JSONB := '{}'::jsonb;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.admin_users WHERE user_id = p_actor) THEN
        RAISE EXCEPTION 'Admin access required' USING ERRCODE = '42501';
    END IF;
    IF p_action = 'mint_invite' THEN
        IF p_code_hash IS NULL OR p_code_hash !~ '^[0-9a-f]{64}$'
           OR coalesce((p_details->>'max_uses')::int,1) < 1
           OR coalesce((p_details->>'expires_in_days')::int,7) < 1 THEN
            RAISE EXCEPTION 'Invalid invite parameters';
        END IF;
        INSERT INTO public.invite_codes(code_hash,max_uses,expires_at,intended_for,issued_to_label,created_by)
        VALUES (p_code_hash,coalesce((p_details->>'max_uses')::int,1),
                now()+make_interval(days=>coalesce((p_details->>'expires_in_days')::int,7)),
                nullif(trim(p_details->>'intended_for'),''),nullif(trim(p_details->>'label'),''),p_actor::text)
        RETURNING * INTO v_invite;
        p_target := v_invite.id::text;
        v_result := jsonb_build_object('ok',true,'invite',
            (to_jsonb(v_invite)-'code'-'code_hash') || jsonb_build_object('remaining',v_invite.max_uses,'uses','[]'::jsonb));
        v_details := jsonb_build_object('max_uses',v_invite.max_uses,'expires_at',v_invite.expires_at,
            'intended_for',v_invite.intended_for,'label',v_invite.issued_to_label);
    ELSIF p_action = 'list_invites' THEN
        SELECT jsonb_build_object('ok',true,'invites',coalesce(jsonb_agg(item ORDER BY item->>'created_at',item->>'id'),'[]'::jsonb))
        INTO v_result FROM (
            SELECT (to_jsonb(ic)-'code'-'code_hash') || jsonb_build_object(
                'remaining',CASE WHEN ic.max_uses IS NULL THEN NULL ELSE greatest(0,ic.max_uses-ic.current_uses) END,
                'uses',coalesce((SELECT jsonb_agg(jsonb_build_object('wallet',u.wallet,'when',u.used_at) ORDER BY u.used_at,u.id)
                                  FROM public.invite_code_usage u WHERE u.code_id=ic.id),'[]'::jsonb)) AS item
            FROM public.invite_codes ic
        ) invitations;
    ELSIF p_action = 'deactivate_invite' THEN
        UPDATE public.invite_codes SET is_active=false WHERE id=p_target::uuid;
        GET DIAGNOSTICS v_count = ROW_COUNT;
        v_result := CASE WHEN v_count=1 THEN jsonb_build_object('ok',true,'id',p_target,'is_active',false)
                         ELSE jsonb_build_object('ok',false,'error','invite_not_found') END;
    ELSIF p_action IN ('admit_cohort','revoke_cohort','revoke_sessions') THEN
        SELECT array_agg(DISTINCT id) INTO v_users FROM (
            SELECT id FROM public.users WHERE wallet=p_target
            UNION SELECT user_id FROM public.auth_identities
                  WHERE wallet=p_target OR (provider='wallet' AND provider_subject=p_target)
        ) identities;
        IF coalesce(cardinality(v_users),0) <> 1 THEN
            v_result := jsonb_build_object('ok',false,'error',
                CASE WHEN coalesce(cardinality(v_users),0)=0 THEN 'wallet_not_found' ELSE 'identity_conflict' END);
        ELSE
            v_user := v_users[1];
            -- Serialize admission mutations on the canonical user.
            PERFORM 1 FROM public.users WHERE id=v_user FOR UPDATE;
            IF p_action = 'revoke_sessions' THEN
                UPDATE public.auth_refresh_tokens SET revoked_at=now(),revocation_reason='admin_revoked'
                WHERE revoked_at IS NULL AND wallet IN (
                    SELECT wallet FROM public.users WHERE id=v_user
                    UNION SELECT wallet FROM public.auth_identities WHERE user_id=v_user
                    UNION SELECT provider_subject FROM public.auth_identities WHERE user_id=v_user AND provider='wallet'
                );
                GET DIAGNOSTICS v_count = ROW_COUNT;
                v_result := jsonb_build_object('ok',true,'user_id',v_user,'revoked',v_count);
            ELSE
                UPDATE public.users SET
                    cohort_admitted_at=CASE WHEN p_action='admit_cohort' THEN now() ELSE NULL END,
                    cohort_admitted_by=CASE WHEN p_action='admit_cohort' THEN p_actor::text ELSE NULL END
                WHERE id=v_user;
                v_result := jsonb_build_object('ok',true,'user_id',v_user,'cohort_admitted',p_action='admit_cohort');
            END IF;
        END IF;
    ELSE
        RAISE EXCEPTION 'Unknown access action';
    END IF;
    INSERT INTO public.access_audit(actor,action,target,details)
    VALUES(p_actor,p_action,p_target,v_details || (v_result-'invites'-'invite'));
    RETURN v_result;
END $$;
REVOKE ALL ON FUNCTION public.access_admin_action(UUID,TEXT,TEXT,JSONB,TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.access_admin_action(UUID,TEXT,TEXT,JSONB,TEXT) TO service_role;
COMMIT;
