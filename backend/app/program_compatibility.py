"""The single, bounded service window for ProgramConfig versions.

Each program release chooses its window explicitly. 0x4C is legacy-only; Stage 1
is available at 0x4D and at 0x4E, which adds no Stage 1 surface. Ship services
that accept a new version before the chain advances to it.
"""

from dataclasses import dataclass
from typing import Optional


SUPPORTED_PROGRAM_VERSIONS = (0x4C, 0x4D, 0x4E)
STAGE1_PROGRAM_VERSIONS = (0x4D, 0x4E)
STAGE1_UNAVAILABLE = "Stage 1 is not available on this network"
# Stored admission over program_version_observations (aliased v), never RPC.
STAGE1_OBSERVED_VERSION_SQL = "v.highest_version IN ({})".format(
    ",".join(str(version) for version in STAGE1_PROGRAM_VERSIONS)
)


def require_program_version_byte(observed: object) -> int:
    if isinstance(observed, bool) or not isinstance(observed, int) or not 0 <= observed <= 255:
        raise ValueError("ProgramConfig version must be an unsigned byte")
    return observed


def require_compatible_program_version(observed: object) -> int:
    observed = require_program_version_byte(observed)
    if observed not in SUPPORTED_PROGRAM_VERSIONS:
        raise ValueError(
            "ProgramConfig version mismatch: expected "
            + ", ".join(f"0x{version:02X}" for version in SUPPORTED_PROGRAM_VERSIONS)
            + f"; got 0x{observed:02X}"
        )
    return observed


@dataclass
class ProgramCompatibility:
    """Remember the highest valid version seen by this service/network pair."""

    program_version: Optional[int] = None
    genesis: Optional[str] = None
    failure: Optional[Exception] = None

    def invalidate(self, error: Exception) -> None:
        self.failure = error

    def observe(self, observed: object) -> int:
        try:
            version = require_compatible_program_version(observed)
            if self.program_version is not None and version < self.program_version:
                raise ValueError(
                    f"ProgramConfig version downgrade: saw 0x{self.program_version:02X}, got 0x{version:02X}"
                )
            self.program_version = version
            self.failure = None
            return version
        except ValueError as exc:
            self.failure = exc
            raise

    @property
    def stage1_available(self) -> bool:
        return self.failure is None and self.program_version in STAGE1_PROGRAM_VERSIONS

    def require_stage1(self) -> None:
        if self.failure is not None:
            raise self.failure
        if not self.stage1_available:
            raise RuntimeError(STAGE1_UNAVAILABLE)


# A backend can access more than one network/program in tests and maintenance.
# Keep high-water marks distinct; a new DirectConfig must not reset the window.
_networks: dict[tuple[str, str], ProgramCompatibility] = {}


def program_compatibility(rpc_url: str, program: str) -> ProgramCompatibility:
    return _networks.setdefault((rpc_url, program), ProgramCompatibility())


async def observe_program_version(client, rpc_url: str, program: str, observed: object, *, pool=None) -> ProgramCompatibility:
    """Persist before exposing capability, including a backend-only advance.

    The database key uses chain identity rather than provider URL. Its atomic
    maximum contains only supported versions, survives process restarts, and
    is shared with the indexer. Failure never falls back to an ephemeral
    observation or a projection row.
    """
    from .db_pool import get_pool

    state = program_compatibility(rpc_url, program)
    try:
        version = require_compatible_program_version(observed)
        genesis_value = (await client.get_genesis_hash()).value
        if genesis_value is None:
            raise ValueError("RPC genesis hash is missing")
        genesis = str(genesis_value)
        if not genesis:
            raise ValueError("RPC genesis hash is missing")
        pool = pool if pool is not None else await get_pool()
        async with pool.acquire() as connection:
            highest = await connection.fetchval(
                "SELECT public.observe_program_version($1, $2, $3::smallint)",
                genesis, program, version,
            )
        state.observe(highest)
        state.observe(version)
        state.genesis = genesis
        return state
    except Exception as exc:
        state.invalidate(exc)
        raise
