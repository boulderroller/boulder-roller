"""
Projection Writer: Read-layer (indexer) writes extracted from ride processing.

Role: BACKEND_TRUTHS §5.3 Projector — maintains the indexer and read-layer
tables that power dashboards, leaderboards, feeds, and BoulderScan. The
Projector is **downstream** of on-chain state.

Per BACKEND_TRUTHS §10 (Indexer Is A Cache):
  - "The indexer is a projection of on-chain state. It may lag, it may
    stutter, it may be rebuilt. It must never be authoritative."
  - Transaction builders never read from or wait on projection tables.
  - Projection drift is self-healing via reindex, never via direct
    reconciliation writes here.

Scope of this module (first slice of the ride_processor.py role
decomposition, per bead `mfab.1`):

  - Writes to the `indexed_vaults` projection table (e.g. opportunistic
    GPS + polyline backfill when the attester has richer local evidence
    than what flowed through the indexer so far).
  - Writes to the `vault_completions` projection table to mirror
    on-chain completion transaction signatures (so the read layer can
    surface tx status) — **never** economic state.

Arrow of truth:
  - These writes are downstream of chain acceptance (or of a detected
    climb's local evidence that the chain has not yet seen).
  - They never replace or contradict on-chain state; a reindex from
    chain state must be able to overwrite anything written here.

Deferred to subsequent `mfab.1` slices:
  - Attester extraction (parse / canonicalize / hash / preliminary
    attestation evaluation) into `ride_attester.py`.
  - Executor extraction (`send_record_ride`, `send_credit_cal`,
    `send_record_climb_completion`) into `ride_executor.py`.

Citations:
  - BACKEND_TRUTHS §5.3 (Projector role)
  - BACKEND_TRUTHS §10 (Indexer Is A Cache)
  - BACKEND_TRUTHS §4.3 (Projected Truth layer)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from ..repositories import get_supabase_client

logger = logging.getLogger(__name__)


class ProjectionWriter:
    """Write-side entry point for indexer / read-layer projections.

    Not a source of truth. Every write here is either:
    - a mirror of something the chain already accepted, or
    - an opportunistic backfill of derivative data (GPS, polylines)
      that the chain itself does not hold.

    The class is intentionally thin: it owns zero business logic and no
    economic math. It exists to keep the Supabase client out of the
    ride_processor.py Attester+Executor hot path per BACKEND_TRUTHS §5.
    """

    def __init__(self, client: Optional[Any] = None) -> None:
        self._client = client or get_supabase_client()

    # -----------------------------------------------------------------
    # indexed_vaults projection writes
    # -----------------------------------------------------------------

    def backfill_vault_gps(
        self,
        vault_id: Any,
        start_lat: Optional[float],
        start_lon: Optional[float],
        end_lat: Optional[float],
        end_lon: Optional[float],
    ) -> bool:
        """Backfill start/end GPS onto an indexed_vaults row.

        Opportunistic: when a ride's detected climb carries GPS
        endpoints and the projection row does not yet have them, we
        enrich the cache. The chain's authoritative climb identity is
        its signature, not its GPS — these coordinates only drive the
        read layer (map, BoulderScan).

        Returns True on success, False on any failure (failure is
        never propagated — projection is best-effort).
        """
        try:
            self._client.table("indexed_vaults").update(
                {
                    "start_lat": start_lat,
                    "start_lon": start_lon,
                    "end_lat": end_lat,
                    "end_lon": end_lon,
                }
            ).eq("id", vault_id).execute()
            logger.info(
                f"[VaultGPS] Backfilled GPS for vault {vault_id}: "
                f"({start_lat}, {start_lon})"
            )
            return True
        except Exception as err:
            logger.debug(f"[VaultGPS] Backfill failed (non-fatal): {err}")
            return False

    def backfill_vault_polyline(
        self,
        vault_id: Any,
        polyline_data: Any,
    ) -> bool:
        """Backfill a JSON polyline onto an indexed_vaults row.

        `polyline_data` is either a raw list (which we JSON-encode) or
        an already-encoded string. Used to populate template-matching
        polylines from a ride when the vault projection does not yet
        have one — again, purely a read-layer enrichment.

        Returns True on success, False on any failure.
        """
        try:
            if isinstance(polyline_data, str):
                polyline_json = polyline_data
            else:
                polyline_json = json.dumps(polyline_data)
            self._client.table("indexed_vaults").update(
                {"polyline_json": polyline_json}
            ).eq("id", vault_id).execute()
            logger.info(
                f"[VaultPolyline] Backfilled polyline for vault {vault_id}"
            )
            return True
        except Exception as err:
            logger.debug(f"[VaultPolyline] Backfill failed (non-fatal): {err}")
            return False

    # -----------------------------------------------------------------
    # vault_completions projection writes (mirror of on-chain tx state)
    # -----------------------------------------------------------------

    def mirror_completion_tx(
        self,
        vault_signature: str,
        activity_id: str,
        tx_signature: str,
    ) -> bool:
        """Mirror a successful on-chain completion tx onto the
        vault_completions projection row.

        The chain is already authoritative; this write only helps the
        read layer render tx status without needing a chain round-trip.
        """
        if str(tx_signature).startswith("exists:"):
            logger.warning(
                "[Projector] Refusing to store PDA existence marker as a "
                "transaction signature for activity %s",
                activity_id,
            )
            return False
        try:
            self._client.table("vault_completions").update(
                {
                    "on_chain_tx": tx_signature,
                    "on_chain_tx_error": None,
                }
            ).eq("vault_signature", vault_signature).eq(
                "activity_id", activity_id
            ).execute()
            return True
        except Exception:
            return False

    def mirror_completion_tx_error(
        self,
        vault_signature: str,
        activity_id: str,
        error: str,
    ) -> bool:
        """Mirror an on-chain completion failure onto the
        vault_completions projection row for observability.

        The authoritative state is still the chain's absence of the
        completion — this write is only so operators see the failure
        reason in the read layer.
        """
        try:
            self._client.table("vault_completions").update(
                {"on_chain_tx_error": error[:500]}
            ).eq("vault_signature", vault_signature).eq(
                "activity_id", activity_id
            ).execute()
            return True
        except Exception:
            return False
