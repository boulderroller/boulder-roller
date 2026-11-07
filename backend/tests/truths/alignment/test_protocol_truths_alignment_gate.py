"""PROTOCOL_TRUTHS_ALIGNMENT_GATE — cross-lane coherence.

Parent docs:
  * `docs/PROTOCOL_TRUTHS.md` (ACTIVE, canonical)
  * `docs/MOBILE_TRUTHS.md` (ACTIVE)
  * `docs/BACKEND_TRUTHS.md` (ACTIVE)

Scope:
  This gate catches drift BETWEEN the lanes.

  * MOBILE_GATE_1 (mobile/src/__tests__/truths/gate1/truths.gate1.test.ts)
    enforces in-lane MOBILE_TRUTHS invariants.
  * BACKEND_GATE_1 (backend/tests/truths/test_backend_truths_gate1.py)
    enforces in-lane BACKEND_TRUTHS invariants.
  * PROTOCOL_TRUTHS is enforced by the protocol agent's own gates.

  This suite fires when any two of those three drift against each other,
  or against the code that straddles them (upload payload, attestation
  loop, three-clocks contract).

Each test name cites the §N (sometimes two) it is bridging. A failure
message must point the reviewer at BOTH sides of the drift — a reader
should not have to guess which half to fix.

Status taxonomy (same as BACKEND_GATE_1):
  * PASS — coherence holds today.
  * PENDING — expected gap while a dependent repair is staged.
  * DRIFT (failing) — current trio disagrees; failure is the gate working,
    not a bug in the gate.

Run locally from the backend venv:

    pytest backend/tests/truths/alignment/ -v

See docs/design/PROTOCOL_TRUTHS_ALIGNMENT_GATE.md for the coverage matrix.
"""

from __future__ import annotations

import re

import pytest

from ._alignment_helpers import (
    backend_upload_init_request_fields,
    field_names_in_mobile_upload_payload,
    find_protocol_citations,
    grep_lines,
    list_section_numbers,
    mobile_src,
    pydantic_extra_policy_for,
    read_truths,
)


# ===========================================================================
# Class 1 — Doc-level consistency
# ===========================================================================


# ---------------------------------------------------------------------------
# Parent citation integrity — MOBILE_TRUTHS + BACKEND_TRUTHS sit UNDER
# PROTOCOL_TRUTHS. Both headers must say so.
# ---------------------------------------------------------------------------


def test_mobile_truths_declares_it_sits_under_protocol_truths() -> None:
    """MOBILE_TRUTHS header ↔ PROTOCOL_TRUTHS — STATUS: PASS.

    The parent doc hierarchy is load-bearing for the WWPTD dispatcher
    reviewer (PROTOCOL_TRUTHS wins any conflict). If MOBILE_TRUTHS stops
    declaring its parent explicitly, a reader landing on it mid-PR review
    loses the arrow-of-truth signal.
    """
    mobile = read_truths("mobile")
    # Tolerate minor wording (e.g., "sits under", "sits **under**") but
    # require the phrase + the PROTOCOL_TRUTHS link within the first 30
    # lines (header block).
    header = "\n".join(mobile.splitlines()[:30])
    assert re.search(r"sits\s+\*{0,2}under\*{0,2}", header, re.IGNORECASE), (
        "MOBILE_TRUTHS header no longer declares it sits under "
        "PROTOCOL_TRUTHS — parent relationship is load-bearing for WWPTD."
    )
    assert "PROTOCOL_TRUTHS" in header, (
        "MOBILE_TRUTHS header must link/cite PROTOCOL_TRUTHS as the parent."
    )


def test_backend_truths_declares_it_sits_under_protocol_truths() -> None:
    """BACKEND_TRUTHS header ↔ PROTOCOL_TRUTHS — STATUS: PASS.

    Same contract as mobile. BACKEND_TRUTHS must keep the parent
    relationship visible at the header.
    """
    backend = read_truths("backend")
    header = "\n".join(backend.splitlines()[:30])
    assert re.search(r"sits\s+\*{0,2}under\*{0,2}", header, re.IGNORECASE), (
        "BACKEND_TRUTHS header no longer declares it sits under "
        "PROTOCOL_TRUTHS."
    )
    assert "PROTOCOL_TRUTHS" in header, (
        "BACKEND_TRUTHS header must link/cite PROTOCOL_TRUTHS as the parent."
    )


def test_backend_truths_declares_alongside_mobile_truths() -> None:
    """BACKEND_TRUTHS header ↔ MOBILE_TRUTHS — STATUS: PASS.

    BACKEND_TRUTHS also declares it sits alongside MOBILE_TRUTHS so the
    two lanes are peers under PROTOCOL_TRUTHS, not in a parent / child
    relationship to each other.
    """
    backend = read_truths("backend")
    header = "\n".join(backend.splitlines()[:30])
    assert "MOBILE_TRUTHS" in header, (
        "BACKEND_TRUTHS header must name MOBILE_TRUTHS as its peer lane "
        "(both sit under PROTOCOL_TRUTHS). Peer relationship is visible "
        "at the doc header so WWPTD review sees lane equality."
    )


# ---------------------------------------------------------------------------
# §N citation link-rot scan — every `PROTOCOL_TRUTHS §N` reference from
# MOBILE_TRUTHS / BACKEND_TRUTHS must resolve to a real section.
# ---------------------------------------------------------------------------


def test_mobile_truths_protocol_section_citations_resolve() -> None:
    """§N link-rot — MOBILE_TRUTHS → PROTOCOL_TRUTHS — STATUS: PASS.

    Every `PROTOCOL_TRUTHS §N` cite in MOBILE_TRUTHS must land on an
    actual numbered header in PROTOCOL_TRUTHS. A rename or deletion of a
    section in the parent without updating the child is drift.
    """
    protocol_sections = set(list_section_numbers(read_truths("protocol")))
    assert protocol_sections, "PROTOCOL_TRUTHS section scan returned empty"

    citations = find_protocol_citations(read_truths("mobile"))
    assert citations, (
        "MOBILE_TRUTHS cites zero PROTOCOL_TRUTHS sections — every time "
        "this trio has shipped there has been at least one cite; scan "
        "may be stale."
    )

    missing = [
        (lineno, section, line)
        for (lineno, section, line) in citations
        if section not in protocol_sections
    ]
    assert not missing, (
        "MOBILE_TRUTHS cites PROTOCOL_TRUTHS sections that do not exist "
        "in the parent doc (link-rot between the two):\n  "
        + "\n  ".join(f"MOBILE_TRUTHS.md:{ln} §{sec} — {line}" for ln, sec, line in missing)
        + f"\n\nPROTOCOL_TRUTHS sections currently present: "
        + ", ".join(sorted(protocol_sections, key=_numeric_key))
    )


def test_backend_truths_protocol_section_citations_resolve() -> None:
    """§N link-rot — BACKEND_TRUTHS → PROTOCOL_TRUTHS — STATUS: PASS.

    Same contract as mobile. Every cite must resolve.
    """
    protocol_sections = set(list_section_numbers(read_truths("protocol")))
    assert protocol_sections, "PROTOCOL_TRUTHS section scan returned empty"

    citations = find_protocol_citations(read_truths("backend"))
    assert citations, (
        "BACKEND_TRUTHS cites zero PROTOCOL_TRUTHS sections — scan may "
        "be stale."
    )

    missing = [
        (lineno, section, line)
        for (lineno, section, line) in citations
        if section not in protocol_sections
    ]
    assert not missing, (
        "BACKEND_TRUTHS cites PROTOCOL_TRUTHS sections that do not exist "
        "in the parent doc (link-rot):\n  "
        + "\n  ".join(f"BACKEND_TRUTHS.md:{ln} §{sec} — {line}" for ln, sec, line in missing)
        + f"\n\nPROTOCOL_TRUTHS sections currently present: "
        + ", ".join(sorted(protocol_sections, key=_numeric_key))
    )


# ---------------------------------------------------------------------------
# Canonical vocabulary — terms from PROTOCOL_TRUTHS §11 must appear in at
# least one lane doc (where relevant), and deprecated terms must not be
# used as canonical objects in any of the three.
# ---------------------------------------------------------------------------


# Per PROTOCOL_TRUTHS §11, canonical names. "Record Royalty" is §8.1; the
# rest are §11. Each term's expected coverage:
#
#   * "Climb", "Vault", "CAL", "DUNG" — should appear in mobile AND backend
#     (both lanes speak of these primitives).
#   * "Record Board", "Local Legend" — should appear in mobile AND backend.
#   * "Record Royalty" — is the canonical bucket name. Backend should use
#     it; mobile may or may not (rider-facing copy can legitimately not
#     mention royalties yet).
#   * "Settlement Week" — mobile optional (rider-facing), backend required.
#   * "Beetle Score" — backend optional (soulbound layer is PROTOCOL_TRUTHS
#     direction, not yet implemented).
#
# This test asserts the minimum — each term that MUST appear does. It
# does NOT require balanced coverage (e.g., equal hits count); that's a
# naming-density question and not load-bearing.
_TERMS_REQUIRED_BOTH_LANES = ("Climb", "Vault", "CAL", "DUNG", "Record Board", "Local Legend")
_TERMS_REQUIRED_BACKEND = ("Record Royalty", "Settlement Week")


def test_canonical_vocabulary_appears_across_lanes() -> None:
    """PROTOCOL_TRUTHS §11 vocabulary ↔ trio — STATUS: PASS.

    The canonical names from PROTOCOL_TRUTHS §11 must appear in the lane
    docs. Missing occurrence means either a rename drifted or the doc
    stopped covering the object.
    """
    mobile = read_truths("mobile")
    backend = read_truths("backend")

    offenders: list[str] = []
    for term in _TERMS_REQUIRED_BOTH_LANES:
        if term not in mobile:
            offenders.append(
                f"MOBILE_TRUTHS.md does not mention canonical term '{term}' "
                "(PROTOCOL_TRUTHS §11)"
            )
        if term not in backend:
            offenders.append(
                f"BACKEND_TRUTHS.md does not mention canonical term '{term}' "
                "(PROTOCOL_TRUTHS §11)"
            )

    for term in _TERMS_REQUIRED_BACKEND:
        if term not in backend:
            offenders.append(
                f"BACKEND_TRUTHS.md does not mention canonical term '{term}' "
                "(PROTOCOL_TRUTHS §11)"
            )

    assert not offenders, (
        "PROTOCOL_TRUTHS §11 canonical vocabulary drift:\n  "
        + "\n  ".join(offenders)
    )


def test_no_trio_doc_uses_segment_as_canonical_object() -> None:
    """Deprecated vocabulary ↔ trio — STATUS: PASS.

    PROTOCOL_TRUTHS §11 / BACKEND_TRUTHS §12 are explicit: the canonical
    object is `Climb`, never `segment`. Inside the trio docs, `segment`
    should only appear in a naming-discipline "avoid" context (e.g.,
    BACKEND_TRUTHS §12 "Avoid: segments (use Climb)"), never as a
    canonical object.

    Heuristic: flag any line where `segment` / `segments` appears
    WITHOUT a surrounding avoid/deprecated/legacy marker on the same or
    adjacent line. This catches drift like "the climb segment stake
    pool" where the word is being used as canonical object.
    """
    offenders: list[str] = []
    for lane in ("protocol", "mobile", "backend"):
        doc = read_truths(lane)
        lines = doc.splitlines()
        for idx, line in enumerate(lines, start=1):
            m = re.search(r"\bsegments?\b", line, re.IGNORECASE)
            if not m:
                continue
            # Context window: this line + the previous line.
            prev = lines[idx - 2] if idx >= 2 else ""
            blob = (prev + "\n" + line).lower()
            # Allowlist markers: naming-discipline / back-compat / legacy
            # / avoid context. "use Climb" / "(use Climb)" is the most
            # explicit.
            if any(
                marker in blob
                for marker in (
                    "avoid",
                    "deprecated",
                    "legacy",
                    "use climb",
                    "not ",
                    "no longer",
                    "never",
                    "back-compat",
                    "compat alias",
                    "rename",
                )
            ):
                continue
            offenders.append(f"{lane.upper()}_TRUTHS.md:{idx}  {line.strip()}")
    assert not offenders, (
        "Deprecated term 'segment' used in a TRUTHS doc outside a "
        "naming-discipline context (PROTOCOL_TRUTHS §11, BACKEND_TRUTHS "
        "§12). Each occurrence below must either be removed, renamed to "
        "Climb, or marked with an 'avoid/deprecated/legacy' adjacent "
        "context:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Status / ratified fields — all three docs carry ACTIVE status.
# ---------------------------------------------------------------------------


def test_all_three_truths_docs_declare_active_status() -> None:
    """Status headers ↔ trio — STATUS: PASS.

    Any of the three silently losing ACTIVE status is a coordination
    signal the dispatcher must catch. If a doc is ever deprecated, the
    replacement should land in the same commit.
    """
    missing: list[str] = []
    for lane in ("protocol", "mobile", "backend"):
        doc = read_truths(lane)
        header = "\n".join(doc.splitlines()[:10])
        if "Status:" not in header or "ACTIVE" not in header:
            missing.append(f"{lane.upper()}_TRUTHS.md does not show 'Status: ACTIVE' in its header")
    assert not missing, "TRUTHS status drift:\n  " + "\n  ".join(missing)


# ---------------------------------------------------------------------------
# Cross-doc bridge claims — the three specific invariants called out in
# the brief.
# ---------------------------------------------------------------------------


def test_bridge_wallet_identity_cites_protocol_authority_posture() -> None:
    """MOBILE §10 / §2.5 + BACKEND §8 ↔ PROTOCOL_TRUTHS — STATUS: PASS.

    MOBILE_TRUTHS §10 / §2.5: the Wallet is protocol identity — not the
    authority.
    BACKEND_TRUTHS §8: the backend is attester, not authority. Authority
    is granted by the chain (§8.2 direction).
    Bridge: both lanes must surface the "chain → backend → rider audits"
    arrow, or at minimum cite the authority pattern from the parent.

    This is the weakest of the three bridges because MOBILE_TRUTHS does
    not currently cite a specific protocol §N for the authority posture
    (it just names the wallet as identity, distinct from effort identity
    per §7.3). The assertion is: BACKEND_TRUTHS §8 explicitly names
    `granted` / `scoped` language pointing at `ProgramConfig`, and
    MOBILE_TRUTHS §2.5/§10 never asserts "authority" on the wallet side.

    A regression here would look like: MOBILE_TRUTHS starting to describe
    the wallet as "the authority that signs" (wrong; it is identity,
    signing is a capability of identity), or BACKEND_TRUTHS dropping the
    "granted"/"scoped" direction and asserting the backend "holds"
    authority.
    """
    mobile = read_truths("mobile")
    backend = read_truths("backend")

    # Mobile side: wallet language must not promote the wallet to an
    # "authority" role. Scan for phrases like "wallet is the authority"
    # or "wallet authority".
    wallet_authority_drift = grep_lines(
        mobile,
        r"wallet\s+(?:is\s+the\s+)?authorit",
        flags=re.IGNORECASE,
    )
    assert not wallet_authority_drift, (
        "MOBILE_TRUTHS wallet drift — §10 / §2.5 describe the wallet as "
        "protocol identity (signs transactions, holds CAL). A phrase "
        "like 'wallet is the authority' inverts PROTOCOL_TRUTHS P13. "
        "Lines:\n  "
        + "\n  ".join(f"MOBILE_TRUTHS.md:{ln} {line}" for ln, line in wallet_authority_drift)
    )

    # Backend side: §8.2 must keep the "granted by chain / scoped by
    # ProgramConfig" direction intact. Look for both words — if either
    # disappears, the grant direction ambiguates.
    has_granted = "granted" in backend or "grants" in backend
    has_scoped = "scoped" in backend
    has_program_config = "ProgramConfig" in backend
    assert has_granted and has_scoped and has_program_config, (
        "BACKEND_TRUTHS §8.2 grant-direction drift — at least one of "
        f"{{granted: {has_granted}, scoped: {has_scoped}, "
        f"ProgramConfig: {has_program_config}}} is missing. §8.2 relies "
        "on the chain-→-backend arrow being legible."
    )

    # Backend side: §8 must carry the arrow-of-truth phrasing that
    # dispatcher reviewers read for direction coherence.
    assert "chain → backend → rider" in backend, (
        "BACKEND_TRUTHS §8.2 drift — the canonical arrow-of-truth "
        "phrase 'chain → backend → rider' is missing. This phrase is "
        "what the dispatcher greps for when reviewing authority "
        "language across PRs."
    )


def test_bridge_attestation_loop_cites_protocol_ride_attestation() -> None:
    """MOBILE §2.4 + BACKEND §6.3 ↔ PROTOCOL_TRUTHS §2.3 — STATUS: PASS.

    MOBILE §2.4 Attestation Stamp: device-side half of the loop,
    explicitly cites PROTOCOL_TRUTHS §2.3.
    BACKEND §6.3 Hash Compare: backend closes the loop by recompute +
    compare.
    Bridge: both must cite the same PROTOCOL_TRUTHS §2.3 anchor so a
    reader following either lane lands on the same parent definition.
    """
    mobile = read_truths("mobile")
    backend = read_truths("backend")

    # Mobile side: §2.4 Attestation Stamp body references §2.3.
    assert re.search(r"PROTOCOL_TRUTHS\s*§\s*2\.3", mobile), (
        "MOBILE_TRUTHS §2.4 drift — Attestation Stamp must cite "
        "PROTOCOL_TRUTHS §2.3 so the device-side half lands on the "
        "canonical definition."
    )
    # Backend side: §6.3 or §2.2 must cite §2.3 (the parent definition
    # of Ride Attestation). BACKEND_TRUTHS currently cites §2.3 in §2.2.
    assert re.search(r"PROTOCOL_TRUTHS\s*§\s*2\.3", backend), (
        "BACKEND_TRUTHS drift — the attester role (§2.2 / §6.3) must "
        "cite PROTOCOL_TRUTHS §2.3 so backend attestation work lands "
        "on the same parent definition the mobile side cites."
    )


def test_bridge_ride_event_time_threaded_through_both_lanes() -> None:
    """MOBILE §3.1 + BACKEND §3.1 ↔ ride-event-time — STATUS: PASS.

    MOBILE §3.1: Device wall-clock is authoritative for ride start / end
    and canonical ride timestamps.
    BACKEND §3.1: `completed_at` is derived from the ride file and is
    authoritative for economic settlement.
    Bridge: the ride-event-time path threads cleanly: mobile stamps
    wall-clock at ride stop; that value lands inside the ride file;
    backend reads `completed_at` from the file (not from upload).

    This test asserts both docs name their side's clock concept with
    the language a reader needs to trace the bridge.
    """
    mobile = read_truths("mobile")
    backend = read_truths("backend")

    # Mobile §3 names three clocks and wall-clock is authoritative for
    # ride start/end.
    assert "Device Wall-Clock" in mobile or "device wall-clock" in mobile.lower(), (
        "MOBILE_TRUTHS §3 drift — 'Device Wall-Clock' is the canonical "
        "label; the bridge to BACKEND §3.1 depends on it."
    )
    assert re.search(r"ride\s+start\s+and\s+end", mobile, re.IGNORECASE), (
        "MOBILE_TRUTHS §3.1 drift — 'ride start and end' authority claim "
        "is missing; backend/§3 bridge loses its mobile anchor."
    )

    # Backend §3.1 explicit: completed_at from the file.
    assert re.search(r"completed_at", backend), (
        "BACKEND_TRUTHS §3 drift — `completed_at` (ride file event "
        "time) is missing. Bridge to MOBILE §3.1 breaks."
    )
    assert re.search(
        r"ride\s+file|the\s+file\s+itself|from\s+the\s+file",
        backend,
        re.IGNORECASE,
    ), (
        "BACKEND_TRUTHS §3.1 drift — 'completed_at is sourced from the "
        "ride file' assertion is missing. That is the anchor that "
        "connects backend's economic clock to mobile's wall-clock."
    )


# ===========================================================================
# Class 2 — Cross-lane code alignment
# ===========================================================================


# ---------------------------------------------------------------------------
# Mobile hash serialization symmetry — mobile ship hex; backend expects
# hex-compatible input.
# ---------------------------------------------------------------------------


def test_mobile_preliminary_hash_serializes_as_64_char_lowercase_hex() -> None:
    """MOBILE §2.4 + §6 hash on wire — STATUS: PASS.

    Mobile's ``bytesToHex`` in ``mobile/src/lib/preliminaryHash.ts``
    produces 64 lowercase hex characters (SHA-256 = 32 bytes → 64 hex
    digits, padded with `0`). Backend consumers MUST be able to accept
    exactly this shape. A mobile-side drift into uppercase, 0x-prefix,
    base64, etc. silently breaks the attestation compare when it lands.
    """
    source = (mobile_src() / "lib" / "preliminaryHash.ts").read_text(encoding="utf-8")

    # bytesToHex must lowercase-pad via toString(16).padStart(2, '0').
    # A drift to toUpperCase() or a different radix changes the format
    # the backend sees.
    assert re.search(
        r"toString\s*\(\s*16\s*\)\s*\.\s*padStart\s*\(\s*2\s*,\s*['\"]0['\"]\s*\)",
        source,
    ), (
        "mobile/src/lib/preliminaryHash.ts drift — bytesToHex no longer "
        "emits lowercase-zero-padded hex. Backend §6.3 hash-compare "
        "expects 64 lowercase hex chars (SHA-256)."
    )
    assert "toUpperCase" not in source, (
        "mobile/src/lib/preliminaryHash.ts drift — bytesToHex must not "
        "emit uppercase hex. A mixed-case mobile hex vs a lowercase "
        "backend canonical hex compares as 'mismatch' even when equal."
    )


# ---------------------------------------------------------------------------
# Attestation envelope field name consistency — mobile emits snake_case;
# backend MUST read the same names. This is the leading drift candidate
# Tim called out.
# ---------------------------------------------------------------------------


def test_backend_upload_init_accepts_mobile_sent_fields() -> None:
    """MOBILE uploadQueue.buildUploadInitPayload ↔ BACKEND UploadInitRequest —
    STATUS: DRIFT (EXPECTED TO FAIL TODAY).

    Mobile's `buildUploadInitPayload` emits (per
    `mobile/src/services/uploadQueue.ts`):

        { file_type, file_hash, file_size,
          parser_version?, preliminary_ride_hash? }

    Backend's `UploadInitRequest` Pydantic model (per
    `backend/app/schemas.py`) declares:

        file_type, file_hash, file_size

    `parser_version` and `preliminary_ride_hash` are OPTIONAL on the
    mobile side — sent only when the ride stamped at stop. Backend's
    Pydantic model silently drops them (Pydantic default
    ``extra='ignore'``), meaning:

        * mobile sends the hash,
        * backend never sees it,
        * BACKEND_TRUTHS §6.3 'hash compare is the attestation gate'
          can never fire because the hash never reaches the compare
          function.

    This is the §6.3 PENDING state BACKEND_GATE_1 already documents,
    but that PENDING is one-sided. The other side — the mobile code
    already shipping the hash — makes this a cross-lane drift the
    alignment gate must surface: the bridge is half-built.

    Fix direction (Tim decides):
      A) Add `parser_version` and `preliminary_ride_hash` fields to
         ``UploadInitRequest`` so the backend accepts them, then wire
         them to ``ride_processor`` per §6.3 progressive tightening.
      B) Document that the optional fields are deliberately ignored
         until §6.3 lands (explicit `extra='ignore'` + a comment).
      C) Remove them from mobile until backend is ready, per
         MOBILE_TRUTHS §7 "say so loudly rather than silently orphan."

    Either way, mobile+backend must agree on the envelope. Today they
    disagree silently.
    """
    mobile_fields = field_names_in_mobile_upload_payload()
    backend_fields = set(backend_upload_init_request_fields())

    assert mobile_fields, (
        "mobile payload parser returned empty — scan may be stale; "
        "check mobile/src/services/uploadQueue.ts still declares "
        "buildUploadInitPayload."
    )
    assert backend_fields, (
        "backend schema parser returned empty — scan may be stale; "
        "check backend/app/schemas.py still declares UploadInitRequest."
    )

    # Every mobile-sent field must either (a) appear on the backend
    # model, or (b) the backend model explicitly declare
    # ``extra='allow'`` / ``extra='forbid'`` with a documented aliasing
    # story. Silent ignore is the drift state.
    policy = pydantic_extra_policy_for("UploadInitRequest")
    unacknowledged: list[str] = []
    for field_name in mobile_fields.keys():
        if field_name in backend_fields:
            continue
        unacknowledged.append(field_name)

    if not unacknowledged:
        return  # coherence holds

    if policy == "allow":
        # Backend explicitly accepts extras — it may be a deliberate
        # progressive-tightening posture; call it out but do not fail.
        # (If this ever becomes the state, upgrade the test to assert
        # the explicit Field aliases so the envelope shape stays
        # documented somewhere.)
        pytest.skip(
            "Backend UploadInitRequest declares extra='allow'; mobile-sent "
            f"fields {unacknowledged} are accepted opaquely. Flip this to "
            "an assertion once the fields land as typed Field entries."
        )

    # Default Pydantic behaviour is ``extra='ignore'`` — silently drop.
    # That is the drift state the gate surfaces.
    assert not unacknowledged, (
        "§6.3 hash-compare envelope DRIFT — mobile sends "
        f"{sorted(unacknowledged)} in the /rides/upload/init body, but "
        "backend's UploadInitRequest Pydantic model (backend/app/schemas.py) "
        "does not declare them. Pydantic default is extra='ignore' "
        f"(current policy: {policy!r}), so these fields are silently "
        "dropped on arrival.\n\n"
        "Mobile source: mobile/src/services/uploadQueue.ts::buildUploadInitPayload\n"
        "Backend source: backend/app/schemas.py::class UploadInitRequest\n"
        "Truth bridge: BACKEND_TRUTHS §6.3 says 'hash compare is the "
        "attestation gate'; today the hash never reaches the gate "
        "because the envelope drops it.\n\n"
        "Decision required: add the fields backend-side, remove them "
        "mobile-side, or document the progressive-tightening delay "
        "with extra='allow' + a Field comment."
    )


# ---------------------------------------------------------------------------
# parser_version naming + type consistency — mobile uses `parser_version`
# as an integer; backend internally uses `ride_parser_version` when
# persisting; the wire field should be one of the two consistently.
# ---------------------------------------------------------------------------


def test_parser_version_wire_name_agrees_across_lanes() -> None:
    """MOBILE uploadQueue ↔ BACKEND rides route — STATUS: DRIFT
    (EXPECTED TO FAIL TODAY).

    Mobile sends ``parser_version`` in the /rides/upload/init body.
    Backend's database column / internal field is named
    ``ride_parser_version`` (per `backend/app/routes/rides.py` and
    `backend/app/services/ride_processor.py`).

    The internal rename is fine — Pydantic supports aliasing. What is
    NOT fine is: there is no alias bridging mobile's `parser_version`
    into backend's `ride_parser_version`. The wire field never lands.

    This compounds the envelope drift above: even if backend started
    accepting the extra, the field name would need either:
      * an alias in UploadInitRequest (`parser_version` → internal
        `ride_parser_version`), OR
      * a rename on one side so both lanes agree on the wire name.

    Fix direction (Tim decides):
      * Prefer mobile's `parser_version` as the wire name (cleaner,
        matches PROTOCOL_TRUTHS §2.3 `parser_version` vocabulary).
      * Backend internally maps to `ride_parser_version` on persist.
      * Or: rename everything to `ride_parser_version` across lanes.
    """
    # Mobile side: payload uses `parser_version`.
    mobile_fields = field_names_in_mobile_upload_payload()
    assert "parser_version" in mobile_fields, (
        "mobile payload drift — `parser_version` no longer listed in "
        "buildUploadInitPayload; scan may be stale."
    )

    # Backend side: is there an alias mapping `parser_version` →
    # `ride_parser_version` in UploadInitRequest, or a field named
    # `parser_version` on it?
    schemas_source = (
        (mobile_src().parent.parent / "backend" / "app" / "schemas.py")
        .read_text(encoding="utf-8")
    )
    upload_init_block_match = re.search(
        r"class\s+UploadInitRequest\b[^\n]*:\s*\n(.*?)(?=^class\s|\Z)",
        schemas_source,
        re.DOTALL | re.MULTILINE,
    )
    assert upload_init_block_match, (
        "could not find UploadInitRequest class block in schemas.py"
    )
    upload_init_body = upload_init_block_match.group(1)

    # Either a direct `parser_version` field, or an aliased route via
    # AliasChoices("parser_version", "ride_parser_version") / similar.
    has_direct = re.search(r"^\s{4}parser_version\s*:", upload_init_body, re.MULTILINE)
    has_alias = re.search(
        r"AliasChoices\([^)]*parser_version[^)]*\)|alias\s*=\s*['\"]parser_version['\"]",
        upload_init_body,
    )

    assert has_direct or has_alias, (
        "parser_version wire-field DRIFT — mobile sends "
        "`parser_version` in the /rides/upload/init body, but backend's "
        "UploadInitRequest (backend/app/schemas.py) declares neither a "
        "`parser_version:` field nor an `AliasChoices('parser_version', "
        "...)` route for it.\n\n"
        "Internal backend column is `ride_parser_version` "
        "(backend/app/routes/rides.py line with "
        "`data.get('ride_parser_version')`), so even if the envelope "
        "accepted extras, the field would not bridge to the attester.\n\n"
        "Mobile source: mobile/src/services/uploadQueue.ts:138 "
        "`payload.parser_version = args.parserVersion`\n"
        "Backend source: backend/app/schemas.py::class UploadInitRequest\n\n"
        "Decision required: pick one canonical wire name "
        "(`parser_version` per PROTOCOL_TRUTHS §2.3 / mobile is "
        "cleanest), and alias on the persistence side if needed."
    )


def test_parser_version_type_is_integer_on_both_sides() -> None:
    """MOBILE canonicalize ↔ BACKEND ride_processor — STATUS: PASS.

    Mobile exports immutable integer parser constants and aliases CURRENT to
    the current constant. Backend consumes the resolved value as Python `int`. On-chain per
    the brief is u32. This test pins both language-level types to
    match: any silent widen (mobile → float) or signedness change
    (backend → negative sentinel) would corrupt the comparison.
    """
    mobile_source = (mobile_src() / "lib" / "canonicalize.ts").read_text(encoding="utf-8")
    # The immutable parser constants must be integer literals, not float / string / bigint.
    m = re.search(
        r"export\s+const\s+PARSER_VERSION_V5\s*=\s*(\S+?)\s*;",
        mobile_source,
    )
    assert m, (
        "mobile/src/lib/canonicalize.ts drift — PARSER_VERSION_V5 "
        "constant declaration missing. Bump-in-lockstep contract with "
        "the Rust parser breaks."
    )
    value_literal = m.group(1)
    assert re.fullmatch(r"\d+", value_literal), (
        f"parser_version mobile-side type drift — PARSER_VERSION_V5 "
        f"is '{value_literal}', not a plain integer literal. Backend "
        "consumes as Python int; a float or string would silently mis- "
        "compare on the attestation hash."
    )
    assert re.search(
        r"export\s+const\s+CURRENT_PARSER_VERSION\s*=\s*PARSER_VERSION_V5\s*;",
        mobile_source,
    ), "CURRENT_PARSER_VERSION must be an explicit alias of immutable V5"

    # Backend side: the ride_processor types parser_version: int.
    ride_processor_source = (
        (mobile_src().parent.parent / "backend" / "app" / "services" / "ride_processor.py")
        .read_text(encoding="utf-8")
    )
    assert re.search(r"parser_version\s*:\s*int", ride_processor_source), (
        "backend/app/services/ride_processor.py drift — "
        "`parser_version: int` type annotation missing on the "
        "OnchainRideIdentity dataclass field. A widen to str / Optional "
        "would mask mobile-side integer drift."
    )


# ---------------------------------------------------------------------------
# completed_at boundary — mobile does NOT send completed_at; backend
# does NOT take it from the upload body.
# ---------------------------------------------------------------------------


def test_completed_at_is_not_a_mobile_wire_field() -> None:
    """MOBILE §3 + BACKEND §3.1 boundary — STATUS: PASS.

    BACKEND_TRUTHS §3.1: `completed_at` is derived from the parsed ride
    file, authoritative for economic settlement. Mobile's job per
    MOBILE_TRUTHS §6 + §7 ends at producing the file + stamp + upload.
    A `completed_at` field coming from mobile would be upload-time
    masquerading as event-time — the exact drift BACKEND_TRUTHS §13.2
    flags as "upload-time-as-economic-time confusion."

    This test asserts mobile does NOT include `completed_at` in the
    upload envelope.
    """
    mobile_fields = field_names_in_mobile_upload_payload()
    assert "completed_at" not in mobile_fields, (
        "MOBILE wire envelope drift — buildUploadInitPayload now "
        "includes `completed_at`. Per BACKEND_TRUTHS §3.1, that value "
        "must be derived from the ride FILE on the backend, not from "
        "the mobile envelope. A mobile-sent completed_at would be "
        "upload-time-as-economic-time confusion (BACKEND_TRUTHS §13.2)."
    )


def test_backend_upload_init_does_not_accept_completed_at_from_body() -> None:
    """MOBILE §3 + BACKEND §3.1 boundary — STATUS: PASS.

    Counterpart to the mobile-side test: backend's UploadInitRequest
    must not declare a `completed_at` field. Backend §3.1 sources
    completed_at from the ride file during processing, never from the
    upload request.
    """
    backend_fields = set(backend_upload_init_request_fields())
    assert "completed_at" not in backend_fields, (
        "BACKEND UploadInitRequest drift — `completed_at` field "
        "declared in `backend/app/schemas.py::UploadInitRequest`. Per "
        "BACKEND_TRUTHS §3.1, `completed_at` must come from the ride "
        "file itself, not from the upload body. Accepting it from the "
        "body re-opens the upload-time-as-economic-time drift §13.2 "
        "flags for repair."
    )


# ===========================================================================
# Class 3 — Semantic bridge assertions
# ===========================================================================


# ---------------------------------------------------------------------------
# Attestation lineage — the code paths that bridge the three docs exist.
# This is the static-scoped-down version of the full integration test the
# brief flags as possibly-too-ambitious.
# ---------------------------------------------------------------------------


def test_attestation_lineage_path_exists_across_lanes() -> None:
    """MOBILE §6 → BACKEND §6.3 → PROTOCOL §2.3 lineage — STATUS: PASS.

    Static bridge assertion: the three load-bearing symbols exist.

      1. Mobile: `computePreliminaryHash` is exported from
         `mobile/src/lib/preliminaryHash.ts`, and `stopRecording` in
         `mobile/src/services/gpsRecording.ts` calls it.
      2. Backend: `evaluate_preliminary_attestation` is declared
         (function or TODO placeholder) in
         `backend/app/services/ride_attester.py`.
      3. On-chain submission: `send_record_ride` exists in
         `backend/app/solana_direct.py`.

    A missing symbol on any row breaks the lineage. This is not an
    integration test (that requires a live ride file); it is the
    minimum static proof that the bridge is wired in source.
    """
    missing: list[str] = []

    # 1. Mobile preliminary hash module exports computePreliminaryHash.
    mobile_hash_src = (mobile_src() / "lib" / "preliminaryHash.ts").read_text(
        encoding="utf-8"
    )
    if not re.search(
        r"export\s+async\s+function\s+computePreliminaryHash\b",
        mobile_hash_src,
    ):
        missing.append(
            "mobile/src/lib/preliminaryHash.ts: "
            "`computePreliminaryHash` is not exported"
        )

    # And stopRecording calls it.
    gps_src = (mobile_src() / "services" / "gpsRecording.ts").read_text(
        encoding="utf-8"
    )
    if "computePreliminaryHash" not in gps_src:
        missing.append(
            "mobile/src/services/gpsRecording.ts: `stopRecording` does not "
            "call `computePreliminaryHash` (MOBILE §6 Every Stop Path Stamps)"
        )

    # 2. Backend attester declares evaluate_preliminary_attestation
    # (function or documented TODO — BACKEND §6.3 is PENDING today).
    attester_path = (
        mobile_src().parent.parent / "backend" / "app" / "services" / "ride_attester.py"
    )
    attester_src = attester_path.read_text(encoding="utf-8") if attester_path.exists() else ""
    if "evaluate_preliminary_attestation" not in attester_src:
        missing.append(
            "backend/app/services/ride_attester.py: "
            "`evaluate_preliminary_attestation` symbol/TODO missing — "
            "BACKEND_GATE_1 §6.3 PENDING sentinel depends on it being "
            "named here."
        )

    # 3. On-chain submit function exists.
    solana_direct_path = (
        mobile_src().parent.parent / "backend" / "app" / "solana_direct.py"
    )
    solana_src = solana_direct_path.read_text(encoding="utf-8")
    if not re.search(r"async def\s+send_record_ride\b", solana_src):
        missing.append(
            "backend/app/solana_direct.py: `send_record_ride` async "
            "function missing — on-chain attestation submission path "
            "broken (PROTOCOL §2.3 bridge)."
        )

    assert not missing, (
        "Attestation lineage drift — at least one symbol in the "
        "MOBILE §6 → BACKEND §6.3 → PROTOCOL §2.3 chain is missing:\n  "
        + "\n  ".join(missing)
    )


# ---------------------------------------------------------------------------
# Arrow of authority — chain → backend → rider audits.
# ---------------------------------------------------------------------------


def test_arrow_of_authority_consistent_across_lanes() -> None:
    """MOBILE §10 / §2.5 + BACKEND §8.2 + PROTOCOL P13 — STATUS: PASS.

    The grant direction is single: chain → backend → rider audits. No
    TRUTHS doc may carry language pointing the other way:

      * Rider does NOT delegate to backend.
      * Backend does NOT own authority (it is granted).
      * Wallet does NOT impersonate authority (it is identity).

    Heuristic scan: the phrase 'rider delegates to the backend' or
    'backend holds authority' or 'wallet is the authority' would all
    invert the grant direction.
    """
    forbidden_patterns = [
        (
            r"rider\s+delegates?\s+to\s+(?:the\s+)?backend",
            "Rider cannot delegate to backend — the grant direction is "
            "chain → backend → rider audits (PROTOCOL_TRUTHS P13, "
            "BACKEND_TRUTHS §8.2).",
        ),
        (
            r"backend\s+holds\s+authorit",
            "Backend does not hold authority — authority is granted "
            "scope by the chain's ProgramConfig (BACKEND_TRUTHS §8.2).",
        ),
        (
            r"wallet\s+(?:is\s+)?the\s+authorit",
            "Wallet is protocol identity, not authority "
            "(MOBILE_TRUTHS §2.5, §10.2).",
        ),
    ]
    offenders: list[str] = []
    for lane in ("protocol", "mobile", "backend"):
        doc = read_truths(lane)
        for pattern, rationale in forbidden_patterns:
            for lineno, line in grep_lines(doc, pattern, flags=re.IGNORECASE):
                offenders.append(
                    f"{lane.upper()}_TRUTHS.md:{lineno} "
                    f"`{line.strip()}`\n      → {rationale}"
                )

    assert not offenders, (
        "Arrow-of-authority inversion in TRUTHS docs:\n  "
        + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# Numeric key helper for sorted section listing in error messages.
# ---------------------------------------------------------------------------


def _numeric_key(s: str) -> tuple[int, ...]:
    return tuple(int(p) for p in s.split("."))
