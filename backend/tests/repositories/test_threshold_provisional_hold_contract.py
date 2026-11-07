"""Static SQL contract for Threshold provisional holds and release authority."""

from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_PATH = BACKEND_ROOT / "sql" / "155_threshold_provisional_hold.sql"


def test_threshold_hold_migration_is_private_complete_and_mirrored() -> None:
    assert CANONICAL_PATH.exists(), "migration 155 must own the Threshold hold authority"
    mirrors = list(
        (BACKEND_ROOT / "supabase" / "migrations").glob(
            "*_threshold_provisional_hold.sql"
        )
    )
    assert len(mirrors) == 1

    canonical = CANONICAL_PATH.read_text(encoding="utf-8")
    assert mirrors[0].read_text(encoding="utf-8") == canonical

    for contract in (
        "CREATE TABLE public.reward_threshold_provisional_holds",
        "CREATE TABLE public.reward_threshold_provisional_hold_admissions",
        "CREATE TABLE public.reward_threshold_release_batches",
        "CREATE TABLE public.reward_threshold_release_batch_items",
        "CREATE TABLE public.reward_threshold_release_snapshots",
        "CREATE OR REPLACE FUNCTION public.create_reward_threshold_release_batch",
        "CREATE OR REPLACE FUNCTION public.record_reward_threshold_provisional_hold_admission",
        "CREATE OR REPLACE FUNCTION public.prevent_reward_threshold_hold_release_mutation",
        "CREATE OR REPLACE FUNCTION public.enforce_ride_threshold_release_power_inputs",
        "CREATE OR REPLACE VIEW public.confirmed_vault_completion_candidates",
        "INTERVAL '16 weeks'",
        "ENABLE ROW LEVEL SECURITY",
        "SECURITY DEFINER",
        "SET search_path = ''",
        "pg_catalog.pg_advisory_xact_lock",
    ):
        assert contract in canonical

    for table in (
        "reward_threshold_provisional_holds",
        "reward_threshold_provisional_hold_admissions",
        "reward_threshold_release_batches",
        "reward_threshold_release_batch_items",
        "reward_threshold_release_snapshots",
    ):
        assert f"REVOKE ALL ON public.{table}" in canonical

    assert (
        "REVOKE ALL ON FUNCTION public.create_reward_threshold_release_batch("
        in canonical
    )
    assert (
        "GRANT EXECUTE ON FUNCTION public.create_reward_threshold_release_batch"
        not in canonical
    )

    # The 16-week disposition is frozen from the finalized parent
    # RideAttestation clock, never the earlier plan/hold registration clock.
    assert "JOIN public.reward_threshold_provisional_hold_admissions AS admission" in canonical
    assert "v_batch.established_at - admission.admitted_at" in canonical
    assert "v_batch.established_at - hold.held_at" not in canonical
    assert "'admitted_at', admission.admitted_at" in canonical

    # The display-only network default cannot survive cutover as executable
    # positive economics, and cannot freeze a new completion receipt.
    assert "Threshold cutover blocked by executable 200 W network-default economics" in canonical
    assert "200 W network default cannot authorize counted economics" in canonical
    assert "CREATE TRIGGER trg_prevent_network_default_completion_step" in canonical
    assert "normalized_power_raw_w, normalized_power_duration_s" in canonical
    assert "Threshold release power inputs are service-only" in canonical
    assert "Threshold release power inputs are immutable" in canonical
    assert "UNION ALL\nSELECT\n    release_step.vault_id" in canonical

    # Mutable ride deletion cannot erase or block retained economic authority.
    # UUID evidence follows the pre-existing ride_economic_plans no-FK pattern,
    # and an absent product row is an honestly omitted terminal projection.
    assert "reward_threshold_provisional_holds_ride_id_fkey" not in canonical
    assert "reward_threshold_provisional_hold_admissions_ride_id_fkey" not in canonical
    assert "reward_threshold_release_snapshots_ride_id_fkey" not in canonical
    assert "reward_threshold_hold_release_evidence" in canonical
    assert "SELECT ride.id INTO v_product_ride_id" in canonical


def test_threshold_release_authority_is_distinct_from_frozen_normal_plans() -> None:
    canonical = CANONICAL_PATH.read_text(encoding="utf-8")
    lowered = canonical.lower()

    assert "reward_ftp_authority_id" in canonical
    assert "snapshot_evidence_hash" in canonical
    assert "update public.ride_economic_plans" not in lowered
    assert "alter table public.ride_economic_plans" not in lowered


def test_release_sql_preserves_budget_cap_open_flow_and_terminal_recovery() -> None:
    canonical = CANONICAL_PATH.read_text(encoding="utf-8")

    # A ride with no positive matched-Vault weights still releases CAL; its
    # 10% tribute amount is a cap, not an obligation to manufacture tribute.
    assert "v_total_tribute > v_tribute_budget" in canonical
    assert "v_total_tribute IS DISTINCT FROM v_tribute_budget" not in canonical

    # A released completion is credited only in the authority's frozen release
    # week. Receipt, flow, and release authority must all agree.
    assert (
        "v_flow.credited_settlement_week IS DISTINCT FROM\n"
        "            v_receipt.credited_settlement_week"
    ) in canonical

    # Release cannot outrun the parent zero-plan terminal projection, which
    # would otherwise overwrite the positive released CAL back to zero.
    assert canonical.count("plan.terminal_projected_at IS NOT NULL") >= 3

    # A finalized existing child PDA is valid recovery authority even when the
    # original transaction signature is no longer available locally. Synthetic
    # exists: references remain forbidden.
    assert "COALESCE(p_tx_signature, '') LIKE 'exists:%'" in canonical
    assert "p_tx_signature IS NOT NULL" in canonical
    assert (
        "v_receipt.credited_settlement_week IS DISTINCT FROM\n"
        "            v_indexed_release.release_settlement_week"
    ) in canonical

    # Chain-complete rows remain claimable until their terminal projection is
    # durable, so one transient projection failure cannot strand the ride.
    assert (
        "execution.state <> 'review'\n"
        "      AND (\n"
        "          execution.state <> 'complete'\n"
        "          OR execution.terminal_projected_at IS NULL\n"
        "      )"
    ) in canonical
