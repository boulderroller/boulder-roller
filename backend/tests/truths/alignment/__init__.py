"""PROTOCOL_TRUTHS_ALIGNMENT_GATE — cross-lane coherence checks.

Verifies that MOBILE_TRUTHS + BACKEND_TRUTHS do not drift from
PROTOCOL_TRUTHS, and that the three docs + the code across mobile + backend
remain internally consistent.

In-lane invariants live in:
    * backend/tests/truths/test_backend_truths_gate1.py (BACKEND_GATE_1)
    * mobile/src/__tests__/truths/gate1/truths.gate1.test.ts (MOBILE_GATE_1)

This gate catches drift BETWEEN the lanes — field name mismatch, §N
link-rot across the trio, contradictions, semantic bridge failures.

See docs/design/PROTOCOL_TRUTHS_ALIGNMENT_GATE.md for the coverage matrix
and any currently-surfaced drift.
"""
