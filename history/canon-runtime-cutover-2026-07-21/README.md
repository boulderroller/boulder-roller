# V4-B Chain Metric Projection Evidence — 2026-07-21

The ratified registry keeps precise compiler measurements. V4-B accounts carry
the deterministic integer projection
`boulderroller_chain_metric_projection_v1`:

```
Q(x, scale) = floor(x * scale + 0.5)
```

The calculation uses nonnegative decimal arithmetic. Length uses scale 1,
vertical gain uses scale 10, and average gradient uses scale 100. The resulting
fields are whole meters, decimeters, and gradient basis points. They populate
the existing `u32`, `u32`, and `u16` registration arguments and do not alter the
D12 bytes, commitment SHA-256, Climb PDA, version-index PDA, or program ABI.

## Red evidence

Before this projection was introduced, the exact-scaling encoder rejected the
real Jefferson Street / North Woodbine Avenue values `2031.31 m`, `87.36 m`,
and `4.301%` as not exactly representable. The new real-row test therefore
failed with `CanonVaultActivationError: ratified Climb metrics are invalid` on
the pre-change Python encoder. Independent replay-resolution verification found
the same launch blocker across the unchanged 57-candidate denominator: 57
fractional lengths, 53 non-decimeter vertical gains, and 55 non-basis-point
gradients made all 57 candidates fail the old exact-scaling path.

## Pinned launch manifest

`chain-metric-projection-launch-manifest.json` is generated only through
`tools/corpus/canon_traversal_replay.py::resolve_launch_canon_candidates` and
contains no ride or rider identifiers. Its source hashes are:

- applied canon report: `de67892dc600affd97e0a5158f3a369ca29777b214ecce41be0e47060736bf0e`
- review labels: `77fbdcc691de9d82124f3d848035f103e5433c6ef2bbe3d8bd64782041c4fdd9`

The resolver audit is 44 exact-lineage approvals, 15 boundary ratifications, 2
locked July 18 carries, 0 pending approvals, and 57 resolved candidates. Each
row preserves raw metrics and records the expected integer projection. The
canonical candidate payload digest is
`da93ce9735a7e609248b67d8f7c6d1d4ea53d8f017e8710e1e76aec20cdc9adb`.
