-- Close Boulder Roller's Supabase Data API boundary.
--
-- Portal and iOS clients use the Boulder Roller API. The reviewed contract is
-- therefore RLS with no client policies, no anon/authenticated object access,
-- and unchanged effective service_role authority. The normalized object scope
-- is committed beside this file in 153_public_data_api_rls_lockdown.catalog.json.
-- Migration 152's reviewed additions are validated but not swept by this file.
--
-- The entire mutating body is one server statement. This matters because
-- default `psql -f` continues after an error; a lone preflight statement would
-- not protect later DDL. Only apply_sql_migrations.py supplies the transaction-
-- local marker, committed catalog manifest, and approved catalog fingerprint.

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';

DO $migration$
DECLARE
  catalog_manifest JSONB;
  manifest_text TEXT;
  expected_catalog_fingerprint TEXT;
  approved_catalog_fingerprint TEXT;
  service_role_state_before TEXT;
  service_role_state_after TEXT;
  difference TEXT;
  violation TEXT;
  target RECORD;
  object_kind TEXT;
BEGIN
  IF current_setting('boulderroller.migration_runner', true)
       IS DISTINCT FROM 'apply_sql_migrations_v1'
  THEN
    RAISE EXCEPTION
      '153_public_data_api_rls_lockdown.sql requires apply_sql_migrations.py';
  END IF;

  manifest_text := current_setting(
    'boulderroller.public_data_api_rls_catalog_manifest',
    true
  );
  IF manifest_text IS NULL OR manifest_text = '' THEN
    RAISE EXCEPTION 'RLS lockdown runner did not supply the committed catalog manifest';
  END IF;
  catalog_manifest := manifest_text::jsonb;

  IF catalog_manifest->>'version' IS DISTINCT FROM '1'
     OR catalog_manifest->>'project_ref'
          IS DISTINCT FROM 'qzkqjevawthyboymqrle'
  THEN
    RAISE EXCEPTION 'RLS lockdown catalog manifest identity mismatch';
  END IF;

  expected_catalog_fingerprint := lower(
    catalog_manifest->>'expected_catalog_fingerprint'
  );
  approved_catalog_fingerprint := lower(current_setting(
    'boulderroller.approved_public_data_api_rls_catalog_sha256',
    true
  ));
  IF expected_catalog_fingerprint !~ '^[0-9a-f]{64}$'
     OR approved_catalog_fingerprint
          IS DISTINCT FROM expected_catalog_fingerprint
  THEN
    RAISE EXCEPTION 'RLS lockdown committed catalog approval mismatch';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = current_user
      AND (
        rolsuper
        OR NOT rolbypassrls
        OR NOT rolcreaterole
        OR NOT rolcreatedb
      )
  ) THEN
    RAISE EXCEPTION
      'RLS lockdown must run as the audited non-superuser database owner';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_database
    WHERE datname = current_database()
      AND datdba = (SELECT oid FROM pg_roles WHERE rolname = current_user)
  ) THEN
    RAISE EXCEPTION 'RLS lockdown runner is not the current database owner';
  END IF;

  IF NOT has_schema_privilege(current_user, 'public', 'USAGE')
     OR NOT has_schema_privilege(current_user, 'public', 'CREATE')
  THEN
    RAISE EXCEPTION 'RLS lockdown owner lacks public schema authority';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'service_role'
      AND rolbypassrls
      AND NOT rolsuper
  ) THEN
    RAISE EXCEPTION
      'service_role must exist with BYPASSRLS and without SUPERUSER';
  END IF;

  CREATE TEMP TABLE br_153_relation_targets ON COMMIT DROP AS
  SELECT item->>'kind' AS kind, item->>'name' AS object_name
  FROM jsonb_array_elements(catalog_manifest->'app_relations') AS item;
  ALTER TABLE br_153_relation_targets
    ADD PRIMARY KEY (kind, object_name);

  CREATE TEMP TABLE br_153_routine_targets ON COMMIT DROP AS
  SELECT
    item->>'kind' AS kind,
    item->>'name' AS object_name,
    item->>'argument_types' AS argument_types
  FROM jsonb_array_elements(catalog_manifest->'app_routines') AS item;
  ALTER TABLE br_153_routine_targets
    ADD PRIMARY KEY (kind, object_name, argument_types);

  CREATE TEMP TABLE br_153_view_targets ON COMMIT DROP AS
  SELECT value #>> '{}' AS object_name
  FROM jsonb_array_elements(catalog_manifest->'views_to_convert');
  ALTER TABLE br_153_view_targets ADD PRIMARY KEY (object_name);

  CREATE TEMP TABLE br_153_provider_relation_exceptions ON COMMIT DROP AS
  SELECT
    item->>'kind' AS kind,
    item->>'name' AS object_name,
    item->>'owner' AS owner_name
  FROM jsonb_array_elements(
    catalog_manifest->'provider_relation_exceptions'
  ) AS item;
  ALTER TABLE br_153_provider_relation_exceptions
    ADD PRIMARY KEY (kind, object_name, owner_name);

  SELECT string_agg(
    format('%s:%s', manifest_target.kind, manifest_target.object_name),
    ', ' ORDER BY manifest_target.kind, manifest_target.object_name
  )
  INTO violation
  FROM br_153_relation_targets AS manifest_target
  LEFT JOIN pg_class AS relation
    ON relation.relname = manifest_target.object_name
   AND relation.relkind::text = manifest_target.kind
   AND relation.relnamespace = 'public'::regnamespace
  WHERE relation.oid IS NULL
     OR relation.relowner <> (
       SELECT oid FROM pg_roles WHERE rolname = current_user
     );
  IF violation IS NOT NULL THEN
    RAISE EXCEPTION 'catalog relation target mismatch: %', violation;
  END IF;

  SELECT string_agg(
    format(
      '%s:%s(%s)',
      manifest_target.kind,
      manifest_target.object_name,
      manifest_target.argument_types
    ),
    ', ' ORDER BY manifest_target.kind, manifest_target.object_name,
      manifest_target.argument_types
  )
  INTO violation
  FROM br_153_routine_targets AS manifest_target
  LEFT JOIN pg_proc AS routine
    ON routine.proname = manifest_target.object_name
   AND routine.prokind::text = manifest_target.kind
   AND oidvectortypes(routine.proargtypes) = manifest_target.argument_types
   AND routine.pronamespace = 'public'::regnamespace
  WHERE routine.oid IS NULL
     OR routine.proowner <> (
       SELECT oid FROM pg_roles WHERE rolname = current_user
     );
  IF violation IS NOT NULL THEN
    RAISE EXCEPTION 'catalog routine target mismatch: %', violation;
  END IF;

  SELECT string_agg(view_target.object_name, ', ' ORDER BY view_target.object_name)
  INTO violation
  FROM br_153_view_targets AS view_target
  LEFT JOIN br_153_relation_targets AS relation_target
    ON relation_target.kind = 'v'
   AND relation_target.object_name = view_target.object_name
  WHERE relation_target.object_name IS NULL;
  IF violation IS NOT NULL THEN
    RAISE EXCEPTION 'catalog view target mismatch: %', violation;
  END IF;

  -- Migration 152 is the immediate predecessor. Its new public objects are
  -- outside this sweep, so prove its security postconditions before touching
  -- any reviewed pre-152 object.
  SELECT string_agg(
    format('%s:%s', item->>'kind', item->>'name'),
    ', ' ORDER BY item->>'kind', item->>'name'
  )
  INTO violation
  FROM jsonb_array_elements(
    catalog_manifest->'predecessor_152'->'relations'
  ) AS item
  LEFT JOIN pg_class AS relation
    ON relation.relname = item->>'name'
   AND relation.relkind::text = item->>'kind'
   AND relation.relnamespace = 'public'::regnamespace
  WHERE relation.oid IS NULL
     OR relation.relowner <> (
       SELECT oid FROM pg_roles WHERE rolname = current_user
     )
     OR NOT relation.relrowsecurity
     OR has_table_privilege('anon', relation.oid, 'SELECT')
     OR has_table_privilege('authenticated', relation.oid, 'SELECT')
     OR has_any_column_privilege('anon', relation.oid, 'SELECT')
     OR has_any_column_privilege('authenticated', relation.oid, 'SELECT');
  IF violation IS NOT NULL THEN
    RAISE EXCEPTION 'migration 152 relation security mismatch: %', violation;
  END IF;

  SELECT string_agg(
    format('%s.%s', item->>'relation', item->>'name'),
    ', ' ORDER BY item->>'relation', item->>'name'
  )
  INTO violation
  FROM jsonb_array_elements(
    catalog_manifest->'predecessor_152'->'excluded_new_columns'
  ) AS item
  LEFT JOIN pg_class AS relation
    ON relation.relname = item->>'relation'
   AND relation.relnamespace = 'public'::regnamespace
  LEFT JOIN pg_attribute AS attribute
    ON attribute.attrelid = relation.oid
   AND attribute.attname = item->>'name'
   AND attribute.attnum > 0
   AND NOT attribute.attisdropped
  WHERE attribute.attrelid IS NULL;
  IF violation IS NOT NULL THEN
    RAISE EXCEPTION 'migration 152 column contract mismatch: %', violation;
  END IF;

  SELECT string_agg(
    format('%s(%s)', item->>'name', item->>'argument_types'),
    ', ' ORDER BY item->>'name', item->>'argument_types'
  )
  INTO violation
  FROM jsonb_array_elements(
    catalog_manifest->'predecessor_152'->'routines'
  ) AS item
  LEFT JOIN pg_proc AS routine
    ON routine.proname = item->>'name'
   AND routine.prokind::text = item->>'kind'
   AND oidvectortypes(routine.proargtypes) = item->>'argument_types'
   AND routine.pronamespace = 'public'::regnamespace
  WHERE routine.oid IS NULL
     OR routine.proowner <> (
       SELECT oid FROM pg_roles WHERE rolname = current_user
     )
     OR has_function_privilege('anon', routine.oid, 'EXECUTE')
     OR has_function_privilege('authenticated', routine.oid, 'EXECUTE');
  IF violation IS NOT NULL THEN
    RAISE EXCEPTION 'migration 152 routine security mismatch: %', violation;
  END IF;

  SELECT string_agg(value #>> '{}', ', ' ORDER BY value #>> '{}')
  INTO violation
  FROM jsonb_array_elements(
    catalog_manifest->'predecessor_152'->'normalized_relation_security'
  ) AS normalized(value)
  LEFT JOIN pg_class AS relation
    ON relation.relname = value #>> '{}'
   AND relation.relnamespace = 'public'::regnamespace
   AND relation.relkind IN ('r', 'p')
  WHERE relation.oid IS NULL
     OR relation.relowner <> (
       SELECT oid FROM pg_roles WHERE rolname = current_user
     )
     OR NOT relation.relrowsecurity
     OR has_table_privilege('anon', relation.oid, 'SELECT')
     OR has_table_privilege('authenticated', relation.oid, 'SELECT')
     OR has_any_column_privilege('anon', relation.oid, 'SELECT')
     OR has_any_column_privilege('authenticated', relation.oid, 'SELECT');
  IF violation IS NOT NULL THEN
    RAISE EXCEPTION 'migration 152 normalized relation mismatch: %', violation;
  END IF;

  SELECT string_agg(
    format('%s(%s)', item->>'name', item->>'argument_types'),
    ', ' ORDER BY item->>'name', item->>'argument_types'
  )
  INTO violation
  FROM jsonb_array_elements(
    catalog_manifest->'predecessor_152'->'normalized_routine_security'
  ) AS item
  LEFT JOIN pg_proc AS routine
    ON routine.proname = item->>'name'
   AND routine.prokind::text = item->>'kind'
   AND oidvectortypes(routine.proargtypes) = item->>'argument_types'
   AND routine.pronamespace = 'public'::regnamespace
  WHERE routine.oid IS NULL
     OR routine.proowner <> (
       SELECT oid FROM pg_roles WHERE rolname = current_user
     )
     OR has_function_privilege('anon', routine.oid, 'EXECUTE')
     OR has_function_privilege('authenticated', routine.oid, 'EXECUTE')
     OR NOT has_function_privilege('service_role', routine.oid, 'EXECUTE');
  IF violation IS NOT NULL THEN
    RAISE EXCEPTION 'migration 152 normalized routine mismatch: %', violation;
  END IF;

  SELECT concat_ws(
    '|',
    role.rolsuper::text,
    role.rolinherit::text,
    role.rolcreaterole::text,
    role.rolcreatedb::text,
    role.rolcanlogin::text,
    role.rolreplication::text,
    role.rolbypassrls::text,
    role.rolconnlimit::text,
    coalesce(role.rolvaliduntil::text, '<null>'),
    coalesce((
      SELECT string_agg(parent.rolname, ',' ORDER BY parent.rolname)
      FROM pg_auth_members AS membership
      JOIN pg_roles AS parent ON parent.oid = membership.roleid
      WHERE membership.member = role.oid
    ), '<none>')
  )
  INTO service_role_state_before
  FROM pg_roles AS role
  WHERE role.rolname = 'service_role';

  -- This rollback-scoped snapshot captures raw ACLs and every effective
  -- service privilege that the migration can disturb.
  CREATE TEMP TABLE br_153_service_acl_before (
    object_kind TEXT NOT NULL,
    object_oid OID NOT NULL,
    sub_id SMALLINT NOT NULL DEFAULT 0,
    schema_name TEXT NOT NULL,
    object_name TEXT NOT NULL,
    column_name TEXT,
    identity_arguments TEXT,
    routine_kind "char",
    privilege TEXT NOT NULL,
    allowed BOOLEAN NOT NULL,
    acl_before TEXT,
    PRIMARY KEY (object_kind, object_oid, sub_id, privilege)
  ) ON COMMIT DROP;

  INSERT INTO br_153_service_acl_before (
    object_kind, object_oid, schema_name, object_name,
    privilege, allowed, acl_before
  )
  SELECT
    'schema', namespace.oid, namespace.nspname, namespace.nspname,
    candidate.privilege,
    has_schema_privilege('service_role', namespace.oid, candidate.privilege),
    namespace.nspacl::text
  FROM pg_namespace AS namespace
  CROSS JOIN unnest(ARRAY['USAGE', 'CREATE']) AS candidate(privilege)
  WHERE namespace.nspname = 'public';

  INSERT INTO br_153_service_acl_before (
    object_kind, object_oid, schema_name, object_name,
    privilege, allowed, acl_before
  )
  SELECT
    'relation', relation.oid, namespace.nspname, relation.relname,
    candidate.privilege,
    has_table_privilege('service_role', relation.oid, candidate.privilege),
    relation.relacl::text
  FROM br_153_relation_targets AS manifest_target
  JOIN pg_class AS relation
    ON relation.relname = manifest_target.object_name
   AND relation.relkind::text = manifest_target.kind
   AND relation.relnamespace = 'public'::regnamespace
  JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
  CROSS JOIN unnest(ARRAY[
    'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE',
    'REFERENCES', 'TRIGGER', 'MAINTAIN'
  ]) AS candidate(privilege)
  WHERE manifest_target.kind IN ('r', 'p', 'v', 'm', 'f')
    AND (
      candidate.privilege <> 'MAINTAIN'
      OR manifest_target.kind IN ('r', 'p', 'm')
    );

  INSERT INTO br_153_service_acl_before (
    object_kind, object_oid, sub_id, schema_name, object_name, column_name,
    privilege, allowed, acl_before
  )
  SELECT
    'column', relation.oid, attribute.attnum,
    namespace.nspname, relation.relname, attribute.attname,
    candidate.privilege,
    has_column_privilege(
      'service_role', relation.oid, attribute.attnum, candidate.privilege
    ),
    attribute.attacl::text
  FROM br_153_relation_targets AS manifest_target
  JOIN pg_class AS relation
    ON relation.relname = manifest_target.object_name
   AND relation.relkind::text = manifest_target.kind
   AND relation.relnamespace = 'public'::regnamespace
  JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
  JOIN pg_attribute AS attribute
    ON attribute.attrelid = relation.oid
   AND attribute.attnum > 0
   AND NOT attribute.attisdropped
  CROSS JOIN unnest(ARRAY[
    'SELECT', 'INSERT', 'UPDATE', 'REFERENCES'
  ]) AS candidate(privilege)
  WHERE manifest_target.kind IN ('r', 'p', 'v', 'm', 'f');

  INSERT INTO br_153_service_acl_before (
    object_kind, object_oid, schema_name, object_name,
    privilege, allowed, acl_before
  )
  SELECT
    'sequence', relation.oid, namespace.nspname, relation.relname,
    candidate.privilege,
    has_sequence_privilege('service_role', relation.oid, candidate.privilege),
    relation.relacl::text
  FROM br_153_relation_targets AS manifest_target
  JOIN pg_class AS relation
    ON relation.relname = manifest_target.object_name
   AND relation.relkind = 'S'
   AND manifest_target.kind = 'S'
   AND relation.relnamespace = 'public'::regnamespace
  JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
  CROSS JOIN unnest(ARRAY['SELECT', 'USAGE', 'UPDATE']) AS candidate(privilege);

  INSERT INTO br_153_service_acl_before (
    object_kind, object_oid, schema_name, object_name,
    identity_arguments, routine_kind, privilege, allowed, acl_before
  )
  SELECT
    'routine', routine.oid, namespace.nspname, routine.proname,
    oidvectortypes(routine.proargtypes), routine.prokind, 'EXECUTE',
    has_function_privilege('service_role', routine.oid, 'EXECUTE'),
    routine.proacl::text
  FROM br_153_routine_targets AS manifest_target
  JOIN pg_proc AS routine
    ON routine.proname = manifest_target.object_name
   AND routine.prokind::text = manifest_target.kind
   AND oidvectortypes(routine.proargtypes) = manifest_target.argument_types
   AND routine.pronamespace = 'public'::regnamespace
  JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace;

  REVOKE ALL PRIVILEGES ON SCHEMA public FROM PUBLIC, anon, authenticated;

  FOR target IN
    SELECT relation.relname AS object_name, attribute.attname AS column_name
    FROM br_153_relation_targets AS manifest_target
    JOIN pg_class AS relation
      ON relation.relname = manifest_target.object_name
     AND relation.relkind::text = manifest_target.kind
     AND relation.relnamespace = 'public'::regnamespace
    JOIN pg_attribute AS attribute
      ON attribute.attrelid = relation.oid
     AND attribute.attnum > 0
     AND NOT attribute.attisdropped
    WHERE manifest_target.kind IN ('r', 'p')
    ORDER BY relation.relname, attribute.attnum
  LOOP
    EXECUTE format(
      'REVOKE ALL PRIVILEGES (%I) ON TABLE public.%I FROM PUBLIC, anon, authenticated',
      target.column_name,
      target.object_name
    );
  END LOOP;

  FOR target IN
    SELECT relation.relname AS object_name
    FROM br_153_relation_targets AS manifest_target
    JOIN pg_class AS relation
      ON relation.relname = manifest_target.object_name
     AND relation.relkind::text = manifest_target.kind
     AND relation.relnamespace = 'public'::regnamespace
    WHERE manifest_target.kind IN ('r', 'p')
    ORDER BY relation.relname
  LOOP
    EXECUTE format(
      'ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', target.object_name
    );
    EXECUTE format(
      'REVOKE ALL PRIVILEGES ON TABLE public.%I FROM PUBLIC, anon, authenticated',
      target.object_name
    );
  END LOOP;

  FOR target IN
    SELECT policy.polname AS policy_name, relation.relname AS object_name
    FROM pg_policy AS policy
    JOIN pg_class AS relation ON relation.oid = policy.polrelid
    JOIN br_153_relation_targets AS manifest_target
      ON manifest_target.object_name = relation.relname
     AND manifest_target.kind = relation.relkind::text
    WHERE relation.relnamespace = 'public'::regnamespace
    ORDER BY relation.relname, policy.polname
  LOOP
    EXECUTE format(
      'DROP POLICY %I ON public.%I', target.policy_name, target.object_name
    );
  END LOOP;

  FOR target IN
    SELECT relation.relname AS object_name
    FROM br_153_view_targets AS view_target
    JOIN pg_class AS relation
      ON relation.relname = view_target.object_name
     AND relation.relkind = 'v'
     AND relation.relnamespace = 'public'::regnamespace
    ORDER BY relation.relname
  LOOP
    EXECUTE format(
      'ALTER VIEW public.%I SET (security_invoker = true)', target.object_name
    );
  END LOOP;

  FOR target IN
    SELECT relation.relname AS object_name, relation.relkind::text AS kind
    FROM br_153_relation_targets AS manifest_target
    JOIN pg_class AS relation
      ON relation.relname = manifest_target.object_name
     AND relation.relkind::text = manifest_target.kind
     AND relation.relnamespace = 'public'::regnamespace
    WHERE manifest_target.kind IN ('v', 'm', 'f')
    ORDER BY relation.relname
  LOOP
    EXECUTE format(
      'REVOKE ALL PRIVILEGES ON TABLE public.%I FROM PUBLIC, anon, authenticated',
      target.object_name
    );
  END LOOP;

  FOR target IN
    SELECT relation.relname AS object_name, attribute.attname AS column_name
    FROM br_153_relation_targets AS manifest_target
    JOIN pg_class AS relation
      ON relation.relname = manifest_target.object_name
     AND relation.relkind::text = manifest_target.kind
     AND relation.relnamespace = 'public'::regnamespace
    JOIN pg_attribute AS attribute
      ON attribute.attrelid = relation.oid
     AND attribute.attnum > 0
     AND NOT attribute.attisdropped
    WHERE manifest_target.kind IN ('v', 'm', 'f')
    ORDER BY relation.relname, attribute.attnum
  LOOP
    EXECUTE format(
      'REVOKE ALL PRIVILEGES (%I) ON TABLE public.%I FROM PUBLIC, anon, authenticated',
      target.column_name,
      target.object_name
    );
  END LOOP;

  FOR target IN
    SELECT relation.relname AS object_name
    FROM br_153_relation_targets AS manifest_target
    JOIN pg_class AS relation
      ON relation.relname = manifest_target.object_name
     AND relation.relkind = 'S'
     AND manifest_target.kind = 'S'
     AND relation.relnamespace = 'public'::regnamespace
    ORDER BY relation.relname
  LOOP
    EXECUTE format(
      'REVOKE ALL PRIVILEGES ON SEQUENCE public.%I FROM PUBLIC, anon, authenticated',
      target.object_name
    );
  END LOOP;

  FOR target IN
    SELECT
      routine.proname AS object_name,
      routine.prokind,
      oidvectortypes(routine.proargtypes) AS identity_arguments
    FROM br_153_routine_targets AS manifest_target
    JOIN pg_proc AS routine
      ON routine.proname = manifest_target.object_name
     AND routine.prokind::text = manifest_target.kind
     AND oidvectortypes(routine.proargtypes) = manifest_target.argument_types
     AND routine.pronamespace = 'public'::regnamespace
    ORDER BY routine.proname, oidvectortypes(routine.proargtypes)
  LOOP
    object_kind := CASE
      WHEN target.prokind = 'p' THEN 'PROCEDURE' ELSE 'FUNCTION'
    END;
    EXECUTE format(
      'REVOKE ALL PRIVILEGES ON %s public.%I(%s) FROM PUBLIC, anon, authenticated',
      object_kind,
      target.object_name,
      target.identity_arguments
    );
  END LOOP;

  ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL PRIVILEGES ON TABLES FROM PUBLIC, anon, authenticated;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL PRIVILEGES ON SEQUENCES FROM PUBLIC, anon, authenticated;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL PRIVILEGES ON FUNCTIONS FROM PUBLIC, anon, authenticated;
  -- Do not alter global function defaults. PostgreSQL's built-in PUBLIC
  -- EXECUTE remains on future routines, but revoked schema USAGE makes those
  -- routines uncallable by anon/authenticated.

  -- Preserve exactly the effective service authority captured above. Direct
  -- grants are added only where removing PUBLIC would otherwise narrow it.
  FOR target IN
    SELECT *
    FROM br_153_service_acl_before AS snapshot
    WHERE snapshot.object_kind = 'schema'
      AND snapshot.allowed
      AND NOT has_schema_privilege(
        'service_role', snapshot.object_oid, snapshot.privilege
      )
  LOOP
    EXECUTE format(
      'GRANT %s ON SCHEMA %I TO service_role',
      target.privilege,
      target.schema_name
    );
  END LOOP;

  FOR target IN
    SELECT *
    FROM br_153_service_acl_before AS snapshot
    WHERE snapshot.object_kind = 'relation'
      AND snapshot.allowed
      AND NOT has_table_privilege(
        'service_role', snapshot.object_oid, snapshot.privilege
      )
  LOOP
    EXECUTE format(
      'GRANT %s ON TABLE %I.%I TO service_role',
      target.privilege,
      target.schema_name,
      target.object_name
    );
  END LOOP;

  FOR target IN
    SELECT *
    FROM br_153_service_acl_before AS snapshot
    WHERE snapshot.object_kind = 'column'
      AND snapshot.allowed
      AND NOT has_column_privilege(
        'service_role', snapshot.object_oid, snapshot.sub_id, snapshot.privilege
      )
  LOOP
    EXECUTE format(
      'GRANT %s (%I) ON TABLE %I.%I TO service_role',
      target.privilege,
      target.column_name,
      target.schema_name,
      target.object_name
    );
  END LOOP;

  FOR target IN
    SELECT *
    FROM br_153_service_acl_before AS snapshot
    WHERE snapshot.object_kind = 'sequence'
      AND snapshot.allowed
      AND NOT has_sequence_privilege(
        'service_role', snapshot.object_oid, snapshot.privilege
      )
  LOOP
    EXECUTE format(
      'GRANT %s ON SEQUENCE %I.%I TO service_role',
      target.privilege,
      target.schema_name,
      target.object_name
    );
  END LOOP;

  FOR target IN
    SELECT *
    FROM br_153_service_acl_before AS snapshot
    WHERE snapshot.object_kind = 'routine'
      AND snapshot.allowed
      AND NOT has_function_privilege(
        'service_role', snapshot.object_oid, snapshot.privilege
      )
  LOOP
    object_kind := CASE
      WHEN target.routine_kind = 'p' THEN 'PROCEDURE' ELSE 'FUNCTION'
    END;
    EXECUTE format(
      'GRANT EXECUTE ON %s %I.%I(%s) TO service_role',
      object_kind,
      target.schema_name,
      target.object_name,
      target.identity_arguments
    );
  END LOOP;

  SELECT string_agg(
    format(
      '%s:%s:%s:%s',
      snapshot.object_kind,
      snapshot.object_name,
      coalesce(snapshot.column_name, '-'),
      snapshot.privilege
    ),
    ', ' ORDER BY snapshot.object_kind, snapshot.object_name,
      snapshot.sub_id, snapshot.privilege
  )
  INTO difference
  FROM br_153_service_acl_before AS snapshot
  WHERE snapshot.allowed IS DISTINCT FROM CASE snapshot.object_kind
    WHEN 'schema' THEN has_schema_privilege(
      'service_role', snapshot.object_oid, snapshot.privilege
    )
    WHEN 'relation' THEN has_table_privilege(
      'service_role', snapshot.object_oid, snapshot.privilege
    )
    WHEN 'column' THEN has_column_privilege(
      'service_role', snapshot.object_oid, snapshot.sub_id, snapshot.privilege
    )
    WHEN 'sequence' THEN has_sequence_privilege(
      'service_role', snapshot.object_oid, snapshot.privilege
    )
    WHEN 'routine' THEN has_function_privilege(
      'service_role', snapshot.object_oid, snapshot.privilege
    )
    ELSE NULL
  END;
  IF difference IS NOT NULL THEN
    RAISE EXCEPTION 'service_role effective privilege changed: %', difference;
  END IF;

  SELECT concat_ws(
    '|',
    role.rolsuper::text,
    role.rolinherit::text,
    role.rolcreaterole::text,
    role.rolcreatedb::text,
    role.rolcanlogin::text,
    role.rolreplication::text,
    role.rolbypassrls::text,
    role.rolconnlimit::text,
    coalesce(role.rolvaliduntil::text, '<null>'),
    coalesce((
      SELECT string_agg(parent.rolname, ',' ORDER BY parent.rolname)
      FROM pg_auth_members AS membership
      JOIN pg_roles AS parent ON parent.oid = membership.roleid
      WHERE membership.member = role.oid
    ), '<none>')
  )
  INTO service_role_state_after
  FROM pg_roles AS role
  WHERE role.rolname = 'service_role';
  IF service_role_state_after IS DISTINCT FROM service_role_state_before THEN
    RAISE EXCEPTION 'service_role BYPASSRLS or membership authority changed';
  END IF;

  SELECT format('%s has %s on schema public', client.role_name, grant_name)
  INTO violation
  FROM (VALUES ('anon'), ('authenticated')) AS client(role_name)
  CROSS JOIN (VALUES ('USAGE'), ('CREATE')) AS candidate(grant_name)
  WHERE has_schema_privilege(
    client.role_name, 'public', candidate.grant_name
  )
  LIMIT 1;
  IF violation IS NOT NULL THEN
    RAISE EXCEPTION 'client privilege revoke verification failed: %', violation;
  END IF;

  SELECT format(
    '%s has %s on public.%I',
    client.role_name,
    candidate.grant_name,
    relation.relname
  )
  INTO violation
  FROM pg_class AS relation
  CROSS JOIN (VALUES ('anon'), ('authenticated')) AS client(role_name)
  CROSS JOIN (VALUES
    ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE'), ('TRUNCATE'),
    ('REFERENCES'), ('TRIGGER'), ('MAINTAIN')
  ) AS candidate(grant_name)
  WHERE relation.relnamespace = 'public'::regnamespace
    AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
    AND (
      candidate.grant_name <> 'MAINTAIN'
      OR relation.relkind IN ('r', 'p', 'm')
    )
    AND NOT EXISTS (
      SELECT 1
      FROM br_153_provider_relation_exceptions AS provider
      WHERE provider.kind = relation.relkind::text
        AND provider.object_name = relation.relname
        AND provider.owner_name = pg_get_userbyid(relation.relowner)
    )
    AND has_table_privilege(
      client.role_name, relation.oid, candidate.grant_name
    )
  LIMIT 1;
  IF violation IS NOT NULL THEN
    RAISE EXCEPTION 'client privilege revoke verification failed: %', violation;
  END IF;

  SELECT format(
    '%s has column %s on public.%I',
    client.role_name,
    candidate.grant_name,
    relation.relname
  )
  INTO violation
  FROM pg_class AS relation
  CROSS JOIN (VALUES ('anon'), ('authenticated')) AS client(role_name)
  CROSS JOIN (VALUES
    ('SELECT'), ('INSERT'), ('UPDATE'), ('REFERENCES')
  ) AS candidate(grant_name)
  WHERE relation.relnamespace = 'public'::regnamespace
    AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
    AND NOT EXISTS (
      SELECT 1
      FROM br_153_provider_relation_exceptions AS provider
      WHERE provider.kind = relation.relkind::text
        AND provider.object_name = relation.relname
        AND provider.owner_name = pg_get_userbyid(relation.relowner)
    )
    AND has_any_column_privilege(
      client.role_name, relation.oid, candidate.grant_name
    )
  LIMIT 1;
  IF violation IS NOT NULL THEN
    RAISE EXCEPTION 'client privilege revoke verification failed: %', violation;
  END IF;

  SELECT format(
    '%s has %s on sequence public.%I',
    client.role_name,
    candidate.grant_name,
    relation.relname
  )
  INTO violation
  FROM pg_class AS relation
  CROSS JOIN (VALUES ('anon'), ('authenticated')) AS client(role_name)
  CROSS JOIN (VALUES ('SELECT'), ('USAGE'), ('UPDATE')) AS candidate(grant_name)
  WHERE relation.relnamespace = 'public'::regnamespace
    AND relation.relkind = 'S'
    AND has_sequence_privilege(
      client.role_name, relation.oid, candidate.grant_name
    )
  LIMIT 1;
  IF violation IS NOT NULL THEN
    RAISE EXCEPTION 'client privilege revoke verification failed: %', violation;
  END IF;

  SELECT format(
    '%s has EXECUTE on public.%I(%s)',
    client.role_name,
    routine.proname,
    oidvectortypes(routine.proargtypes)
  )
  INTO violation
  FROM pg_proc AS routine
  CROSS JOIN (VALUES ('anon'), ('authenticated')) AS client(role_name)
  WHERE routine.pronamespace = 'public'::regnamespace
    AND (
      EXISTS (
        SELECT 1
        FROM br_153_routine_targets AS manifest_target
        WHERE manifest_target.kind = routine.prokind::text
          AND manifest_target.object_name = routine.proname
          AND manifest_target.argument_types = oidvectortypes(routine.proargtypes)
      )
      OR EXISTS (
        SELECT 1
        FROM jsonb_array_elements(
          catalog_manifest->'predecessor_152'->'routines'
        ) AS predecessor(item)
        WHERE item->>'kind' = routine.prokind::text
          AND item->>'name' = routine.proname
          AND item->>'argument_types' = oidvectortypes(routine.proargtypes)
      )
    )
    AND has_function_privilege(client.role_name, routine.oid, 'EXECUTE')
  LIMIT 1;
  IF violation IS NOT NULL THEN
    RAISE EXCEPTION 'client privilege revoke verification failed: %', violation;
  END IF;

  SELECT string_agg(relation.relname, ', ' ORDER BY relation.relname)
  INTO violation
  FROM pg_class AS relation
  JOIN br_153_relation_targets AS manifest_target
    ON manifest_target.kind = relation.relkind::text
   AND manifest_target.object_name = relation.relname
  WHERE relation.relnamespace = 'public'::regnamespace
    AND relation.relkind IN ('r', 'p')
    AND NOT relation.relrowsecurity;
  IF violation IS NOT NULL THEN
    RAISE EXCEPTION 'public app-owned table remains without RLS: %', violation;
  END IF;

  SELECT string_agg(relation.relname, ', ' ORDER BY relation.relname)
  INTO violation
  FROM pg_policy AS policy
  JOIN pg_class AS relation ON relation.oid = policy.polrelid
  JOIN br_153_relation_targets AS manifest_target
    ON manifest_target.kind = relation.relkind::text
   AND manifest_target.object_name = relation.relname
  WHERE relation.relnamespace = 'public'::regnamespace;
  IF violation IS NOT NULL THEN
    RAISE EXCEPTION 'public app-owned table retains a client policy: %', violation;
  END IF;

  SELECT string_agg(relation.relname, ', ' ORDER BY relation.relname)
  INTO violation
  FROM pg_class AS relation
  JOIN br_153_relation_targets AS manifest_target
    ON manifest_target.kind = 'v'
   AND manifest_target.object_name = relation.relname
  WHERE relation.relnamespace = 'public'::regnamespace
    AND relation.relkind = 'v'
    AND NOT coalesce(
      relation.reloptions @> ARRAY['security_invoker=true'], false
    );
  IF violation IS NOT NULL THEN
    RAISE EXCEPTION 'public app-owned view remains security definer: %', violation;
  END IF;

  SELECT string_agg(
    format('%s -> %s.%s', view_relation.relname, dependency_namespace.nspname,
      dependency_relation.relname),
    ', ' ORDER BY view_relation.relname, dependency_namespace.nspname,
      dependency_relation.relname
  )
  INTO violation
  FROM pg_class AS view_relation
  JOIN br_153_relation_targets AS manifest_target
    ON manifest_target.kind = 'v'
   AND manifest_target.object_name = view_relation.relname
  JOIN pg_rewrite AS rewrite ON rewrite.ev_class = view_relation.oid
  JOIN pg_depend AS dependency
    ON dependency.classid = 'pg_rewrite'::regclass
   AND dependency.objid = rewrite.oid
   AND dependency.refclassid = 'pg_class'::regclass
  JOIN pg_class AS dependency_relation
    ON dependency_relation.oid = dependency.refobjid
  JOIN pg_namespace AS dependency_namespace
    ON dependency_namespace.oid = dependency_relation.relnamespace
  WHERE view_relation.relnamespace = 'public'::regnamespace
    AND view_relation.relkind = 'v'
    AND dependency_relation.oid <> view_relation.oid
    AND dependency_relation.relkind IN ('r', 'p', 'v', 'm', 'f')
    AND NOT has_table_privilege(
      'service_role', dependency_relation.oid, 'SELECT'
    );
  IF violation IS NOT NULL THEN
    RAISE EXCEPTION 'service_role cannot read security-invoker view dependency: %',
      violation;
  END IF;
END
$migration$;
