# Abstention Policy

**Status:** ACTIVE
**Last updated:** 2026-07-21
**Authority:** V4-B canon cutover

Abstention means a climb may remain visible as a ride or discovery object, but
it does not trigger Vault completion, CAL tribute, Record Board state, or a
settlement input. False certainty destroys trust; an absent or uncertain gate
is a reason to stop, not a reason to infer.

## Authority Classes

### Detector output

Every persistence, momentum, template, DCT, signature, similarity, H3, or
localized-endpoint result is discovery only. Every non-canon pattern carries:

- `economic_eligible = false`;
- `MATCH:canon_traversal_required`; and
- `match_trace.authority = discovery_only`.

These rules apply even when canon evaluation is disabled, identity-bound raw
evidence is missing, the detector reports high confidence, or old match fields
name a Vault. Detector-era completion rows are cleared before persistence.

### Accepted canon traversal

An accepted D11 traversal proves exact gate crossing, direction, corridor
coverage, monotonic progress, and the frozen whole-second traversal interval.
It remains abstained with `MATCH:canon_activation_required` until the exact
registry/Climb/Vault/Activation binding is resolved.

The same activity-level and climb-window sensor gates that protect detector
patterns are applied to newly appended D11 patterns. Applicable `SENSOR:`,
`CLIMB_SENSOR:`, and `EFFORT:` reasons are retained. An exact finalized binding
may clear only `MATCH:canon_activation_required`; it cannot clear another
reason or flip the traversal eligible while any reason remains.

### Exact finalized binding

Economics require one current, non-quarantined registry identity, D12
commitment, indexed Climb, attached Vault, finalized reservation, and active
chain-derived generation-2 Vault Activation with zero constructor history.
Missing, malformed, stale, ambiguous, mismatched, quarantined, or unfinalized
evidence abstains.

## Sensor And Effort Triggers

The activity-level sensor report blocks economics for conditions including:

- GPS or elevation coverage below the ratified minimum;
- excessive GPS teleportation, implausible elevation, or excessive time gaps;
- too few samples or a failing composite integrity score; and
- route-estimate-only effort with neither power nor heart-rate evidence.

The accepted climb window also checks GPS and elevation coverage, gaps over five
minutes, and implausible VAM. These gates attach reasons to a D11 result before
the exact binding is evaluated.

Insufficient segment power does not fabricate effort from gradient. The
completion may remain sporting-valid if all identity and sensor gates pass, but
its measured Climb-TSS tribute is zero under `cal_tribute_segment_tss_v2`.

## No Direct Promotion

An abstained detector row cannot be promoted directly into economics. Terrain
bootstrap, a later GPS trace, a high similarity score, or an administrator's
review may strengthen a ClimbLab nomination, but none can remove
`MATCH:canon_traversal_required` or select a Vault.

The only promotion path is to compile and ratify an explicit canon revision,
then evaluate fresh identity-bound ride evidence through D11. That new accepted
D11 traversal must independently pass sensor gates and resolve one exact
finalized binding. Historical detector matches are not replayed as completions.

## Persistence And Monitoring

Abstention reasons and the machine-readable decision trace are stored with the
climb pattern. Monitoring distinguishes at least:

- detector discovery awaiting canon;
- accepted traversal awaiting activation;
- sensor or effort abstention;
- invalid or ambiguous binding;
- quarantine; and
- successful exact binding with no remaining abstention.

Metrics may reveal missing data or overly conservative gates, but no target
abstention rate authorizes relaxing a ratified gate automatically.

## Relationship To The Truth Contract

This policy implements `INV-ECON-1` through `INV-ECON-4` and `INV-ABST-1`
through `INV-ABST-3` in `docs/TRUTH_CONTRACT_V1.md`.
