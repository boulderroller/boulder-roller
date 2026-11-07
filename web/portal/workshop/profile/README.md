# Rider Profile Overview · Candidate V2

Preview: http://localhost:4330/?surface=profile&variant=profile-v2&scenario=owner

Owner: `boulderroller-v2-hnrkn`, branch `codex/hnrkn-profile-v2`, worktree
`/Users/gabetemp/curahee/BoulderRoller-worktrees/profile-v2-workshop`.
The user explicitly admitted five room workshops in parallel for this batch;
this exception is recorded on the owning Bead. This task has one implementation lane.

## Design and supplied truth

The current-run V1 inspection found that its tall map opening separates rider
identity and standing from recent rides/history. The retained Strava Overview,
History and More history references bring identity, sporting results and riding
history into a clearer reading order. Their 430 px phone captures also reveal a
wide desktop layout, so they are hierarchy references rather than a responsive
layout template.

The corrected V2 uses the current workshop composition: a 56 px dark olive
shell (52 px phone), light paper, a 1148 px white reading surface, pale olive
identity/result groups, proportional tabular figures and closely aligned rows.
Identity leads; the supplied climb best and recent rides follow; month and
measurement controls provide an explicit history view. Totals cover only the
shown rides. No map, geometry, photograph, rank or result has been invented.

### Source discussion correction · 13 September 2026

The original dark draft used production tokens, a 72 px shell, an 88 px avatar,
monospaced headline figures and widely separated bordered sections. That missed
the newer workshop direction. It is preserved as `DraftProfileV2.tsx` and
`draft-profile-v2.css`, accessible with **Original draft** in the toolbar or
`/?profile-preview=1&scenario=owner&draft=original`. The source checkpoint is
`3c2ddeb004b2d7b901b9148a47f863aa4f33f4a6`; V1 remains separately frozen.

Before the correction, actual user messages and paired design responses were
read from both named tasks. Newer turns omitted by `read_thread` were read from
the exact session files with matching task IDs, excluding tool logs. These were
the applicable user decisions, not inferences from task summaries:

- **Critique Strava portal audit** (`01a08890-52a0-7f51-bd6d-51a5279c5872`):
  carry typography forward between rooms (turn `01a091b9-c369-7fb1-9c03-080b19082651`);
  reduce Feed headroom and excessive card whitespace (`01a097c4-4edb-7dc1-858e-adcb49df8a78`);
  preserve the accepted light/green identity balance (`01a09839-5fff-74b3-bf62-1cd76d1120c1`);
  give complete rows quiet hover feedback instead of multiple disconnected
  highlights (`01a0987e-8233-7062-8066-75151c7bd615`);
  keep the dark navbar stable (`01a09b7d-f4f4-7771-8782-5004d39ddc49`);
  cluster identity, date, time and place deliberately (`01a09ba3-603d-7752-87f8-0e36f533269e`);
  tighten data while making it more legible, removing empty compartments and
  excessive links (`01a09bc8-b676-7a52-aa0b-75158a78501c`).
- **Find Strava portal audit thread** (`01a09b16-1c41-7462-87c9-658914226e24`):
  minimum useful interface above the content and natural return continuity
  (`01a09b78-4622-76f1-8a63-5a1c5d42c677`); considered containers, readable
  numbers and clear hierarchy (`01a09bae-b160-7462-af0c-2f50193065cb`). Later
  revisions continue the same family of carefully finished compact tiles;
  they do not authorize inventing activity, place, or geometry on Profile.

Donors were inspected read-only. Ride V13 inherits `candidate-v12.css` through
`candidate-v13.css`; Feed V9 imports V12 and `feed-v3/v4/v5/v6/v9.css`.
The scoped Profile styles carry the shell/ground and reading-surface patterns,
Feed V9's `.f9-rider-intro`, `.f9-rider-ride` and `.f9-rider-standing` grouping,
and Climb V7's narrower supporting column and proportional figures. Map V4
informs restraint and coherent card edges, without borrowing its geography.
No whole donor cascade or unrelated branch was merged.

Climb V7 donor: `6864083ac2a3b40a55e7fb8b061135c237ea3cbd`.
Map V4 donor: `ebf7b3917c1d07ace6c387f6f2a30278d943cc80`.
Ride V13 / Feed V9: shared checkpoint `ac161705a0d198f46de906be296f9f7ce5953450`.
The Climb preview is served by the newer Climb V8 worktree, with V7 selected;
its V7 component and inherited candidate styles were checked unchanged against
the named V7 donor commit.

All responses come from `baseline/fixtures/portal.ts`, retained from
`e2e/portal-v2-routes.spec.ts` at revision
`a63ffc77f9638b78d3a404be2575aaa7ddd9c145`, anchored 5 May 2026.
V1's source archive and all 441 materialized source files remain unchanged.
Seven scenarios remain selectable: own rider, another public rider, private,
empty history, loading, unavailable and retained/offline.

The historical Strava references were captured 9 September 2026: desktop
1440 px, phone 430 px. They retain their own provenance in
`baseline/references/provenance.json`. Boulder Roller phone renders are 390 px.

## Honest limits and navigation

- The owner has one supplied Manayunk Wall best time. Its compatibility rank
  is not current sporting place; V2 shows place unavailable.
- Tim's public profile contains 12 total rides but only three recent rows.
  Their totals are explicitly a subset. The generic standing fixture belongs
  to another wallet, so Tim's standing remains unavailable.
- The empty-history recipe removes ride rows while retaining a supplied climb
  result. V2 does not fabricate an all-zero sporting history.
- The supplied `climb-1` detail fixture names a different Climb than the Profile
  list. The candidate therefore does not navigate that best-time link into the
  mismatched specimen. Public/imported summaries without matching detail also
  disclose that absence. Owner Ride links open matching retained Ride details.
- Provenance contains separate, explicitly labeled review links to Ride V13
  and Climb V6. Those candidates use different supplied data. Browser Back
  restores the Profile month and measurement. Explicit Profile-tab journeys restore their own
  room's saved scenario/candidate. Shared browser-history traversal can retain an
  older destination-room snapshot after edits in that other room; that existing
  harness behavior is not rewritten here. Profile's own month/measurement survive Back.
- There are no social writes, account changes, signing or money operations in
  V2. Public/private projection denies hidden modules and inconsistent privacy.
  A private profile displays no redaction sentinel totals or rider identity.

## Verification and integration

`evidence/correction/scenarios/` contains the corrected seven-scenario render
matrix at exactly 1440×1000 and 390×844. `evidence/correction/comparison.html`
shows actual side-by-side Profile renders with the preserved draft, Feed V9,
Ride V13, Climb V7 and Map V4 at both widths. Each pair uses equal source scales.
`comparison.json` records capture URLs and runtime/overflow checks. Earlier
`evidence/final/` and V1 captures remain unchanged as the original draft record.
`evidence/correction/interactions.json` records keyboard, pointer and emulated
phone tap journeys, history filters, private-tab ownership, compatible detail
navigation, reference section widths, Squint, file/paste imports, JSON
copy/download/restore, loading/error/offline recovery and return state.
These are local supplied-data and browser-emulation results, not production or
physical-rider evidence.

Focused regressions and their initial failures are retained in `evidence/`.
Run from `web/portal`:

- `npm run workshop:test`
- `npm run workshop:typecheck`
- `npm run workshop:build`
- `./node_modules/.bin/tsx workshop/profile/verify-profile.mts`
- `./node_modules/.bin/tsx workshop/profile/compare-profile.mts` (donor previews on 4318 and 4323 must be running)

Shared changes are limited to Profile metadata/default selection in
`roomRegistry.ts` and two imports plus Profile workshop/preview dispatch in
`main.tsx`. They are committed separately for the integration owner to reconcile
with the parallel room registrations. No baseline, other candidate or shared
integration checkout was edited. The branch carries the exact shared checkpoint
`ac161705a0d198f46de906be296f9f7ce5953450` in its ancestry. Merge the completed branch
checkpoint explicitly; do not copy dirty files or synchronize worktrees.
No merge to main or deployment is included.
