import pytest

from app.generated_program_version import (
    CURRENT_PROGRAM_VERSION,
    PREVIOUS_PROGRAM_VERSION,
)
from app.program_compatibility import STAGE1_PROGRAM_VERSIONS
from app.solana_direct import require_current_program_version


@pytest.mark.parametrize("version", [0x4C, 0x4D, 0x4E])
def test_backend_accepts_exact_cutover_window(version: int) -> None:
    assert require_current_program_version(version) == version


def test_window_serves_stage1_at_the_manifest_previous_and_current_versions() -> None:
    # Services ship before the chain advances, so a manifest bump needs a new window.
    assert {PREVIOUS_PROGRAM_VERSION, CURRENT_PROGRAM_VERSION} <= set(STAGE1_PROGRAM_VERSIONS)


@pytest.mark.parametrize("version", [0x44, 0x4B, 0x4F, 0, 255])
def test_backend_rejects_outside_cutover_window(version: int) -> None:
    with pytest.raises(ValueError, match="ProgramConfig version mismatch"):
        require_current_program_version(version)


@pytest.mark.parametrize("observed", [None, -1, 256, "65", True])
def test_backend_rejects_missing_or_non_u8_program_versions(observed: object) -> None:
    with pytest.raises(ValueError, match="ProgramConfig version"):
        require_current_program_version(observed)
