"""Cross-document gate for the ratified ride CAL tribute policy."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
POLICY_DOCS = (
    ROOT / "docs" / "PROTOCOL_TRUTHS.md",
    ROOT / "docs" / "BACKEND_TRUTHS.md",
    ROOT / "docs" / "FRESHEST_SPEC.md",
    ROOT / "docs" / "ECONOMIC_MODEL_FORMAL.md",
    ROOT / "docs" / "TRUTH_CONTRACT_V1.md",
)

POLICY_VERSION = "cal_tribute_segment_tss_v2"
REQUIRED_POLICY_TERMS = (
    POLICY_VERSION,
    "segment_tss_base_units_i",
    "exact_tribute_budget_base_units = sum(segment_tss_base_units_i)",
    "full attested CAL",
    "one fastest qualifying traversal per ride and Vault",
    "overlapping eligible climb windows require review",
    "never exceeds full attested CAL",
    "immutable ride-time reward FTP",
    "mutable profile FTP",
    "no gradient proxy",
    "floored independently",
)


def test_canonical_docs_freeze_one_cal_tribute_policy() -> None:
    for path in POLICY_DOCS:
        text = path.read_text(encoding="utf-8")
        lowered = " ".join(text.split()).lower()
        missing = [term for term in REQUIRED_POLICY_TERMS if term.lower() not in lowered]
        assert not missing, f"{path.name} is missing ratified policy terms: {missing}"


def test_canonical_docs_reject_the_retained_cal_tax_model() -> None:
    for path in POLICY_DOCS:
        text = path.read_text(encoding="utf-8")
        assert "1 - alpha retained" not in text.lower()
        assert "1 - α retained" not in text
        assert "10% of CAL goes to vault" not in text


def test_vault_matching_contract_names_exact_canon_as_completion_authority() -> None:
    text = (ROOT / "docs" / "VAULT_MATCHING_SYSTEMS.md").read_text(
        encoding="utf-8"
    )

    assert "Binding backend contract as of 2026-07-15" not in text
    for term in (
        "D11 canon traversal",
        "D12 commitment",
        "finalized",
        "seed_generation = 2",
        "discovery only",
        "MATCH:canon_traversal_required",
        POLICY_VERSION,
    ):
        assert term in text


def test_abstention_policy_cannot_promote_detector_rows_into_economics() -> None:
    text = (ROOT / "docs" / "ABSTENTION_POLICY.md").read_text(encoding="utf-8")

    assert "Abstained climbs can be promoted to economic-eligible" not in text
    assert "Manual review by admin" not in text
    for term in (
        "MATCH:canon_traversal_required",
        "discovery only",
        "accepted D11 traversal",
        "exact finalized",
        "cannot be promoted directly",
    ):
        assert term in text
