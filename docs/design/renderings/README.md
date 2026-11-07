# BR Identity Calibration Artifacts

Internal artifacts for calibrating the BR design-system push.

These are working aids for product/design/frontend taste alignment before token
and component work begins. The exploratory boards and packet are taste
references, not app code or current-app evidence, and not external presentation
material. The `current-captures/` set is the grounded current-UI reference.

## Files

- `br-identity-renderings.html` - editable HTML/CSS rendering board
- `br-identity-desktop.png` - desktop screenshot capture
- `br-identity-mobile.png` - narrow/mobile screenshot capture
- `br-identity-refinement-board.html` - refined pass with beauty, surface, stress, and mobile sections
- `br-identity-refined-desktop.png` - refined full desktop screenshot capture
- `br-identity-refined-tablet.png` - refined tablet-width screenshot capture
- `br-identity-refined-mobile.png` - refined narrow/mobile screenshot capture
- `br-identity-interactions-board.html` - interaction pass with climb inspector, explorer, object pages, vocabulary, and mobile sheet
- `br-identity-interactions-desktop.png` - interaction desktop screenshot capture
- `br-identity-interactions-mobile.png` - interaction narrow/mobile screenshot capture
- `br-identity-state-range-board.html` - live recording, processing, comments, and dark-mode range pass
- `br-identity-state-range-desktop.png` - state-range desktop screenshot capture
- `br-identity-state-range-mobile.png` - state-range narrow/mobile screenshot capture
- `BR_IDENTITY_VISUAL_PACKET_2026-05-12.pptx` - editable 6-page internal calibration packet
- `current-captures/2026-05-12/` - current route/component captures for the next design-system audit
- `current-captures/2026-05-12/AUDIT.md` - preserve/reduce/clarify/propose audit of those captures

## Intent

Turn `docs/design/BR_IDENTITY_SYSTEM.md` into a small ruler for judging current
portal/mobile surfaces:

- athletic record first
- maps, elevation, stats, and leaderboards as the main visual language
- proof/status as quiet receipt markers
- CAL/vault/legend as attached consequences of rides and climbs
- no invented screens, fake product states, or fake data
- BoulderScan kept out of the BR app packet as a separate product-language pass

## Exploratory Boards

The HTML boards are exploratory static renderings. They can help discuss taste,
but they must not outrank current app captures, code-backed behavior, or the
identity-system rules.

- beauty pass: map-first ride record, restrained color, quieter panels
- surface pass: feed, ride detail, climb detail, and portfolio as separate families
- stress pass: needs-review, not-counted, no-vault, and long-name states
- climb-table selected-row popout on desktop
- climb inspector bottom sheet on mobile
- map-led climb explorer
- climb/vault object page
- live recording cockpit
- post-ride record-building state
- comments and activity pulse
- dark-mode activity record treatment

## Calibration Packet

The PowerPoint packet is intentionally short and internal. It is a 6-page design
system calibration sheet:

- purpose and truth boundary
- taste hierarchy
- type and density
- color, containers, and maps
- primitive map for existing surfaces
- red lines before implementation

## Current Captures

`current-captures/2026-05-12/` is the grounded reference set for the next pass.
It uses current portal code with API-contract fixture data, and labels gaps
instead of pretending unbuilt popouts already exist.

Use these captures for `Preserve / Reduce / Clarify / Propose` markup. Do not
treat responsive portal screenshots as native mobile app truth.
