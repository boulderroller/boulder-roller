# BR Core Surface Captures - 2026-05-12

These are calibration references for design-system work.

Boundary:
- Current portal captures use real `web/portal` routes and components.
- Data is API-contract fixture data, shaped from the existing portal route-shell test harness.
- Responsive mobile captures are the portal at a mobile viewport. They are not native mobile app captures.
- Native mobile detail/profile captures are still missing because the booted simulator is at `LoginScreen`.
- Climb economy popouts are unbuilt gaps. Use current `ClimbView`, `RideView` vault panel, and `VaultView` as constraints before proposing a primitive.

Capture list:
- `desktop-feedview.png`
- `desktop-rideview.png`
- `desktop-climb-table-current.png`
- `desktop-climbview.png`
- `desktop-climbview-record-economy-module.png`
- `desktop-rideview-vault-panel.png`
- `desktop-feedview-item.png`
- `desktop-riderview.png`
- `desktop-vaultview-economy-reference.png`
- `responsive-mobile-rideview.png`
- `responsive-mobile-climb-table-current.png`
- `responsive-mobile-climb-econ-current.png`
- `responsive-mobile-climbview.png`
- `responsive-mobile-profileview.png`

See `manifest.json` for source file mapping and status labels.

Use `AUDIT.md` for the preserve/reduce/clarify/propose read before any
implementation pass.
