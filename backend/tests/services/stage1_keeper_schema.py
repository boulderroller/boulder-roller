"""Whole relevant migrations over the declared pre-152 legacy predecessor.

The repository has no complete initial users/rides schema. Reuse its deletion
runtime predecessor for those unrelated legacy surfaces; replace every keeper
source relation with its real migration, including constraints and triggers.
"""
from pathlib import Path

from tests.sql.test_account_deletion_migration_runtime import _bootstrap_pre_152

BACKEND = Path(__file__).parents[2]
MIGRATIONS = """
009_ride_metrics.sql
015_rides_status.sql
024_pattern_tables.sql
028_indexed_vaults.sql
033_vault_economics.sql
034_swanny_system.sql
035_swanny_local_legend.sql
040_epoch_state.sql
045_ride_processing_phases.sql
047_full_leaderboard.sql
048_time_validation.sql
052_leaderboard_history.sql
053_leaderboard_metadata.sql
054_leaderboard_flagging.sql
068_decision_trace.sql
20260306_074_pipeline_versions.sql
20260306_077_economic_events.sql
20260306_080_indexer_tables.sql
20260318_087_indexed_vault_activations.sql
20260415_091_v4a_settlement_indexer_alignment.sql
20260416_093_v4b_identity_indexer_tables.sql
20260416_094_v4b_ride_attestation_columns.sql
20260417_095_preliminary_attestation_handshake.sql
20260420_097_vault_activation_audit_state.sql
086_indexed_settlement_projections.sql
089_finalized_at_settlement_projection.sql
093_post_ride_cascade_detail.sql
111_canon_climb_registry.sql
112_canon_registry_private_rls.sql
113_settlement_crank_state_machine.sql
114_ride_economic_recovery.sql
115_ride_economic_review_repair.sql
117_parser_provenance.sql
118_stake_settlement_snapshots.sql
119_settlement_clock_v2.sql
121_tribute_conservation.sql
122_authoritative_ride_metrics.sql
123_reward_ftp_authority.sql
134_indexed_legends_bootstrap_projection.sql
139_canon_traversal_evidence.sql
140_single_ratified_canon.sql
141_canon_runtime_activation.sql
143_canon_runtime_digest_portability.sql
152_account_deletion_lifecycle.sql
154_derived_threshold_authority.sql
169_stage1_program_version_window.sql
170_stage1_keeper.sql
171_stage1_indexer.sql
""".split()


async def schema(c, powered_wallets=()):
    statements = []
    class Capture:
        def execute(self, sql):
            statements.append(sql)
    _bootstrap_pre_152(Capture())
    for sql in statements:
        await c.execute(sql)
    replaced = """patterns_climb patterns_steady patterns_exploration cal_daily_balances
    ride_economic_plans reward_ftp_authorities economic_events indexed_vaults
    indexed_leaderboards indexed_legends indexed_stakes indexed_completions
    indexed_accounts indexed_beetle_cards indexed_events indexed_staker_allocations
    indexed_rider_souls indexed_ride_attestations indexed_cal_mint_receipts settlement_jobs
    local_legend_rollovers vault_stakes vault_leaderboards vault_distributions
    distribution_receipts swanny_seats swanny_elections leaderboard_history
    leaderboard_disputes vault_completions""".split()
    for table in replaced:
        await c.execute(f'DROP TABLE IF EXISTS public."{table}" CASCADE')
    await c.execute("""ALTER TABLE public.rides ADD started_at timestamptz,
        ADD created_at timestamptz DEFAULT now(), ADD uploaded_at timestamptz""")
    for name in MIGRATIONS:
        if name == '154_derived_threshold_authority.sql' and powered_wallets:
            # Historical verified-test fixtures migrate through the same
            # authority bridge as production. Never disable an FTP guard.
            for wallet in powered_wallets:
                user = await c.fetchval('SELECT user_id FROM br_get_or_create_active_user(gen_random_uuid(),$1)',wallet)
                await c.execute("""INSERT INTO reward_ftp_authorities(user_id,ftp_w,source,evidence,evidence_hash,verified_by,verified_at,effective_at)
                    VALUES($1,200,'verified_power_test','{}',sha256(convert_to('{}','UTF8')),'localnet-synthetic','2026-01-01','2026-01-05 12:00+00')""",user)
            for extra in ('127_parser_v4_climb_authority.sql','130_cal_tribute_policy.sql'):
                await c.execute((BACKEND/'sql'/extra).read_text())
        # Historical scripts change a default-argument signature but leave its
        # old overload, making their unqualified COMMENT ambiguous on a fresh
        # replay. Drop only that superseded, unused legacy function; never edit
        # migration text or supply substitute source tables/functions.
        if name == "052_leaderboard_history.sql":
            await c.execute("DROP FUNCTION public.update_vault_leaderboard(text,text,integer,integer,uuid)")
        if name == "053_leaderboard_metadata.sql":
            await c.execute("DROP FUNCTION public.update_vault_leaderboard(text,text,integer,integer,uuid,timestamptz)")
        path = BACKEND / ("supabase/migrations" if name.startswith("2026") else "sql") / name
        try:
            await c.execute(path.read_text())
            if name == '154_derived_threshold_authority.sql' and powered_wallets:
                for extra in ('155_threshold_provisional_hold.sql','157_segment_tss_cal_tribute.sql',
                              '163_threshold_hold_freeze_uses_measured_policy.sql','164_ride_effort_trim.sql'):
                    await c.execute((BACKEND/'sql'/extra).read_text())
        except Exception as exc:
            raise RuntimeError(f"Whole migration failed: {name}") from exc
