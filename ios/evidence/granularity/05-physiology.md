# FTP and weight facts — local/offline evidence

**Bead:** `boulderroller-v2-odmi6.5` (client half; server contract remains the
bead's open Tim question)

**Owner/status:** claude / client implemented local-authoritative; backend
persistence blocked on the ratified contract

**Evidence class:** local/offline (render fixtures labeled simulated; unit
tests over the store, formatter, and the real Rust parser)

**Input class:** deterministic local fixtures and a GPXWriter-serialized
120-second powered ride; no production account write, no CAL, no permanent
surface

## Externally checkable outcome

A rider who never entered FTP or weight sees a dash on both avatar-sheet rows
— never 200 W, never 75 kg. The rows follow the binding grammar (label · one
trailing value · chevron) and sit in the Riding group between Sensors and
Units. Editing opens the money room's numeral-input species; Done is disabled
outside the plausible ranges (FTP 30–500 W, weight 30–200 kg), and Clear
removes the fact entirely with its provenance.

Weight is stored in kilograms at tenth precision and displays per the Units
row: the 81.4 kg fixture renders 179 lb on an imperial account. FTP renders
exact watts. Values persist per rider id; a second account inherits nothing.

The preliminary parser wrapper has no silent FTP default any more. With no
rider FTP on record, the same file parses to a summary whose TSS and
Intensity Factor are truthfully absent while NP, average power, distance,
and the canonical hash are unchanged — the test proves byte-identical
canonical hashes with and without FTP, so the custody stamp and upload
lineage are FTP-independent. Backend-computed CAL remains authoritative and
untouched.

The client `User` model no longer decodes `ftp_w` at all: the API's
fabricated default cannot be consumed by construction. Server sync is a
documented seam in `RiderPhysiologyStore` (no import of fabricated GET
values, no PUT), pending the odmi6.5 permanence/privacy contract; the
backend half is cut as its own bead depending on that ratification.

## Captures (simulated — simulator, DEBUG render fixtures)

- `05-physiology-avatar-unset-simulated.png` — both rows dashed, no defaults
- `05-physiology-avatar-set-simulated.png` — 245 W · 179 lb (imperial from
  81.4 kg stored)
- `05-physiology-edit-ftp-simulated.png` — numeral entry, W unit, disabled
  Done on empty input
- `05-physiology-edit-weight-imperial-simulated.png` — prefilled 179 lb,
  Clear row present

## Tests

`RiderPhysiologyTruthTests` (7): unset-is-empty, set/clear provenance,
per-rider isolation, plausibility bounds refuse and leave nothing behind,
parser FTP bridge, dash/units display, no-FTP parse strips TSS/IF with hash
equality. Full suite green.

## Gaps

- Server-side persistence and portal parity wait on the odmi6.5 contract
  (Tim-ratifies). Until then physiology lives on-device only; reinstalling
  the app loses locally entered values (documented seam, not silent).
- VoiceOver labels and Dynamic Type verified by inspection in the simulator;
  physical-device accessibility audit rides the existing lane-wide pass.

## Resolution (2026-08-11)

Tim's contract question resolved as Choice A (field-level source metadata;
see bead odmi6.5 notes), and the backend shipped it to production
(`coq7q`): honest-nullable `ftp_w`/`weight_kg` + `ftp_w_source`/
`weight_kg_source`, PUT persists explicit null as a clear, fabricated
200/75 gone. The documented sync-later seam in `RiderPhysiologyStore` was
swapped to the live contract — hydrate-fills-empty at session start (server
null never clears local; local manual always wins), push-on-edit with
explicit null on Clear. Production round-trip proof including the clear:
`live-contract-wiring-2026-08-11.md`. The reinstall-loses-values gap above
is now closed by server persistence.
