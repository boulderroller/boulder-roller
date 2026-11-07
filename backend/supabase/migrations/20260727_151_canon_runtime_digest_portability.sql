-- Keep the V4-B reservation commitment check independent of the pgcrypto schema.
-- Canonical mirror:
-- backend/supabase/migrations/20260727_151_canon_runtime_digest_portability.sql

DO $migration$
DECLARE
    v_signature REGPROCEDURE := pg_catalog.to_regprocedure(
        'public.reserve_canon_vault_activation(uuid,text,text,text,text,text,text,bigint,text,text,text,bigint)'
    );
    v_definition TEXT;
    v_legacy_fragment TEXT := $legacy$public.digest(
                    pg_catalog.decode(v_expected_commitment, 'hex'),
                    'sha256'
                )$legacy$;
    v_portable_fragment TEXT := $portable$pg_catalog.sha256(
                    pg_catalog.decode(v_expected_commitment, 'hex')
                )$portable$;
BEGIN
    IF v_signature IS NULL THEN
        RAISE EXCEPTION 'canonical Vault reservation function is missing'
            USING ERRCODE = '42883';
    END IF;
    IF pg_catalog.to_regprocedure('pg_catalog.sha256(bytea)') IS NULL THEN
        RAISE EXCEPTION 'PostgreSQL SHA-256 primitive is unavailable'
            USING ERRCODE = '42883';
    END IF;

    SELECT pg_catalog.pg_get_functiondef(v_signature)
    INTO v_definition;
    IF pg_catalog.strpos(v_definition, v_portable_fragment) > 0 THEN
        RETURN;
    END IF;
    IF pg_catalog.strpos(v_definition, v_legacy_fragment) = 0 THEN
        RAISE EXCEPTION 'canonical Vault reservation digest source drifted'
            USING ERRCODE = '22000';
    END IF;

    EXECUTE pg_catalog.replace(
        v_definition,
        v_legacy_fragment,
        v_portable_fragment
    );

    SELECT pg_catalog.pg_get_functiondef(v_signature)
    INTO v_definition;
    IF pg_catalog.strpos(v_definition, v_portable_fragment) = 0
       OR pg_catalog.strpos(v_definition, 'public.digest(') > 0 THEN
        RAISE EXCEPTION 'canonical Vault reservation digest patch did not apply'
            USING ERRCODE = '22000';
    END IF;
END;
$migration$;
