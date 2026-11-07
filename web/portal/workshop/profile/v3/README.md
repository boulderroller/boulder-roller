# Rider Profile Candidate V3

Local workshop: `http://localhost:4335/?surface=profile&variant=profile-v3&scenario=recorded&viewer=owner`

One Profile page shares its identity, terrain and navigation across Overview, Rides, Training and Portfolio. The workshop tab selector and product tabs stay synchronized. Overview pairs the retained Ride map ground with measured climb efforts and one concise ride summary. Phone puts those efforts in a horizontally browsable strip below the map.

## Data boundary

The default is the retained **In the bag** recording, 28 August 2016: 16,082 supplied GPS/measurement samples and three recorded climb intervals. The source has no rider name, portrait, current sporting rank or balance. V3 displays an anonymous rider and omits those claims. One recording is explicitly one ride shown, not a complete month or lifetime total. Portfolio demonstrates the unavailable state; no live account or economic service is connected.

Sparse, empty and private scenarios are supplied state studies. Imports use the V3 schema and namespace, validate the nested recording, and preserve declared provenance. A private study cannot contain hidden recording data. Geographic links to the three known climbs require the retained sample geometry and interval definitions; short IDs alone are insufficient.

## Interaction evidence

- 155 workshop tests pass; workshop typecheck and build pass. Focused reds covered model introduction, imported-ID/deep-link recovery and false geographic association. The shared navigation assertion now expects the carried Map V7.
- Exact 1440×1000 and 390×844 captures are in `evidence/`, together with the historical Strava squint comparison.
- Browser checks exercised actual tabs and dropdown synchronization, arrow/Home/End keys, ride search and clearing, owner/visitor restrictions, private/empty/sparse/loading/error/offline states and retry.
- A valid custom recording imported from a local JSON file survives reload; invalid candidate JSON is rejected. Switching V2 → V3 keeps V3's recording.
- Wises opens its measured 3:55 effort in retained Ride V13. Browsing Power and returning restores Profile; Training's return restores its invoking focus. The isolated Ride host supplies no illustrative identity or CAL. Browser Back from Map V7 restores the selected Profile hill. No browser warnings/errors were observed in the final review.

## Integration

Own code is confined to `workshop/profile/v3/` plus `tests/profile-v3.test.ts`. Retained Profile V1/V2 and all Ride, Feed, Climb and Map candidate implementations are unchanged. The checkout carries Profile V2 dependency `bf60467320acc8ed4ec4fab4f108f34ecae1486e` and settled Map V7 alignment `73b57bd26882d89086ff383ac50a68ddf56662ea`, combined at `d269578a3`.

Candidate code/tracker and shared registration are separate commits. Reconcile only the small Profile imports/preview dispatch in `main.tsx`, Profile destination in `roomRegistry.ts`, and Map-default expectation in `tests/shared-navigation.test.ts`; preserve the integrating task's newer registrations. Do not replace another task's harness wholesale. Run from `web/portal` with `npm run workshop -- --host localhost --port 4335 --strictPort` (or another free port).

Bead: `boulderroller-v2-jnqu9`. Branch: `codex/jnqu9-profile-v3`. Sibling checkout: `/Users/gabetemp/curahee/BoulderRoller-worktrees/profile-v3`. This is a local candidate; production integration and deployment remain separate.
