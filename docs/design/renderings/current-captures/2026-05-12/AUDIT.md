# BR Current Surface Audit - 2026-05-12

Use this as the bridge from screenshots to design-system work. The captures are
not a pitch deck and not a prompt for new fantasy screens. They are the current
product evidence we mark up before touching implementation.

## How To Use This Set

Read every surface through four actions:

- Preserve: keep the real product strengths.
- Reduce: remove visual noise, crypto/admin drift, and overbuilt boxes.
- Clarify: make the hierarchy match the BR identity contract.
- Propose: only introduce a new primitive when the current product has a real
  gap or an existing component clearly cannot carry the job.

The first implementation pass should be conservative: refine current surfaces
around a shared grammar before introducing novel views.

## Global Read

The product is closest when it feels like an athletic record with consequences.
RideView, the route map, the climb table, and leaderboard rows are the best raw
material. The product drifts when record/economy facts become square metadata
blocks, when labels sound internal, or when mobile inherits desktop density
without a native interaction model.

Preserve:
- Athletic object first: ride, climb, rider, route, effort, result.
- Dense but legible stats, tables, leaderboards, maps, and elevation profiles.
- CAL/vault/proof as compact consequences attached to athletic objects.
- The current restrained green/brass accent family, used sparingly.

Reduce:
- Generic ledger/admin card grids.
- Technical labels in primary product surfaces.
- Too many equal-weight bordered boxes.
- Large empty placeholders that dominate over ride or climb evidence.
- Mobile desktop chrome squeezed into narrow viewports.

Clarify:
- Maps/elevation should lead ride and climb understanding.
- Proof and economy should read as a receipt layer, not as the main app.
- Every action label should be rider-native.
- Each surface should make its object obvious within two seconds.

## FeedView Item

Capture: `desktop-feedview-item.png`

Preserve:
- Human rider header plus ride title is the right first read.
- Route preview as the card's main visual is strong.
- `+96 CAL` works as a compact consequence marker.
- Kudos/comment/view actions are simple enough to scan.

Reduce:
- The gray dead area in the route preview makes the card feel unfinished.
- Technical map microcopy should not sit in the feed primary image.
- The card border and map treatment are a little too dry for a social object.

Clarify:
- The feed item should read as "rider did a ride" before "ride produced CAL."
- CAL should stay attached to the ride stats, not become a token tile.
- Comment and kudos affordances should feel human, not infrastructural.

Propose:
- A feed activity card primitive: rider header, title, compact stat row, route
  preview, consequence chip, and actions.

## RideView

Captures: `desktop-rideview.png`, `desktop-rideview-vault-panel.png`

Preserve:
- Ride title, date, counted status, core metrics, route map, and top result are
  the right backbone.
- The side-panel idea is a good place for vault/economy consequence on desktop.
- The climb result strip makes the ride feel consequential without taking over.

Reduce:
- Too many tiny title-adjacent controls compete with the ride identity.
- The map is large but visually washed out; the route line carries too much
  alone.
- The current page feels like stacked bordered records instead of one coherent
  ride receipt.

Clarify:
- The ride should lead with identity plus route context, then metrics, then
  climb/economy outcomes.
- Record/proof controls belong as receipt actions, not hero controls.
- The vault panel should explain what this ride changed: counted CAL, matched
  climb, rank, vault status.

Propose:
- Ride header primitive.
- Route map primitive with stronger route/elevation relationship.
- Consequence strip for CAL, counted climbs, and record state.
- Desktop receipt side panel for proof/economy details.

## Climb Table / Inspector

Capture: `desktop-climb-table-current.png`

Preserve:
- The selected climb row plus elevation profile is one of the strongest current
  design-system candidates.
- Dense result values are appropriate here: time, speed, VAM, rank.
- The table can carry repeated scanning without feeling like marketing.

Reduce:
- `Segment spine` reads internal.
- The chart is useful but too compressed to feel like the climb's shape.
- `Clear` is mechanically accurate but not the best product language for a
  selected climb state.

Clarify:
- This is not currently a popout. It is an expanded climb card inside RideView.
- The design-system job is to turn this into a reusable Climb Inspector pattern:
  climb identity, elevation, rider result, rank, and vault action.
- Desktop can become a popout or side inspector later; mobile should become a
  bottom sheet, but both should preserve this data spine.

Propose:
- Climb Inspector primitive, with desktop panel and mobile sheet variants.

## ClimbView

Captures: `desktop-climbview.png`, `desktop-climbview-record-economy-module.png`

Preserve:
- The page correctly treats a climb as an object with record, leaderboard, vault,
  legend, and week state.
- The leaderboard should stay central.
- The current compact stats are useful and serious.

Reduce:
- The four-box record module feels like admin metadata, not rider meaning.
- `Vault 1` is too system-ish as primary user-facing copy.
- Long rider handles expose why truncation and display-name strategy need rules.
- The page underuses map/elevation for a place/object surface.

Clarify:
- ClimbView should answer: what is this climb, what is the shape, who owns the
  result, where do I stand, and what is at stake?
- Vault and local legend should attach to the climb identity, not become a
  generic finance panel.
- Economy copy should be short and rider-native: active vault, counted efforts,
  current legend, open week.

Propose:
- Climb hero primitive: name, location, distance, gain, grade, best time,
  entries, vault/week state.
- Climb economy strip that can expand into the future econ popout.
- Leaderboard row grammar with display-name, handle, rank, time, power, VAM.

## RiderView

Capture: `desktop-riderview.png`

Preserve:
- Rider identity, public/private state, follow/share/report, stats, and tabs are
  the right surface family.
- The profile should feel like a rider record, not a wallet page.
- Compact lifetime stats are useful.

Reduce:
- The giant empty avatar block dominates too much when no photo exists.
- `Rider type not set` feels like setup/admin state on a public profile.
- Equal-weight stat boxes make the page colder than it needs to be.
- Empty or fixture-bad values such as `0m` time need a display rule before this
  becomes a design-system primitive.

Clarify:
- Public rider pages should emphasize identity, activity, achievements, and
  climb relationship before account completeness.
- Owner-only setup prompts should not leak into the public profile grammar.
- Social actions should feel calm and trustworthy.

Propose:
- Rider header primitive with graceful no-avatar state.
- Rider stats row with hide/empty rules.
- Public profile activity module that centers rides and climb standing.

## Responsive Portal Mobile

Captures: `responsive-mobile-rideview.png`, `responsive-mobile-climb-table-current.png`,
`responsive-mobile-climb-econ-current.png`, `responsive-mobile-climbview.png`,
`responsive-mobile-profileview.png`

Preserve:
- The current responsive portal proves the same product objects can stack.
- Core stats remain readable at phone width.
- The climb/economy sequence exists and can inform native mobile.

Reduce:
- Top chrome is crowded.
- Horizontal tabs clip and feel like desktop navigation squeezed onto mobile.
- Large bordered blocks stack into a long administrative scroll.
- Climb titles and tables need mobile-specific line and density rules.

Clarify:
- These are not native mobile captures.
- Native mobile should use detail headers, sheets, and focused action bars
  rather than copying the portal shell.
- Mobile climb inspector and econ popout should be bottom-sheet primitives, not
  full desktop panels shrunk down.

Propose:
- Capture native mobile after auth/test fixture access is available.
- Define mobile detail header, climb inspector sheet, and economy sheet as
  mobile-native primitives.

## Explicit Gaps

Native mobile requested views:
- Not captured. The simulator is currently at LoginScreen.
- Do not use responsive portal screenshots as native truth.
- Next step is a native fixture/auth path for RideDetail, ClimbDetail, Profile,
  climb inspector, and econ sheet captures.

Climb economy popout:
- Not built.
- Do not invent a finished view.
- Design it only from current constraints: ClimbView, RideView VaultPanel,
  VaultView, and the climb table's selected state.

## Next Design-System Pass

1. Mark the captures with Preserve / Reduce / Clarify / Propose notes.
2. Convert repeated needs into primitives: Ride Header, Route Map, Consequence
   Strip, Climb Inspector, Climb Economy Strip, Rider Header, Leaderboard Row.
3. Define copy rules for labels currently reading as internal: segment spine,
   vault IDs, record module labels, empty values, technical map labels.
4. Define mobile-specific primitives separately from responsive portal.
5. Only then start implementation, beginning with the highest-leverage shared
   primitives rather than one-off page restyles.
