from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "sql" / "156_threshold_rider_projection.sql"
MIRROR = ROOT / "supabase" / "migrations" / "20260831140000_threshold_rider_projection.sql"


def test_threshold_rider_projection_is_private_and_mirrored() -> None:
    canonical = CANONICAL.read_text(encoding="utf-8")
    assert MIRROR.read_text(encoding="utf-8") == canonical
    assert "get_reward_threshold_rider_projection" in canonical
    assert "get_reward_threshold_ride_projections" in canonical
    assert "SECURITY DEFINER" in canonical
    assert "STABLE" in canonical
    assert "GRANT EXECUTE ON FUNCTION public.get_reward_threshold_rider_projection" in canonical
    assert "GRANT EXECUTE ON FUNCTION public.get_reward_threshold_ride_projections" in canonical
    assert "TO service_role" in canonical
    assert "display_candidate_w" not in canonical
    assert "Threshold has an overdue unsealed promotion" not in canonical
    assert "'sealing_in_progress'" in canonical
    assert "latest_release" not in canonical


def test_release_projection_updates_the_single_visible_training_tss() -> None:
    canonical = CANONICAL.read_text(encoding="utf-8")
    assert "SET cal_earned = v_display_cal::INTEGER," in canonical
    assert "tss = v_snapshot.economic_tss" in canonical
    assert "threshold_training_kind = 'sealed'" in canonical
