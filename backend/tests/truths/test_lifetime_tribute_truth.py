"""Cross-layer gates for the ratified lifetime tribute flow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PROGRAM_SRC = ROOT / "protocol" / "anchor" / "programs" / "boulder_rollers" / "src"
PROTOCOL_TRUTHS = ROOT / "docs" / "PROTOCOL_TRUTHS.md"
BACKEND_TRUTHS = ROOT / "docs" / "BACKEND_TRUTHS.md"
FRESHEST_SPEC = ROOT / "docs" / "FRESHEST_SPEC.md"
MATH_AUDIT = ROOT / "docs" / "design" / "MATH_AUDIT_2026-07-09.md"
MATH_AUDIT_PHASE2 = ROOT / "docs" / "design" / "MATH_AUDIT_PHASE2_2026-07-12.md"
V4B_BLAST_RADIUS = ROOT / "docs" / "design" / "V4B_BLAST_RADIUS_INVENTORY.md"
COORDINATOR = ROOT / "backend" / "app" / "services" / "ride_economic_coordinator.py"


def _program_source(*, tests: bool = True) -> str:
    """The Anchor program's Rust source, joined across every module file."""
    paths = sorted(PROGRAM_SRC.glob("*.rs"))
    if not tests:
        paths = [path for path in paths if not path.stem.endswith("tests")]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_protocol_freezes_admission_and_disables_receiptless_completion() -> None:
    source = _program_source()
    production = _program_source(tests=False)

    # Ordinary V2 admission and one-time V3 held-ride release are the only
    # receipt-backed lifetime tribute paths.
    assert production.count("vault.credit_lifetime_tribute(cal_tribute)?;") == 2
    assert "pub fn record_climb_completion_v2" in production
    assert "pub fn record_released_climb_completion" in production
    assert "fn credit_tribute_for_week" not in source
    assert "ErrorCode::RideOutsideSettlementWindow" not in source
    assert "RideOutsideSettlementWindow," in source
    assert production.count("require_accepted_ride_timestamps(") == 6
    assert production.count("require_valid_ride_timestamps(") == 3
    assert "completion.note_completed_at(completed_at);" in production

    # The receipt-less and tribute-unbound completion entries were removed.
    assert "pub fn record_vault_completion(" not in production
    assert "pub fn record_climb_completion<" not in production


def test_truth_docs_define_timeless_records_and_open_flow_attribution() -> None:
    protocol_truths = _read(PROTOCOL_TRUTHS)
    backend_truths = _read(BACKEND_TRUTHS)
    freshest_spec = _read(FRESHEST_SPEC)

    required = (
        "lifetime tribute flow meter",
        "oldest open Settlement Week",
        "original `completed_at`",
        "30-day",
    )
    for phrase in required:
        assert phrase in protocol_truths
        assert phrase in backend_truths
        assert phrase in freshest_spec


def test_backend_confirms_every_completion_before_crediting_cal() -> None:
    source = _read(COORDINATOR)
    completion_call = source.index("self.executor.record_climb_completion_receipt(")
    completion_checkpoint = source.index("self.repository.confirm_completion_step(")
    cal_call = source.index("self.executor.credit_cal_receipt(")

    assert completion_call < completion_checkpoint < cal_call
    assert source.index('status="recovery_pending"') < completion_call


def test_audit_ledgers_mark_lrwd_landed_and_keep_projection_separate() -> None:
    audit = _read(MATH_AUDIT)
    phase2 = _read(MATH_AUDIT_PHASE2)
    blast_radius = _read(V4B_BLAST_RADIUS)

    assert "Resolution (2026-07-14)" in audit
    assert "boulderroller-v2-4x3v" in audit
    assert "boulderroller-v2-29rm" in audit
    assert "landed 2026-07-14" in phase2
    assert "boulderroller-v2-4x3v" in phase2
    assert "boulderroller-v2-29rm" in phase2
    assert "deprecated ABI slot after LRWD" in blast_radius
    assert "production instructions must not emit it" in blast_radius

    alignment_plan = _read(ROOT / "docs" / "design" / "PROTOCOL_ALIGNMENT_FIX_PLAN.md")
    assert "P6 and P7 are superseded" in alignment_plan
