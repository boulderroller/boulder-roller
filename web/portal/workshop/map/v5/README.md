# Map Candidate V5

Run `npm run workshop -- --port 4325` from `web/portal`.
Open <http://localhost:4325/?surface=map&variant=map-v5&scenario=wises&viewer=rider&origin=43f15658-a824-438d-9925-e61c67ddabe9>.

## Design and source boundaries

V5 refines V4's existing composition. All ground fill colors, vegetation, water, contours, accepted type and RankMark assets remain intact. Real hillshade strength changes modestly from .70/.50/.35 to .74/.57/.40 at zooms 10/14/16. Camera rotation and pitch remain disabled.

List profiles are larger, 72 by 44, and use a consistent fourfold vertical exaggeration relative to distance. A steep profile scales both axes together to fit; it does not independently stretch its height to match a gentle hill. Every supplied sample remains in the shape. Selected-card charts grow from 64 to 96 pixels on desktop and 54 to 78 on phone, retaining labeled distance and elevation scales. Missing profiles stay absent. Phone framing reserves slightly more room for the taller card; the expanded phone list still folds the selected profile away.

Landmarks use only named features in CARTO's existing `poi` tiles: museums, castle/ruin-class places and specifically classified viewpoints from zoom 14; shelters from zoom 15. No routine businesses or manually positioned points were added. Named nearby landmarks are absent from the inspected zoom 12/13 source tiles, so the initial view may show none. The map reveals them as real data arrives at closer zoom. CARTO's `rank` controls collision priority, not popularity. The pre-existing stadium POI filter excludes only viewpoints to avoid duplicating the new layer.

Four original Maki SVGs are included under `assets/`, pinned to upstream revision `28e2a3602e4bde033a1dd388e86e9c117b425e34`, with CC0 license. Local rendering colors the artwork using muted map ink and registers images at 2x. Optional icon failure does not prevent the map from opening. Sources: <https://github.com/mapbox/maki>, <https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json>, <https://tiles.basemaps.cartocdn.com/vector/carto.streets/v1/tiles.json>.

Recent public rider counts remain absent. Existing indexed Vault completions include repeats and cannot serve as recent or distinct rider activity. The proposed selected-card activity line requires a separate, properly defined public aggregate. No production endpoint or data contract changed here.

## Integration

Bead `boulderroller-v2-4131x`; branch `codex/4131x-map-v5`; sibling worktree `/Users/gabetemp/curahee/BoulderRoller-worktrees/map-v5`. Started from fetched `origin/main` `a63ffc77f`, then carried completed V4 `ebf7b3917c1d07ace6c387f6f2a30278d943cc80` forward. The dirty human root and other task checkouts were preserved.

V5 owns this directory. A separate small registration commit updates MapWorkshop, MapPreview, the default Map destination, candidate count and test entrypoint. Integrators should reconcile those edits into their shared harness, not replace its whole files. V5 still imports V4's immutable ground as its baseline and the existing common map/climb models. This dependency includes Climb V1–V3; later Climb generations are consolidated by the shared workshop owner separately.

Snapshots use `br-map-v5:<study-id>`. The adapter also preserves V4 filters and older candidate behavior. `mapV5ExploreHref` carries the one-use fresh-arrival intent; ordinary detail return preserves camera, selection, filters and list state. These remain local workshop behaviors, not production URL claims.

## Local verification

106 workshop tests, workshop typecheck and workshop build pass. The build retains the existing large-workshop bundle warning. Focused red-to-green: V4's independent profile normalization failed the comparative-grade assertion; the consistent fourfold scale passes, including steep shapes, missing profiles and supplied dips.

Browser checks cover all six scenarios and three viewers; loading, empty and both error states; map retry; filtering; independent V4/V5 filters; keyboard selection and Escape; pointer map selection and panning; same-zoom neighbor selection; exact camera return through detail and browser Back; imported bounds-only geography with zero route lines; invalid import rejection; inspectable export/reimport; earlier candidate buttons, retained V1, page return, Strava reference and desktop/phone controls.

Exact 1440×1000 and 390×844 screenshots, including both open lists, are in `evidence/`. Both layouts have no document overflow. Final browser logs contain no errors or warnings. Phone evidence is pointer/keyboard at the stated viewport, not physical touch. Geography is retained published data; no live rider or economic proof is claimed. No production integration, merge to main or deployment.
