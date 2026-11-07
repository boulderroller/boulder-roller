# Ride → Climb workshop

Run `npm run workshop` from `web/portal`, then open `http://localhost:4318`.
Tick **Finals** in the page bar (or add `&finals=1`) to open every room on the
candidate Tim locked, settled or accepted and hide the candidate ladders; see
`SHARED_WORKSHOP.md` for the consolidated checkpoint and the per-room record.
Tick **Palette** (or add `&palette=1`) to see any room on the shared palette in
`palette/palette.ts`, the one colour file for the finals. Every colour a room's
stylesheets set is shown as its palette token; no candidate file changes, and
with Palette off the rooms render exactly as locked. `&palette=identity` injects
the same rules with colours unchanged, a check that the preview keeps the cascade.
This is a separate Vite entry. The normal portal build and production routes
do not include the workshop, scenarios, or reference images. Use the portal's
existing local environment for its CARTO key; never commit that environment.

## Working together

- Switch **Current / Candidate v1 / Candidate v2 / Candidate v3 / Candidate v4 / Candidate v5 / Candidate v6 / Candidate v7 / Candidate v8 / Candidate v9 / Candidate v10 / Candidate v11 / Candidate v12** without changing the selected
  dataset or climb. V1 retains its **Claude changes** toggle.
- **Preserve every generation.** A reviewed candidate is a fixed reference;
  improvements get a new candidate button, separate components and scoped styles.
  Do not revise an earlier candidate or a shared dependency that changes its
  presentation. V4 is restored exactly to `5c71ffc1`; its six owned files have
  a regression guard. The later refinement is V5.
- The URL records the selected candidate and built-in scenario, so a hard
  refresh keeps that comparison. A fresh workshop opens V12 with the recorded ride.
  V8 carries illustrative rider identity across all bundled scenarios and removes
  the separate identity choice from its picker. Older candidates retain it.
  Recorded geography and measurements remain unchanged. Imported files remain
  session-only and are not embedded in the URL.
- Choose **Fit window**, **Desktop** (1440px), or **Phone** (390 × 844px).
- Select a named climb from the map or result list. Map and elevation share
  inspection; arrow keys inspect the profile. V4 returns through the ride name
  above the climb; earlier candidates retain their existing back controls.
- In V5 Analysis, clear a selected interval with Escape, a click outside its
  highlighted elevation span, or either Clear control. Clearing returns to the
  current ride or climb. Escape during an edit or drag cancels that edit only.
- Optional `ride.rider` metadata supplies `displayName`, `source` (`provided`
  or `illustrative`), and an optional `avatarDataUrl` (embedded PNG, JPEG or WebP,
  up to 2 MB). It survives scenario import, export and cropping. V5 shows a
  compact rider identity in both rooms, with initials if no portrait is supplied
  or the image cannot load. The retained recording has no verified rider name
  or portrait; it keeps the generic ride label until identity is supplied.
- Hold **Loading results**, then **Release data**. **Empty** and **Error** have
  working recovery actions. These are controlled workshop states.
- **Strava reference** opens the retained study captures beside the preview.
  **Analysis** includes the whole ride and a selected climb with aligned speed,
  recorded power, heart rate, cadence and temperature charts, plus a live source link.
  **Squint** blurs both presentations. The Strava captures contain other rides.
- **Data** imports a JSON scenario. Invalid imports keep the current ride.
  **Export scenario** exposes the full JSON, a copy action and a download action.
  Browser support determines clipboard/download behavior; the full text remains
  available in the export view. Imported data stays in the browser session.

## Data format

Export a bundled scenario as the easiest starting point. `scenario.ts` is the
scenario validator and overview measurement model; `v3Model.ts` supplies analysis channels and selection. One version-1 scenario contains:

```ts
{
  version: 1,
  id: string,
  label: string,
  source: {
    kind: 'recorded' | 'illustrative',
    description: string,
    history: 'none' | 'recorded' | 'illustrative',
    sha256?: string
  },
  ride: {
    title: string,
    startedAt: string, // ISO date
    location: string,
    samples: Array<{
      lon: number, lat: number,
      d: number, // cumulative meters, first sample = 0
      t: number, // elapsed seconds, first sample = 0
      elevation: number | null, // meters
      power: number | null, // watts
      cadence?: number | null, // rpm
      speed?: number | null, // meters per second
      heartRate?: number | null // bpm
    }>
  },
  climbs: Array<{
    id: string, name: string,
    start: number, end: number, // exact elapsed sample times
    history: Array<{ date: string, duration: number }>
  }>
}
```

Times must increase; distance must not decrease. Climb windows must have exact
sample boundaries. Previous results must precede the ride. Null measurements
remain absent. Files are limited to 20MB, 100,000 samples and 100 climbs.

Distance and elapsed time come from the selected interval's endpoints. Elevation
gain sums positive measured changes, and average power is time-weighted over
covered intervals; neither calculation bridges gaps longer than 30 seconds.
Those totals can differ from a device's filtered summaries. The profile uses
the same samples and leaves missing elevation gaps unfilled.

## Sources and scope

`data/in-the-bag.json` normalizes the GPS/elevation/distance and timestamp-matched
power, cadence and speed from `history/ride-room-2026-09-05/build/capture-fixture.json.gz`.
It retains 16,082 samples from the 28 Aug 2016 `in_the_bag_.fit` recording
(source SHA256 `309a48f315c75647f3282027beab8f1b5a4106a33050a538da1178ea113d0d8b`).
Cadence and power have 15,901 timestamp-matched readings; all 16,082 GPS samples
have recorded speed. The 2,255 measured cadence zeros remain zero. Heart rate
was not recorded and remains absent; V3 and V4 display it when an imported scenario
contains it. The optional channel fields preserve compatibility with older scenarios.
Fictional social, CAL, vault IDs, ranks and settlement values were excluded.
The three climb names and traversal time windows come from that retained study;
their visible geometry and dimensions are derived from the recorded intervals,
not presented as canonical course dimensions.

The ordinary scenario has no history. The new-best scenario adds explicitly
illustrative prior results. The short scenario crops the recorded ride and
deliberately removes power. None are current production rider-state evidence.

Current reuses `RideRoomGeography`, `RideRoomIdentity`, `RideRoomRow`, their CSS,
and `RideRoomMap`. Its selected-climb view applies that existing composition to
the selected interval; it is not a reproduction of the full production Climb
page. A local pure-formatter alias supplies the few formatting functions needed
by `RideBand` without mounting authentication or wallet providers.

Candidate changes composition and map emphasis, using the existing MapLibre
ground recipe and telemetry path/nearest-point helpers. It is a working design
proposal, not a ratified replacement for portal contracts. It includes ride
metrics and personal history, with no fabricated leaderboard or economy data.

Candidate v2 keeps the quiet unselected climbs and early phone result. It groups
climb dimensions compactly, removes the title arrow, preserves the large time
and gold personal best, and gives map terrain, roads, water and labels distinct
color roles. The map keeps its existing phone height. Elevation labels render at
their intended size, and history bars use one uncapped duration scale. History
is absent without prior efforts; the selected climb is omitted from the lower
list. Loading retains the same result geometry. These changes are isolated from
Current and both V1 presentations.

Candidate v3 is a separate presentation with a light ground palette and a wider,
quieter reading surface. Ride overview places the full-width map over elevation
and climb results. Climb overview pairs the selected route with elevation and a
100 m gradient profile, brings the personal time and best forward, and keeps the
whole-ride profile as context. Unselected route geometry recedes while the map
stays mounted when the selected interval changes. Its light relief, contours,
land, water, road and label colors use the existing CARTO/Terrarium sources.

V3 Analysis has aligned elevation, speed, power, cadence and optional heart-rate
charts. Hover, arrow keys and map inspection share the same global sample index.
Drag any chart to select a stretch; the whole-ride context keeps that interval
marked while the detailed charts, map and interval summaries update together.
The range editor accepts kilometers or elapsed minutes according to the chosen
axis, including stationary intervals. Clear returns to the selected climb or
whole ride. Channel toggles preserve at least one visible measurement. Missing
channels stay absent. Chart means use covered time and retain measured zeros;
recording gaps over 30 seconds break both traces and route geometry. Missing
speed derives from its forward distance/time interval only when that gap is at
most 30 seconds. Grade abstains across missing or short windows. Trace thinning
retains bucket extrema so brief efforts are not silently smoothed away.

Desktop reference comparison displays a genuine 1440 px preview scaled to the
same width as the retained desktop image. Both surfaces receive the same 5 px
blur after scaling. This fixes the earlier mismatched scale and blur strength;
the rides and terrain are still different, as labeled. Loading preserves the
V3 anatomy and known geography while withholding personal results. V3 is local
workshop behavior, with no new production routes or provider integration.

Candidate v4 adds a dark BR header, a stable section sidebar and neutral surfaces
for ride identity, supporting figures, climb results and chart readings. The
climb's personal time and best remain above its terrain map. Its history and
other climbs sit in a quieter companion column; phone navigation and results
keep the same ancestry. Analysis uses a compact identity so traces enter sooner.
Elevation is the persistent selection surface; speed, power, cadence and optional
heart rate form the aligned chart stack beneath it.

V4 separates current ride/climb, interval selection, transient inspection and a
pinned reading. Drag the elevation relief or a detailed trace to select; drag
either edge to resize, or drag the selected relief to move the interval. Chart
scales and map camera hold during the draft, then update on release. The gray
summary previews the draft's recorded bounds and measurements. Movement preserves
distance or duration to the nearest recorded samples, clamped within the subject.
Stationary intervals retain their exact endpoints on Distance; use Time to move
them. Numeric adjustment is secondary and cannot escape the climb. Switching
axes preserves endpoints. Clicking an active navigation item preserves selection.
Click or tap pins; arrows inspect, Enter pins and Escape releases. Inspection
outside a selected interval is explicitly identified and never fabricates detailed
readings. Selection edges have keyboard controls and 44px-wide pointer targets;
vertical touch gestures yield to page scrolling and other pointers cannot take
over an active selection. This is responsive browser proof, not a physical-phone
touch evaluation.

V4 loading reserves result geometry with quiet marks and keeps known geography.
Short scenarios omit missing charts; empty/error states have working recovery.
Prior candidates remain available. A shared analysis correction prevents a
forward-derived speed at a selected endpoint from using a sample outside the
selection; recorded endpoint speed remains intact. The analysis reference mode
uses a 1440 × 1175 preview to match the retained capture, with equal scale and blur.

The Ride and Climb reference images are retained captures from the supplied
`history/strava-study-2026-09-09` study (9 Sep 2026). Analysis references show
[Drake Deuel's Morning Ride, 10 Sep 2026](https://www.strava.com/activities/20113623084/analysis),
found in the user's existing Strava feed and captured on 10 Sep 2026 at
1440 × 1175px. The 48.87-mile ride has recorded power (not estimated), heart
rate and cadence, plus speed, elevation and temperature. The overview displayed
197 W average power, 116 bpm average heart rate and 74 rpm average cadence.
Dragging a chart selected an 8.1-mile climbing interval (2,876 ft, 6.7%, 54:32),
highlighted the route, zoomed all five measurement charts together and updated
their averages. A shared cursor shows exact readings across the chart stack.
The retained selection is `/activities/20113623084/analysis/5465/8737`.
These replace the earlier speed/estimated-power-only Analysis reference.
The subscription panel is retained; gated subscription views were not inspected.
All reference panels display static captures, not a live Strava connection.
No source recording was downloaded or imported into the Boulder Roller scenario.

## Checks

`npm run workshop:test`, `npm run workshop:typecheck`, and
`npm run workshop:build` check the data model and separate app build.
The normal `npm run build` confirms the production entry remains independent.

## Candidate v6

V6 preserves V4 and V5 byte-for-byte, including their shared presentation dependencies.
It combines overview figures into a white summary, gives the map more distinct
vegetation, uses a freely following cursor, and replaces visible range grippers
with subtle adjustable edges. Escape, outside-profile click, and Clear return
to the current ride or climb. Keyboard edge adjustment and numeric interval
editing remain available.

Chart traces use covered-time averaging across a shared screen-width budget,
with gaps preserved. Sparse scopes show raw traces. Raw cursor readings, maxima,
scales and averages are unchanged. The V6 colors draw from the deep hues in the
[USGC website colorbar](https://usgraphics.com/static/core/logo/colorscale/usgraphics-colorscale.955194642d2e.svg):
speed blue `#184898`, power violet `#613393`, cadence green `#007A61`, heart rate
red `#C22032`. This channel mapping is our proposal, not an official USGC chart system.

Power Curve shows exact covered-time best efforts over uninterrupted intervals
of at least one second, using original power samples and measured zeros. Missing
power and gaps over 30 seconds split coverage; the final reading has no invented
duration. The retained ride has no uninterrupted hour of power and no heart rate.
Heart Rate appears when an imported scenario supplies it; no physiological zones
are invented. Both additional views follow the current ride or climb.

The rider bar contains an explicitly local kudos/comment prototype. It has no
authenticated viewer, provider connection, persisted comments, or invented social
counts. Reloading discards that local interaction state. Production maps, routes,
and social behavior are untouched.


## Candidate v7

V7 is a separate generation. V4, V5 and V6 have byte-for-byte guards; older
candidate files and shared presentation dependencies remain unchanged.

Overview climb results now enter ride Analysis. The ride title, identity and
whole-ride totals remain steady. The scope row names the climb, its detail charts
use the exact recorded start and finish, and the map fits that interval. The
full-ride elevation profile remains visible with the climb highlighted in place.
Overview no longer repeats the climb list below the relief. Analysis uses small
position/length-aware climb marks on the Distance or Time axis, with overlapping
touch targets arranged into lanes. Clicking an active mark returns to the ride.

A plain click in a scoped map, profile or detail chart returns to the whole ride.
Map pan and zoom preserve scope. Dragging the map's lower separator changes its
height; arrow keys and Home/End offer the same adjustment. Escape cancels an active
resize, or clears scope when idle. Detail selection uses one translucent block
across the complete chart stack. Shift with arrows previews a keyboard selection;
Enter applies it and Escape cancels a draft or releases a committed scope.
Numeric interval adjustment remains available. The elevation relief is slightly
shorter, with the same soft boundary treatment.

Averaged display runs now reach their actual covered endpoints. Distance pauses
no longer acquire invented blank width; true time and missing-channel gaps remain
unconnected. Two focused tests reproduced the prior endpoint error before the fix.
Raw values, calculations and recording data remain unchanged.

Power Curve keeps its layout and exact calculation. Its brush zooms a separate
logarithmic effort-duration domain, not a contiguous ride interval. Click or Escape
returns to all durations; Shift and arrows plus Enter provide keyboard selection.
Replacing a recording resets that domain before old indexes can reach new data.

The date sits with the ride's location. Comments open a centered ride-scoped
modal with focus containment and return, Escape/outside close, and a composer at
the bottom. Comments and kudos remain explicitly local, session-only prototypes.
No feed, social provider, or economic output was added. This recording has no
attested CAL, frozen tribute itemization, Vault position, or settled DUNG evidence.

Verified locally at 1440px desktop and 390 x 844 responsive browser sizes: climb
entry and release, repeated chart selection, continuous stack brush, map pan and
resize, duration zoom and keyboard release, comments focus, and shorter same-ID
scenario replacement. An explicitly illustrative import exercised heart-rate and
loading behavior; the retained recording still has no heart rate. These are local
browser checks, not physical-phone or deployed rider proof.

## Candidate v8

V8 preserves all twelve V7 files under a byte guard at `3145bfc2`. The title now
precedes location/date. Both Analysis entry points remain. Overview's collapsed
Show more reveals maximum speed, maximum power, covered-power work and the known
FIT origin, followed by a small illustrative Ride CAL summary.

CAL & tribute is a secondary destination. Its dotted branches show the full
312 CAL pending to the example rider and separate 8 / 3 / 11 CAL pending tribute
examples beside this ride's three climbs. All amounts, states and Vault bindings
are expressly illustrative, authorized for this design mock, and are not derived
from the recording. Tribute is not deducted from the rider. The diagram links
back to each climb's Analysis. No DUNG or live economic transaction is presented.
The limited-measurement scenario and all imports omit this economics fixture,
even if an imported ID matches a bundled ID. Export still contains source data;
V8 presentation examples are not silently written into an imported ride.

Power distribution sits below the existing selectable curve: wattage bins on X,
covered minutes on Y, including real zeros. Ordinary data uses 25 W bins; unusually
large imported ranges adapt bin width to cap display allocation at 160 bins. The
raw readings stay intact; unrepresentable ranges show an unavailable state. Drag,
click-to-release, Escape and Shift+arrows/Enter work in both power charts. Clearing
from a button restores focus to the chart. Empty-to-covered and shorter same-ID
replacements retain safe state and responsive measurement.

The map stays mounted across Analysis, Power Curve and CAL & tribute. Resize and
camera requests share one animation-frame queue, and endpoint markers are reused.
Climb targets under the relief are unnumbered, with a soft 28px minimum surround
and the actual proportional span inside. Names appear on hover/focus. Visible
instructional chart sentences are removed; cursor readings and optional help stay.

Local evidence: 1440px desktop and 390 x 844 browser renders; scoped map/chart
release, continuous stack brush, map height, both power chart selections, keyboard
focus return, comments, loading, scenario/version switching and same-ID imports.
The same map canvas node survived economics, climb Analysis, Power Curve and back.
Focused distribution/work tests include zeros, real gaps, final-sample duration
and an outlier allocation regression. This remains a local workshop, not deployed
rider, social-provider, financial or physical-device evidence.


## Candidate v9

V9 is a separate candidate. All seventeen V8-owned files remain byte-for-byte as
reviewed at `060d05cc`, alongside the earlier generation guards.

Overview groups date/place above the title, local description and private notes
beneath it, and co-riders below. The statistics column has reserved height and a
soft secondary band. Show more reveals compact file facts and discreet Ride CAL;
the desktop map moves 66px in the verified example. Example labels are disclosed
in the workshop About panel rather than repeated in the ride composition. Social
controls are local interactions; there is no matching provider or message sending.

Power contains the existing selectable curve and distribution plus a power/cadence
density chart. Cells measure covered seconds, including real zeros, and exclude
unpaired intervals or gaps over 30 seconds. The grid is bounded to 64 cells per
axis for unusual imports. Selecting a climb compares its paired measurements with
the whole ride; dragging or keyboard selection zooms a watt/cadence rectangle.
This selection is a combination of levels, not one continuous ride interval.
The retained recording contains no heart rate or recorded torque channels.

CAL & tribute keeps full rider CAL separate from climb tribute and places each
named destination alongside its actual traversal relief. Its Vault links now open
a local climb/Vault page. Overview climbs still open scoped Analysis; the climb
name there opens its Vault. This ride's effort returns to scoped Analysis. Browser
Back restores the mode, axis, interval, map height and scroll, and bundled deep
links survive refresh. Historical summaries have no invented linked recordings.
These Vault bindings and economic amounts remain explicit workshop examples.

Imported recordings receive session references. Reopening one outside its window
shows unavailable and offers reimport or the bundled ride; it never substitutes
bundled economics silently. Source replacement resets local notes, companions and
selection even when ID/date match. Long imported names wrap within phone layouts.

Verified locally at 1440px and 390 x 844: overview expansion, description/note focus,
co-rider dialog, ride/Analysis/Vault links and Back, Vault refresh, chart selection
and click-to-return, map height, Power rectangle and climb comparison, loading,
shorter same-ID imports, unavailable imports and long names. Forty workshop tests,
workshop typecheck, workshop build and ordinary portal build pass. This is a local
workshop preview, not deployed rider, matching-provider, chain or physical-device
proof.

## Candidate V10

V10 is a separate generation; all 23 V9-owned files remain byte-for-byte at
`6548b81b`, in addition to the earlier generation guards. Its compact headers
share metadata/metric-caption and title/numeral baselines. Power uses readable
axis steps. A point or duration tile on Power Curve opens its actual effort in
Analysis on Time; Distance remains selectable and survives refresh. Duration
brushes still zoom the curve, and clicking a zoomed curve or Escape returns.

Power includes a relationship switch between power/cadence and cadence/estimated
gradient. Density uses covered time, measured zeros, full-ride derived grade and
fixed bins when highlighting a climb. Missing pairs and gaps remain absent.
Fractional power windows open enclosing recorded samples and explicitly show
the exact best-effort interval separately when those boundaries differ.

The sidebar ellipsis contains existing local description, private-note and rider
controls. The harness's Ride owner / Visitor setting exercises their presentation;
it is not authentication. Notes are omitted from the visitor render. Editing
works from every ride section, closes with Escape and restores focus. Empty
descriptions and private notes leave no authoring prompt in the resting ride.
CAL destination hover or keyboard focus highlights that climb's actual span in
the whole-ride relief and its dotted connection. All V9 local-data disclosures
and the separation between full rider CAL and tribute still apply.

Local verification: 43 workshop model/generation tests, typecheck, workshop and
ordinary portal builds; exact 1440px and 390×844px browser captures, pointer and
keyboard selection/clearing, effort routing, axis refresh, owner/visitor context,
CAL/Vault/effort loop and import replacement. Captures and browser probes are in
`/tmp/boulder-v10-proof`. No production merge, deployment or physical-touch proof.


## Candidate V11

V11 preserves all 23 V10-owned files exactly at `b330977d`.

- Sidebar rows and owner options share their icon column, height and hover width.
  Analysis and Heart rate retain compact rider/ride identity while the figures
  below the elevation become the primary summary. Chart rails have larger labels
  and averages without heavier traces.
- Power Curve keeps the full duration axis in place. Dragging leaves a soft band;
  its finishing duration automatically chooses one real best effort. The summary
  names that duration, average power and elapsed ride boundaries. Hover is free
  and never changes the committed effort. Only **Analyze effort** navigates.
- Click a selected chart or press Escape to clear. Presets select without leaving
  Power. Shift-arrow/Enter commits a keyboard selection. Canceled gestures keep
  the previous selection; replacing a recording resets it, and loading masks it.
- A curve band is not a ride-time interval and its points are not averaged.
  Analysis retains the exact-effort disclosure when the best effort falls between
  recorded samples and the displayed charts require enclosing samples.
- Cadence & gradient stays beside Power & cadence in the relationship switch.
  A quieter low-density field and softer cell seams leave the busiest combinations
  distinct; bins, covered time and recorded values are unchanged.

Local proof: focused browser red showed the old click leaving Power; V11 keeps
selection in place and requires Analyze. All 46 workshop tests, typecheck and
workshop build pass. Browser checks cover pointer/keyboard/cancel/hover, scoped
navigation and return focus, same-ID imports, fractional bounds, missing/zero
power, loading, owner dialogs and visitor hiding. Exact 1440 × 1000 and 390 × 844
captures and scripts are retained in `/tmp/boulder-v11-proof`. These are local
workshop and fixture checks, not production or physical rider evidence.


## Candidate V12

V12 preserves all 24 V11-owned files exactly at `75dc068a`. The desktop climb
rail is limited by the combined map and elevation height. Short lists retain
their natural spacing. Longer lists scroll only their rows, with the count and
Analyze ride action outside the scroller; the footer aligns with the geography.
The native scrollbar is visible and row sizes stay unchanged. On phone, the
list remains in normal page flow.

Opening a climb, switching sections or selecting elevation records the Overview
position. Browser Back and the Overview button restore that position; returning
from a climb also restores its focused row. Recording replacement clears stale
positions. A responsive layout change reveals the activated row in the new layout.

The navigation and summary destination now say **CAL**. The page retains **Ride
CAL** and **Climb tribute**, with the existing separate amounts and state labels.

V12 adds **10 climbs · layout study** and **30 climbs · layout study** to the
scenario picker. Their windows and names are explicitly illustrative, including
long names; the recording's GPS and measurements are unchanged. They supply no
additional detected climbs, canonical Vault matches, history or economics.
These built-in studies survive a refresh and can be exported.

Run `node workshop/tests/v12-layout.browser.cjs` with the workshop running for
layout/interaction regression checks. It exercises short and long lists, the
fixed count/footer, real wheel scrolling, keyboard access, scoped Analysis and
return restoration, elevation selection, phone flow, scenario replacement,
refresh, CAL labels and the unchanged V11. The browser keeps scrollbars enabled
so captures represent the native scroller. Local captures and red-to-green
probes are in `/tmp/boulder-v12-proof`; these are workshop/fixture checks, not
production or physical rider evidence.

## Feed workshop and page selection

The workshop now has a **Workshop page: Ride / Feed** selector. Ride retains
its complete candidate history and accepted V12; Feed starts with **Candidate
v1** and has its own reference set and scenario picker. Page switching remembers
the last Ride view/axis/scroll and keeps the Feed's scroll, comments and kudos in
its existing preview. Browser Back follows the ride-entry loop. The page,
candidate, built-in scenario and Feed filter survive refresh.

The accepted Ride source is preserved from `534641ac336c9c594ed9c9ddede778bd02dddcd7`
(owner `boulderroller-v2-w6arc`). All 25 V12 source/fixture files now have byte
checks, in addition to the earlier generation guards. This successor starts
from current main and carries that workshop source as its dependency; normal
portal routes remain separate.

Feed V1 carries V12's Geist typography, paper/ink colors, neutral identity
surfaces and map ground. The central stream contains independent ride cards,
Everyone/Following, a wide map link, recorded elevation, a compact climb result,
and inline comments. Maps scroll with the Feed; opening a ride provides map
inspection. Title/map links open the corresponding Ride V12. Climb result links
open that recording's scoped Analysis. Entry ownership is explicit: another
rider opens Visitor mode. Feed maps preserve recording gaps; absent relief
measurements remain gaps. Loading retains result/comment row geometry.

The bundled Feed is a **presentation study**, not multiple recorded activities.
Its geography and measurements use the retained ride and excerpts. Rider names,
comments, kudos and prior effort history are illustrative. No production social
API is called. The source explanation remains in Data and outside the candidate
composition. Feed JSON includes each complete ride scenario, supports up to 50
unique entries, and can be exported/replaced. Imported ride IDs are namespaced
per source. Imports are session-only; after a refresh, an unavailable imported
Feed or linked ride requests recovery instead of substituting a bundled ride.

`feed/FeedWorkshop.tsx` owns the Feed candidate/reference registry. V1 references
are retained 9 Sep 2026 desktop and phone Strava Dashboard captures, top and
scrolled. Copied from `history/strava-study-2026-09-09` in the original root.
They contain different athletes and activity data. Reference images remain
separate from the candidate. Future generations get a new candidate entry,
separate owned components/styles, and their specific reference set.

Run `WORKSHOP_URL=http://localhost:4318 node workshop/tests/feed-workshop.browser.cjs`
for the connected surface, comments, filters, Visitor, Back, references, loading,
refresh and phone-layout checks. V12's existing browser regression remains valid.

### Ride implementation handoff boundary

Feed workshop work does not start production Ride integration. The accepted Ride
must be implemented with explicit owner, signed-in visitor and signed-out public
states inside the existing portal navigation. Existing public visibility and
privacy rules govern available data/actions. Private/unavailable rides, sign-in
return, ownership, saved comments/editing, actual CAL states and canonical Vault
links belong in that implementation's completion criteria. The final combined
visual/interaction check happens when the worker returns the integrated result.

## Feed Candidate V2

V2 carries the ratified **personal / terrain and people / world** composition:
private progress and recent rides on the left, linked ride terrain and a named
climb result in the stream, and a compact platform summary on the right. The
map and relief highlight the same supplied climb on hover or keyboard focus;
the camera stays fixed, and leaving the result clears the emphasis. The result
opens scoped Ride V12 Analysis. Phone summaries are collapsed and only appear
when their content exists. Comments stay attached to their ride.

`feed-v2` is a separate candidate and URL. V1's component, stylesheet and data
model, and every accepted Ride V12 file, remain unchanged. The retained Strava
Feed references are bound to each candidate in the registry. Source replacement
resets V2 local UI state; filters preserve the independently supplied world data.

Optional `workshopV2` JSON contains `source`, a platform `world` summary (explicit
period start/end/as-of and optional climbsRidden/rideCal/tributeCal), and
`rideEconomics` bound to exact owned entry and ride IDs. Built-in example context
is attached before serialization using object identity. Imported JSON never
inherits it by ID, name, or known climb. True zeros remain visible; missing
context stays absent; tiny positive amounts never round to zero. Imports
rebind economics to the newly namespaced ride IDs after validation.

Personal history uses the newest eligible owned ride and that climb's supplied
history. A local history dialog shows the exact dates/times; only the current
effort has a linked recording. Platform details are a local scoped summary,
not a new global explorer. Own Ride CAL opens a dialog using unchanged
V12Economics with explicit example amounts; its Vault links open the matching
V12 traversal. The preserved Vault view does not receive custom economic
amounts. Full profile/world destinations and production integration remain
separate work. All social changes and imports stay in this workshop session.

## Feed Candidate V3

V3 preserves Feed V1/V2 and Ride V12. Its left side covers a complete recent
riding period with Week/4 weeks controls, daily climbing inspection and current
Top 10 standings. The right side shows independent regional activity, subdued
Ride CAL/tribute totals and one climb discovery outside the feed. The stream
keeps the linked map, relief and attached comments. A compact inset gathers the
featured climb, measured time and supplied prior-best improvement, with Ride CAL
in its own compartment. All climbs opens a result list; choosing an effort opens
its exact Ride V12 Analysis and dismisses the dialog before navigation.

`workshopV3` is optional and carries an explicit source. `personal` binds to the
viewer and contains a complete consecutive date range, daily riding summaries
and exact owned entry/climb standings. `world` carries a period, as-of time,
optional CAL totals and geographic regions whose counts reconcile with the
supplied total. Empty regions omit the map; zero values remain visible. Imports
never inherit bundled context by a familiar ID. Changing a source remounts its
local state; changing the feed filter preserves the independent context. The
export includes the context so another source can replace the whole example.

The bundled 28-day personal history, current ranks, regional activity and
amounts are explicitly illustrative design inputs. Port Royal Avenue's 192-point
profile, 1,530.43 m length and 93.07 m ascent come from the retained
`web/scan/src/fixtures/climb-canon.json` geography, documented in
`history/boulderscan-climb-2026-09-06/build/README.md`. The extracted data lives in
`data/port-royal-discovery.json`. No public place, active Vault, platform activity
or economic claim is inferred from that geography.

Personal day/period details and regional/discovery details are local dialogs.
Top 10 entries open the supplied recording's scoped Analysis. Discovery has no
Vault binding. Ride CAL reuses the unchanged V12 economics dialog and Vault
traversal. Full profile, leaderboard, world and discovery destinations remain
production integration work; this candidate does not implement them.

V3's reference set adds the achievement inset observed in the signed-in Brave
Strava Dashboard on 11 Sep 2026, retained as
`references/strava-feed-v3-achievements.png`. The 9 Sep top and phone references
remain available; earlier candidates keep their original reference sets.

Local verification: 59 workshop tests, workshop typecheck and build; desktop
and 390 px phone compositions; tablet world access without personal context;
period/day and region/discovery dialogs; results/Analysis/Back and CAL/Vault/Back;
filter independence; explicit-zero and missing-context imports; loading, error,
empty and refresh behavior. This is runnable workshop evidence, not deployed
portal or real-rider evidence.

## Feed Candidate V4

V4 keeps V1–V3 and Ride V12 as fixed references. Each ride has one achievement
inset: up to two personal bests share the same surface, while All climbs opens
the complete result collection. Ride CAL appears once in an adjoining compartment.
Pointer and keyboard inspection connect the chosen result to its map and relief;
each result opens the exact scoped Ride V12 Analysis and closes its dialog before
navigation. Top 10 uses aligned rank marks with effort time and distance.

The upper-right Boulder Roller composition is retained. Discovery gains locality,
three compact measurements and a preview with a navigable map and larger elevation
profile. Port Royal Avenue uses the retained 192-point geography from
`data/port-royal-discovery.json`; Philadelphia locality is supported by the matching
record in the retained open-data release's `regions/philadelphia.jsonl`. Displayed
average grade is endpoint rise divided by full length (6.1%), rather than cumulative
ascent divided by length. Partial imported profiles omit the whole-climb grade and
leave their unknown terrain unfilled. This preview makes no active-Vault claim.

`feedV4Model.ts` extends the optional `workshopV3.world.discovery` with `locality`
and a validated GeoJSON LineString `geometry`. Missing fields stay absent; imported
files never inherit bundled context merely by matching an ID. The existing source
export includes these fields. Earlier candidates retain their original data views.

Use Mixed rides for one best, **3 new bests · example history** for the retained
three climbs with supplied previous times, and **10 new bests · layout study** for
the existing V12 ten-window layout fixture. Both new cases preserve all recorded
ride samples. The ten-window study does not invent Ride CAL, ranks or canonical
Vaults for those windows. These remain explicit workshop data choices.

Local verification: 64 workshop tests, typecheck and build; 1440 px desktop and
390 × 844 phone previews; one-, three- and ten-best collections; final-result
Analysis/Back; keyboard-linked relief; identical ready/loading collection height;
discovery map controls; and preserved earlier source files. Production feed
integration, live activity and rider-state evidence remain outside this workshop.

## Feed Candidate V5

V5 preserves Feed V1–V4 and Ride V12. The header and ride identity are tighter;
the personal summary and current leaderboard marks share deliberate alignment.
The visible map button is removed, while its full map link and accessible name
remain. Missing personal/world context is omitted and the remaining composition
recenters; empty and error states keep a full-width central panel.

A ride has one compact result collection, with at most two achievements visible
and every climb available in its detail dialog. Public places 1–10 use the existing
rank assets without runtime decoration. A personal best and a public place on the
same climb occupy one result. Personal second/third times have distinct type and
explicit labels, not public-rank sprites. Ordinary results stay quiet. Ride CAL
appears once. The leading visible result supplies the resting map/relief highlight;
pointer and keyboard inspection temporarily follows another result.

All seven scenario choices are complete: Mixed rides, Quiet ride, Long title,
3 new bests, 10 new bests, Personal bests 1st/2nd/3rd, and Leaderboard places 1st–10th.
The last two are explicit design cases. The ten-place case uses the existing
layout windows; those windows are not newly detected or canonical climbs.

Optional `workshopV5` supplies a source and exact entry/climb result facts.
Historical public `leaderboard` placements are separate from current personal
standings. Personal second/third requires `personalHistoryComplete`; ties use
competition ranking and the same whole-second precision shown in the UI.
Imported data never gains bundled examples from a familiar name or ID.
A production adapter must supply the appropriate proven placement/PR/history;
these workshop examples do not establish live rider results.

Regional activity details link map marks, row selection, exact counts and
proportional bars. CAL remains an aggregate below the regional display; no regional
CAL allocation or unprovided time series is inferred. The independent network
feature uses the retained Black Rock Road interval, with an explicitly illustrative
Alex identity and first-place result. Its source is separate from the visible feed
and does not change with Everyone/Following. The preview links its map and relief
cursor, supports keyboard inspection and map controls, and has working Analyze
effort and View climb journeys into the matching preserved Ride V12 surfaces.
The latter is the existing local Vault preview, not a newly built public explorer.
Incomplete terrain omits the profile instead of filling missing elevation or gain.

Imports validate result and network bindings against normalized ride identities,
rekey network rides independently and include them in onward navigation. Export
retains the supplied V5 context. Session-only imports give an explicit recovery
state after refresh rather than substituting another ride. Earlier generations
restore their own original scenarios and reference images.

Local verification: 70 workshop tests, typecheck and build; all seven dropdown
cases at desktop and 390 px phone widths; complete 3/10-result dialogs; exact
1440 × 1000 and 390 × 844 renders; linked region/profile keyboard inspection;
import validation and network-to-Vault/Back; result-to-Analysis; filter and comment
continuity; loading/empty/error recovery; and V1–V4/V12 preservation checks.
Screenshots for this pass are in `/tmp/boulder-feed-v5-proof/` on the workshop host.
This is a local workshop candidate, without production integration or deployment.


## Feed V6 and Ride V13

Feed V6 preserves V1–V5 and connects to additive Ride V13. Achievements open
an expanded result within the ride overview; **Analyze effort** opens its scoped
analysis. **Your leaderboards** and **Open climb** go to the climb page. Supplied
current leaderboard rows link back to a recording only when rider, climb, and
time match. Historical ride placement is separate from current placement.
The ride carries its supplied owner-only CAL context through this journey.

The personal summary has one keyboard-accessible daily chart (arrows, Home/End,
Enter/Space). Comments use a quiet field and **Comment**. Feed sessions retain
filter, loaded batch, scroll position, comments, and drafts across ride visits.
The 32-card case appends in batches; distant maps release their live instance
and retain a still image. This exercises local pagination, not a live feed API.

The default world shelf pairs a retained Philadelphia climb with supplied
regional activity. The three-feature case uses three retained Philadelphia
intervals, with explicitly illustrative people and placements. V6 imports may
supply up to three network features and dated leaderboard excerpts through
`workshopV6`; missing recording links and invented geography are not filled in.
All nine feed scenarios, loading/recovery, export/import, and session-only import
recovery are available from the workshop controls.

Ride V13 shows **Avg grade** for a selected climb or interval: signed net rise
divided by traveled distance, preserving a true zero. It withholds a reading
for missing elevation, gaps over 30 seconds, or intervals shorter than 50 m.
Earlier ride candidates retain their original behavior.

## Feed V7

V7 preserves the accepted personal/terrain/world composition and all prior feed
generations. Across Boulder Roller now separates network totals from a featured
climb: place, terrain, rider, result. Its rider, rank, and time resolve from one
supplied leaderboard row. Recording links appear only for a matching effort;
the terrain can come from another supplied recording without assigning that
recording's performance to the featured rider.

Rider names, avatars, companions, and comment authors open a local rider summary
with supplied rides and leaderboard rows. Quiet shared hover/focus connects
repeated identities. Native links retain real destinations, while ordinary
navigation preserves the feed's filter, loaded cards, scroll position, and drafts.
Imports require explicit identity bindings, reject colliding entries, rekey all
recordings including retained legacy terrain, and validate the resulting payload.

All nine dropdown cases use V7, including the 32-card continuation study. Local
verification covers 77 workshop tests, typecheck/build, all nine scenarios,
matching-result navigation, rider/ride/feed return, Following, comments, and
desktop/phone interaction. Exact 1440 × 1000 and 390 × 844 captures are retained
in `history/feed-v7-workshop-2026-09-12/` at the repository root. This is workshop
evidence; rider summaries and network activity remain supplied examples.

## Feed V8

V8 preserves V1–V7 and shares the V7 scenario/identity validation. Network
activity places the map and regional readings in one responsive frame. The
headline and CAL remain platform totals; transient inspection and persistent
region selection are separate, including marker `aria-pressed`. Selecting again
or All regions clears the selection without rebuilding the map.

Across Boulder Roller uses one continuous field for climb identity, relief, and
result. Rank assets are modestly larger without changing their artwork. Rider
hover is local to the actual target, and the riding footer now reaches both card
edges with matching bottom corners. Rider, ride, and leaderboard destinations
retain the V8 return origin.

Local proof: all nine scenarios at desktop and 390 px phone width with no
horizontal overflow; region click/reset and keyboard selection; stable global
CAL; local avatar hover; comment draft and browser Back; climb/Analysis/feed
return; Following and loading/empty/error states. The footer changed from a
170 px highlight inside a 204 px card to the full 204 px; V7 remains 170 px.
All 77 existing workshop tests, typecheck, and build pass. Exact desktop/phone
captures are in `history/feed-v8-workshop-2026-09-12/`. Workshop only.

## Feed V9

V9 keeps the accepted V8 composition and makes Across Boulder Roller two
complete targets. The climb heading and relief share one native link to the
climb/Vault. The rider, rank and time share one result button and continuous
hover/focus bar, opening the existing detail view. Rider and matching recording
links remain explicit inside that view. V1–V8 are preserved.

Local verification: the mixed feature changed from four targets to two, without
nested links or separate name/relief highlighting. Keyboard activation and Escape
restore focus to the complete result bar. All nine scenarios fit desktop and
390 px phone layouts; Following, comment draft retention, ride/climb/feed return,
loading/empty/error recovery, network selection and 32-ride continuation work.
An imported scenario also retains V9 through climb and feed return navigation.
All 77 existing workshop tests, typecheck and build pass. Exact 1440 × 1000 and
390 × 844 captures are in `history/feed-v9-workshop-2026-09-12/`. This is the local
workshop implementation target; production integration and deployment are separate.

## Climb V1 baseline and Candidate V2

The third Workshop page preserves Ride V1–V13 and Feed V1–V9. Start at
`/?surface=climb&variant=climb-v2&scenario=wises&viewer=rider`.
V1 is a frozen capture of the live public Jefferson Street / North Woodbine
Avenue page on 12 September 2026, with an Open live link. It is explicitly the
public view, not an authenticated-page reconstruction. V2 has the same public
geography as a selectable scenario for direct composition comparison, plus
Wises, Black Rock, Sprague, first-visit and an explicitly authored Vault case.
The retained Strava Manayunk Wall desktop reference remains a different climb.

V2 carries the accepted map colors, typography and unchanged RankMark artwork.
The elevation cursor follows the map; dragging selects a stretch with signed
endpoint average grade. A map/profile click or Escape clears the selection.
Shift+arrows extend keyboard selection. Map expansion retains one map instance.
Personal history and leaderboard links use explicit identities and supplied
recordings; imported IDs are rekeyed. Climb → ride → climb preserves the original
viewer. Signed-out climb previews use the existing visitor ride preview, not
owner controls. Missing leaderboard data does not assert an empty leaderboard.

The default personal/leaderboard context is illustrative and declared in Data.
The live public JSON is retained in `climb/data/`; no times or Vault are inferred
from it. The Vault scenario separately supplies an illustrative 1,200 CAL viewer
position and Waiting state. It offers inspection only, no transaction controls,
DUNG values, aggregate deposits or inferred settlement state.

Local verification: 82 workshop tests, typecheck and build pass. Model failures
for viewer routing and reordered leaderboard imports were reproduced before
fixing. Browser checks cover all six scenarios and three viewer modes, import,
map clear/expansion, keyboard selection, modal Escape/focus return, loading and
error recovery, and navigation between workshops. Exact 1440 × 1000 and 390 × 844
V2 captures are in `climb/evidence/`; live captures are in `climb/references/`.
This is a local workshop candidate, not production integration or live rider proof.
