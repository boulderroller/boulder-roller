# Strava file-import-only cutover

This runbook retires Boulder Roller’s Strava OAuth sync without deleting any
Strava-derived ride, file, connection row, or import-provenance row. It is the
operator procedure for `boulderroller-v2-qht6b`.

The code delivery does **not** authorize or perform this production cutover.
Until an operator completes one reviewed production path below, the local
cutover and admin post-state remain unverified. Provider revocation and remote
webhook state are separately unverified unless the provider-revoke path can run
to completion.

## Outcome and hard boundaries

Both cutover paths have these observable outcomes:

1. The deployed server reports `integration_mode=file_import_only` and
   `sync_enabled=false`, so new OAuth, imports, backfill, webhook queueing,
   residual Strava NATS/Celery work, and admin re-subscription are fail-closed.
2. Local active connections and active webhook rows are zero while total
   connection rows, `strava_imported_activities`, and Strava-origin rides are
   unchanged.

Use the default **provider-revoke** path while the Strava application still
accepts its client credentials. It adds two provider outcomes: Strava reports
no webhook subscription, and Strava acknowledges idempotent revoke requests for
both stored token columns on every `strava_connections` row, including rows
already marked inactive.

Use **local-only** only when the provider application is already dead and no
longer permits subscription inventory, webhook deletion, or token revocation.
`--local-only` makes no Strava API request, does not require
`STRAVA_CLIENT_SECRET`, and marks only the exact reviewed local connection and
webhook rows inactive. Its output leaves provider subscription and revocation
fields `null`; it is not evidence that Strava deleted a webhook or revoked a
grant.

Do not delete or truncate `strava_connections`, `strava_imported_activities`,
`rides`, storage objects, or imported files. Do not blank stored tokens. The
foreign key from `strava_imported_activities` to `strava_connections` cascades
on delete, so deleting a connection would violate the preservation directive.

Revocation is forward-only. Do not “roll back” by setting `is_active=true`,
registering a new webhook, or restoring OAuth. A future return to Strava sync
would require new product ratification and fresh athlete authorization.

## Why provider-revoke includes every stored connection

Historical `is_active=false` is not proof that Strava revoked the grant. The
legacy rider disconnect path could mark a row inactive after a failed provider
request. A successful provider refresh followed by a failed local token update
can also leave a stale stored refresh token while the stored access token is
still live. The cutover therefore reads every stored connection and calls
Strava’s current recommended `POST /oauth/revoke` endpoint with both its stored
refresh and access token. Strava documents a `200` response whether a token was
revoked now or was already absent, so repeating both calls is safe.

Local-only does not load either stored token column. It inventories connection
IDs and active state only, then updates the exact active rows bound into its
reviewed plan.

Provider references:

- [Strava deauthorization](https://developers.strava.com/docs/authentication/#deauthorization)
- [Strava webhook subscriptions](https://developers.strava.com/docs/webhooks/#subscriptions)

## 1. Preflight: deploy the server fence

Complete these before the production inventory. All API and worker instances
must run the reviewed cutover code; an old instance can still accept OAuth or
process queued Strava events.

1. Set `STRAVA_SYNC_ENABLED=false` in the deployed server and worker
   environment. Keep `STRAVA_CLIENT_ID` available to the one-time operator
   process. The provider-revoke path also requires `STRAVA_CLIENT_SECRET`; the
   local-only path deliberately does not. Never put a provider secret on the
   command line.
2. Deploy the reviewed commit normally. Do not bypass CI, release gates, or the
   usual deployed-SHA verification.
3. In the authenticated admin Strava panel, confirm:
   - integration mode is **File imports only**;
   - OAuth, webhook ingest, backfill, and re-subscription are shown disabled;
   - no **Register Webhook** action is offered.
4. Confirm no old API or worker replica remains. The updated API acknowledges
   new webhook deliveries as ignored; updated NATS workers ACK residual Strava
   messages without importing them; and legacy Celery webhook/backfill jobs
   return a file-import-only skip before touching queue or provider state.

If the admin response says `sync_enabled=true`, stop. Do not inventory or
execute the cutover against that deployment.

## 2. Production dry-run: read-only first

Run from `backend/` in the approved production operator environment. The
service-role key and Strava application credentials come only from managed
environment variables:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY` (or the legacy `SUPABASE_SERVICE_ROLE_KEY` alias)
- `STRAVA_CLIENT_ID`
- `STRAVA_CLIENT_SECRET` (provider-revoke only)
- explicit `STRAVA_SYNC_ENABLED=false`

The Supabase credential must positively identify server authority: either a
modern `sb_secret_...` secret or a legacy JWT whose `role` claim is exactly
`service_role`. The script rejects anon, publishable, authenticated, malformed,
and opaque keys before constructing a client. Do not proceed with a key that
could return an RLS-filtered subset of the grant inventory.

The default dry-run reads Supabase and performs Strava’s read-only subscription
inventory. It sends no provider POST/DELETE and performs no database update.

```bash
python3 scripts/strava_file_import_cutover.py --dry-run
```

If the provider application is already dead, build the local-only plan instead:

```bash
python3 scripts/strava_file_import_cutover.py --dry-run --local-only
```

This variant reads Supabase only. It does not construct a Strava client, does
not require `STRAVA_CLIENT_SECRET`, and makes no Strava API request. Its plan
sets `cutover_mode=local_only`, `strava_api_contact_planned=false`, and
`provider_subscription_ids=null` so absence of provider evidence cannot be
mistaken for a zero-subscription inventory.

Save the complete JSON output in the approved private operations record. It is
redacted: it contains counts, subscription IDs, the target host, application
ID, and plan digest—never wallets, athlete names, refresh tokens, access tokens,
the service-role key, or the Strava client secret. HTTP client request logs also
redact the entire `client_secret` query value.

Before any write, review and record:

- `stored_connection_count`;
- `active_connection_count` and `inactive_connection_count`;
- `cutover_mode` and `strava_api_contact_planned`;
- local subscription counts/IDs and, for provider-revoke, provider
  subscription IDs;
- `imported_activity_link_count`;
- `strava_origin_ride_count`;
- `revoke_request_count_without_checkpoint` (two calls per stored row for
  provider-revoke, zero for local-only);
- `target_supabase_host` and `strava_application_id`;
- `plan_sha256`.

Stop for review if the Supabase host or Strava application ID is unexpected,
if Strava reports more than its documented single application subscription, or
if the preservation counts cannot be explained. In provider-revoke mode, a
local/provider subscription ID mismatch is not silently ignored: the reviewed
plan will delete every provider-reported subscription and then mark every local
active row inactive.
For local-only, provider state is deliberately unknown. A digest from one mode
cannot authorize the other because `cutover_mode` is part of the plan hash.

## 3. Execute the exact reviewed plan

Run a fresh dry-run immediately before execution. Use its exact values below;
do not reuse an older digest. The target URL is the full normalized
`SUPABASE_URL`, not only its project ref.

### Provider-revoke

```bash
export STRAVA_SYNC_ENABLED=false
export STRAVA_CUTOVER_PLAN_SHA="replace-with-reviewed-plan-sha256"
export STRAVA_CUTOVER_SUPABASE_URL="https://replace-with-reviewed-project.supabase.co"
export STRAVA_CUTOVER_APP_ID="replace-with-reviewed-strava-application-id"
export STRAVA_CUTOVER_CHECKPOINT="/absolute/private/path/strava-cutover-checkpoint.json"

python3 scripts/strava_file_import_cutover.py \
  --execute \
  --confirm FILE_IMPORT_ONLY_REVOKE_STRAVA_GRANTS \
  --expected-plan-sha256 "$STRAVA_CUTOVER_PLAN_SHA" \
  --expected-supabase-url "$STRAVA_CUTOVER_SUPABASE_URL" \
  --expected-strava-application-id "$STRAVA_CUTOVER_APP_ID" \
  --checkpoint-file "$STRAVA_CUTOVER_CHECKPOINT"
```

Use one approved absolute checkpoint path for the whole cutover and every
retry. Keep it outside the repository in private operator storage; the script
creates it mode `0600` and rejects a symlink or a file accessible by group or
others. It contains target identity, connection IDs, token fingerprints, and
provider/local completion bits—never access tokens, refresh tokens, wallets,
athlete names, or service credentials. Do not run concurrent operators against
the same cutover.

Execution re-reads and rejects plan drift before mutation. It then:

1. deletes every provider-reported webhook subscription and verifies provider
   absence;
2. marks the exact local webhook rows inactive only after provider absence;
3. calls `POST /oauth/revoke` sequentially for both stored tokens on every
   connection;
4. durably checkpoints provider acknowledgement after Strava returns `200` for
   both calls, then marks the exact connection `is_active=false` and
   checkpoints that local result;
5. skips already acknowledged provider calls on a retry, then re-reads all
   postconditions and preservation counts.

The revoke call retries Strava `503` and transport failures at most three
times. A `429`, `401`, exhausted transport/`503`, or other provider `5xx` stops
the grant loop immediately so later quota is not burned. A rerun with a fresh
dry-run digest and the same checkpoint resumes at the first unacknowledged
grant. `400` fails only that row and leaves it active. The script never uses the
legacy disconnect or admin webhook-delete paths.

### Local-only fallback for a dead provider application

Run a fresh `--dry-run --local-only`, review that exact local-only plan, and
use its digest. The execution retains the same sync fence, confirmation, plan
digest, Supabase target, and Strava application-ID gates:

```bash
export STRAVA_SYNC_ENABLED=false
export STRAVA_CUTOVER_PLAN_SHA="replace-with-reviewed-local-only-plan-sha256"
export STRAVA_CUTOVER_SUPABASE_URL="https://replace-with-reviewed-project.supabase.co"
export STRAVA_CUTOVER_APP_ID="replace-with-reviewed-strava-application-id"

python3 scripts/strava_file_import_cutover.py \
  --execute \
  --local-only \
  --confirm FILE_IMPORT_ONLY_DISABLE_LOCAL_STRAVA_ROWS \
  --expected-plan-sha256 "$STRAVA_CUTOVER_PLAN_SHA" \
  --expected-supabase-url "$STRAVA_CUTOVER_SUPABASE_URL" \
  --expected-strava-application-id "$STRAVA_CUTOVER_APP_ID"
```

Local-only does not accept a provider-revoke plan digest and does not use a
provider checkpoint because it makes no external mutation. Before its first
write, it rebuilds the local-only plan and rejects any drift. It then marks the
exact planned active webhook rows and active connection rows inactive, re-reads
all local postconditions, and verifies that total connection, imported-link,
and Strava-origin ride counts did not change. It never constructs the Strava
HTTP client, loads stored token columns, or sends a request to Strava.

## 4. Verify the outcome

Both execution paths exit zero only when their JSON reports all of the
following:

- `success=true`;
- `failed_connection_count=0`;
- `remaining_local_subscription_count=0`;
- `remaining_active_connection_count=0`;
- `stored_connection_count_before` equals
  `stored_connection_count_after`;
- `imported_activity_links_before` equals
  `imported_activity_links_after`;
- `strava_origin_rides_before` equals `strava_origin_rides_after`.

Provider-revoke must additionally report `strava_api_contacted=true`,
`connections_revoke_acknowledged` equal to `stored_connection_count_before`,
and `remaining_provider_subscription_count=0`.

Local-only must report `cutover_mode=local_only`,
`strava_api_contacted=false`, `connections_revoke_acknowledged=null`,
`provider_subscriptions_deleted=null`, and
`remaining_provider_subscription_count=null`. Those `null` values preserve the
truth that provider state was not queried or changed.

Run the dry-run again in the same mode with the same production environment:

```bash
# Provider-revoke verification
python3 scripts/strava_file_import_cutover.py --dry-run

# Local-only verification
python3 scripts/strava_file_import_cutover.py --dry-run --local-only
```

The second inventory must show the same stored/imported/ride totals, zero
active connections, and zero local subscriptions. Provider-revoke must also
show zero provider subscriptions. Local-only continues to report provider
inventory as skipped, not zero. All stored connections remain present and are
shown inactive by directive.

Finally refresh the admin panel. A complete cutover is `HEALTHY` in
`file_import_only` mode with zero active local grants, no active local
subscription, and no cutover alert. This panel does not convert local-only into
provider revocation evidence. If the backing state cannot be read, it reports
`WARNING`, labels the cutover state unavailable, and omits database-backed
counts rather than treating unknown state as zero. Record the execution output
and the post-cutover admin snapshot as separate evidence. Neither one alone
substitutes for the other.

## 5. Forward recovery after a nonzero exit

Do not reverse confirmed work.

- **Webhook deletion not confirmed:** the script stops before revoking grants
  and does not mark local subscription rows inactive. Resolve provider access,
  run a new dry-run, review the new digest, and execute again.
- **Some token revocations fail:** successfully acknowledged rows remain
  inactive; failed rows remain active. Run a new dry-run and execute its new
  digest with the same checkpoint. Confirmed token pairs are skipped; the next
  unacknowledged row continues forward. Strava’s `200`-for-absent contract also
  keeps a repeated call safe if acknowledgement preceded a checkpoint write.
- **Provider revoke succeeds but the local update fails:** the row may still
  look active. The result records the provider acknowledgement separately from
  the failed local mark. The checkpoint preserves the provider result, so a
  rerun skips those provider calls and retries the exact local update.
- **Rate limit, provider auth, or provider outage:** stop at the first global
  halt. Preserve the checkpoint, wait for quota or repair credentials/provider
  access, run a new dry-run, review its digest, and execute with the same
  checkpoint. Do not start over with a new checkpoint path.
- **Provider application is already dead:** do not keep retrying an application
  that can no longer authenticate or manage its subscription. Run a fresh
  `--dry-run --local-only`, review that plan and its explicitly unknown provider
  state, then execute only that exact local-only digest. Do not describe this as
  provider revocation.
- **Local-only database update fails:** some exact rows may already be inactive.
  Run a fresh `--dry-run --local-only`, review the new digest, and rerun it.
  Updates to `is_active=false` are idempotent; no provider call or data deletion
  is introduced on retry.
- **Counts or targets drift:** stop. Investigate the new connection, import,
  ride, subscription, Supabase target, or application identity before making
  another write.

Never recover by deleting data, weakening the server fence, reactivating a
connection, or registering a replacement webhook.
