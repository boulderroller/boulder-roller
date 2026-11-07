# Backups to Cloudflare R2

Bead `boulderroller-v2-m6rs7`. Production Postgres and Supabase Storage are
copied from the droplet to the private R2 bucket `boulderroller-backups`. The
bucket deletes every object after 30 days, so the freshness alert below is what
stops a silent outage from emptying it.

## What runs (droplet cron, UTC: `/etc/cron.d/boulder-backups`)

| When | Script | What it does |
|---|---|---|
| 03:17 daily | `backup-db.sh` | `pg_dump` (custom format) with a `postgres:<major>-alpine` client that matches the server's major version, read back with `pg_restore --list`, uploaded to `db/YYYY/MM/boulder-<stamp>-pg<major>.dump` plus `.sha256` |
| 04:23 Mondays | `backup-storage.sh` | every Storage object (bucket `ride-uploads`: ride files and media) downloaded and checked against Storage's sizes, uploaded to `storage/YYYYMMDD/` with `manifest.json` |
| 05:41, 1st of month | `restore-test.sh` | the restore test below, against the newest dump |
| hourly at :09 | `check-freshness.sh` | alerts if the newest dump is over 48 h old or the newest Storage copy over 8 days |

Logs: `/var/log/boulder-backup.log`. Failures raise `BoulderBackupFailed`, and
stale backups raise `BoulderBackupStale`. Both go to the droplet's Alertmanager,
which sends them to Telegram, and both resolve when a later run succeeds.

The dump leaves out the schemas Supabase manages and every new project
recreates: `auth`, which is empty because sign-in is Privy, `storage`, whose
files the weekly copy holds, `realtime`, `vault`, `graphql` and
`graphql_public`. Owners and grants are left out too (`--no-owner
--no-privileges`).

## Credentials

- R2: `~/.config/boulder-r2` on Tim's Mac (`R2_ACCESS_KEY_ID`,
  `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT`, `R2_BUCKET`). The installer copies it
  to `/root/.secrets/r2.env` on the droplet with mode 600.
- Database and Storage: read at run time from `/root/boulder-repo/.env`
  (`DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`). Once that file is
  updated after a password or key rotation, the backups need no change.
- No script prints a credential. Values reach containers as `docker run -e NAME`.

## Install or update (from the Mac)

    scripts/backup/install.sh            # credentials, scripts, cron, then a check
    scripts/backup/install.sh --run-now  # also one backup, restore test, Storage copy

The installer copies the scripts to `/root/bin/boulder-backup/` and finishes
with `backup-db.sh --check`, which lists the bucket and runs a schema-only dump
to `/dev/null`. To change a script, edit it here and run the installer again.

## Restore test (scratch database, never production)

    /root/bin/boulder-backup/restore-test.sh                         # newest dump
    /root/bin/boulder-backup/restore-test.sh db/2026/10/<name>.dump  # a given dump

From the Mac with Docker running, the same script works with
`R2_ENV_FILE=~/.config/boulder-r2 scripts/backup/restore-test.sh`.

It downloads the dump and checks its SHA-256, then starts a throwaway
`postgis/postgis:<major>-3.5-alpine` container with no published port. It
creates an empty database from `template0` along with Supabase's role names,
runs `pg_restore`, and compares every table's row count with the rows in the
archive's own COPY data. It passes only if all of them match; tables an
extension owns, such as PostGIS's `spatial_ref_sys`, may only grow, because
`CREATE EXTENSION` refills them. Restore errors outside the data, such as the
Supabase-only `supabase_vault` extension, are listed but are not failures. The
container and files are removed afterwards.

First run, 21 Oct 2026: a 33 MB dump of 254 tables restored in 34 s with all
503,319 rows present, and the Storage copy held 189 objects (69.8 MB).

## Real recovery, in outline

1. Pick a dump: `rclone lsf -R r2:boulderroller-backups/db`. Each night's dump
   covers the whole day.
2. Restore into a fresh Supabase project, or into the existing one after
   review, with `pg_restore --no-owner --no-privileges -d <target-url> <dump>`
   using a client of the dump's major version.
3. Re-upload Storage from the matching `storage/YYYYMMDD/ride-uploads/` folder
   with the Storage API, or with `rclone` against Supabase's S3 endpoint.
4. Point `/root/boulder-repo/.env` at the target and recreate the api, indexer
   and keeper containers.
