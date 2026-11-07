# Vault Matching Authority

**Status:** Binding V4-B backend contract as of 2026-07-21
**Owner:** Canon identity cutover bead `boulderroller-v2-4crx.11`

This contract supersedes every detector-signature, similarity, and localized
endpoint path that previously selected a Vault for economics.

## One Economic Path

A completion plan may contain a Vault step only through this sequence:

1. Identity-bound raw ride evidence produces an accepted D11 canon traversal.
2. Its trace identifies one private registry row by exact `registry_id`,
   `canon_id`, `canon_version`, and canonical profile hash.
3. The backend resolves that identity to one indexed Climb carrying the same
   D12 commitment.
4. The Climb's attached Vault pointer and the Vault's Climb pointer identify the
   same exact account pair.
5. The backend reservation is `finalized`, the indexed Climb and Vault are
   current and not quarantined, and the chain-derived Vault Activation is active
   with exactly `seed_generation = 2` and zero constructor history.
6. The plan builder consumes that exact frozen Climb/Vault/Activation row. It
   does not refetch a Vault through a generic numeric-ID lookup.

Missing, malformed, stale, ambiguous, quarantined, mismatched, or unfinalized
evidence fails closed. No cached Vault ID, name, score, or earlier match trace
can replace any step above.

An accepted traversal begins with
`MATCH:canon_activation_required`. Resolving the exact finalized binding clears
only that reason. Any remaining `SENSOR:`, `CLIMB_SENSOR:`, `EFFORT:`, or other
abstention keeps the traversal outside the completion plan.

## Detector Compatibility Is Discovery Only

Persistence, momentum, DCT, H3, v1/v2 signatures, similarity scores, and
localized detector endpoints remain useful for display, diagnostics, replay,
and ClimbLab canon nomination. They are discovery only.

Every non-`canon_traversal_v1` climb is stored with
`economic_eligible = false`, `MATCH:canon_traversal_required`, and a
`discovery_only` authority trace. Detector-era Vault completions are discarded
before persistence. A detector row cannot select tribute, write a completion or
Record Board entry, or serve as a settlement input even when its similarity is
perfect and its endpoints agree.

Parser V5 and the immutable `5-ftp-v1` pipeline vector supply current ride
canonicalization and evidence provenance. V1-V4 remain replayable for their
historical lineage; they are never silently reinterpreted or promoted into D11
economics.

## Creation And Activation

Vault creation starts from one active private canon registry revision. The
backend reserves the exact registry/Climb/Vault/Activation tuple before building
the constructor transaction, and only the finalized backend-authority
constructor path may create it. Direct rider-signed and legacy seed paths are
retired for V4-B creation.

Finalization requires exact agreement among the registry row, D12 commitment,
Climb account, Vault account, expected Vault Activation PDA, constructor
evidence hash, and chain-derived activation projection. Constructor activation
must prove generation 2 with:

- `seed_generation = 2`;
- zero completions written;
- zero matched users and matched completions;
- a seeded empty leaderboard;
- one non-zero evidence hash shared by the reservation and chain account; and
- equal creation, activation, seed, and seed-cutoff timestamps.

A timed-out reservation may be released only after explicit finalized on-chain
absence past the prepared transaction's last valid block height.

## Quarantine And Recovery

Indexer observations are monotonic by chain slot. An invalid Climb observation
atomically quarantines that Climb and every attached active Vault, including a
Vault observed at a higher slot; the Vault keeps its greater slot. An invalid
Vault observation quarantines that exact Vault.

Recovery also fails closed. A later valid Climb observation may clear the Climb
quarantine, but the Vault returns to `canon_binding_status = 'active'` only
after a later exact valid Vault observation re-establishes both account pointers
and the full identity. Stale observations cannot reactivate either account.

## Tribute Policy

Exact Vault selection and CAL attribution are separate gates. Once completion
steps are frozen, `cal_tribute_segment_tss_v2` computes each Vault's amount from
the authoritative Climb window's pause-aware NP duration, integer NP
milliwatts, and immutable ride-time reward FTP. Each measured amount is floored
independently; missing power receives zero tribute with no gradient proxy. One
fastest qualifying traversal per ride and Vault supplies the existing receipt,
and overlapping eligible windows require review rather than double counting.

## Verification

The cutover gate covers:

- identity-bound raw evidence invoking the default D11 service;
- one accepted D11 traversal reaching one exact frozen plan step;
- missing and mismatched registry, Climb, Vault, pointer, activation, and
  constructor evidence abstaining;
- activity and per-climb sensor abstention surviving an exact binding;
- detector rows remaining discovery only with no detector completion rows;
- stale and higher-slot quarantine ordering plus exact revalidation; and
- SQL and TypeScript indexer agreement on the active binding projection.
