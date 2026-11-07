# Supabase Migrations

This project uses Supabase for the database. Migrations are stored in `../sql/` for historical reasons.

## Running Migrations

Apply `backend/sql` only through `scripts/apply_sql_migrations.py`, normally via
`scripts/deploy-backend-release.sh`. The runner owns the transaction, advisory
lock, immutable ledger, and any explicit migration approval.

Direct SQL-file execution and Dashboard-pasted migrations are retired. In
particular, default `psql -f` continues after an error and cannot enforce the
atomic approval contract of `153_public_data_api_rls_lockdown.sql`.

## Creating New Migrations

```bash
# Discover the current CLI shape first, then create the mirror.
supabase --help
supabase migration new your_migration_name
```

Follow the existing naming convention: `NNN_description.sql`

## Migration History

| # | Name | Description |
|---|------|-------------|
| 001-030 | Core schema | Users, rides, segments, tiles, etc. |
| 031 | points_period | ~~Points earning during pre-TGE~~ (tables dropped by 089) |
| 032 | supply_emissions | Token supply and halving |
| 033 | vault_economics | Vault staking and distributions |
| 034-035 | swanny/local_legend | Local Legend elections |
| 036 | vault_completion_event | VAULT_COMPLETION event type |
| ... | ... | ... |
| 089 | remove_points_system | **Drops points tables** (`wallet_points`, `points_events`, `points_config`, `tge_conversions`). Queued for execution when Supabase resumes (paused until April 9, 2026). |
