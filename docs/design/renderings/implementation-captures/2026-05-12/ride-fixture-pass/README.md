# Ride Fixture Pass

Candidate implementation capture for the RideView composition pass.

Scope:
- One unified ride fixture with a titlebar identity/actions row
- Split left ride context and right metric system
- White empirical metric row, grey performance/economy band
- Show More / Show Less secondary stats
- Top results integrated into the fixture before the map
- Timestamp replaces duplicate rider name above the activity title
- Cleaner left rail and flatter mobile/titlebar actions

Baseline:
- `docs/design/renderings/implementation-captures/2026-05-12/ride-map-header-pass/desktop-rideview.png`
- `docs/design/renderings/implementation-captures/2026-05-12/ride-map-header-pass/responsive-mobile-rideview.png`

Candidate captures:
- `03-desktop-rideview.png`
- `04-desktop-rideview-stats-expanded.png`
- `11-responsive-mobile-rideview.png`
- `12-responsive-mobile-rideview-stats-expanded.png`

Read:
- Better: RideView now behaves as one activity fixture instead of a stack of separate boxes.
- Better: primary ride facts and secondary performance/economy metrics are visually separated without new product claims.
- Better: duplicated rider identity is removed from the body; the titlebar owns rider/type, while the body owns time/title/source.
- Watch: titlebar density and the left-column whitespace still need taste review against real rider/avatar/media states.
