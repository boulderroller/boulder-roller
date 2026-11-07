# Canon Build Decisions

**Status:** RATIFIED — decisions locked 2026-07-05 (Tim + CTO session); D10
tolerance policy and D13 boundary-agreement metric ratified 2026-07-21
**Audience:** The engineer agent(s) implementing epic `boulderroller-v2-4crx`
**Governing truths:** `docs/PROTOCOL_TRUTHS.md` §14 (Climb Canon) and §15 (Zero-Start)

These are pre-called design decisions for the canon compiler, schema,
traversal engine, and cutover. **Do not reopen them mid-implementation.**
If implementation reveals one is genuinely wrong, stop, write down why, and
queue it for the weekly ratification batch — do not silently pick an
alternative. Anything *not* covered here is agent-autonomous.

---

## Product decisions (Tim, 2026-07-05)

### D1. Launch canon scope: paved roads only
Rideable-way whitelist for the Philadelphia compile: `residential`,
`unclassified`, `tertiary`, `secondary`, `primary`, `living_street`,
`cycleway`, plus `service` only when named. Exclude `motorway`/`trunk`
(unless a mapped parallel cycleway), `track`, `path`, `footway`, `steps`.
Gravel/trail compilation ships later behind a compiler flag — it is not
launch scope. Surface tags in OSM are unreliable: default-allow whitelisted
highway classes; do not require `surface=paved`.

### D2. Timing: elapsed time, always
Traversal time is wall-clock between gate crossings. No pause credit, no
moving-time subtraction. Lights are part of the hill. This matches TRUTHS
§14.6 (whole-second precision, ties share rank) and cannot change later
without a canon version bump on every affected climb — treat it as
constitutional.

### D3. First canon size: curated dozens (~30–60 ratified climbs)
The compiler may emit many more candidates; the ratified launch canon is
30–60 climbs, every one hand-ratified by Tim in ClimbLab. Optimize the
review surface for that workload. The discovery loop grows canon afterward.

---

## Engineering decisions (CTO)

### D4. Compiler lives in the workout-parse Rust workspace
New binary (e.g. `workout-parse/src/bin/canon_compile.rs`) plus a `canon/`
module. Reuse `geo_features::OsmParser` (already parses PBF → road features
with class filters), `polyline.rs` (encoding), and `climb/persistence.rs`
(persistence machinery — repointed at clean road profiles). No Python in the
compile path. Compiler runs on Tim's Mac as a batch job; production runtime
only ever reads database rows. Never call public elevation APIs from the
compiler (ClimbLab's OpenTopoData/Open-Meteo constants are dev-only toys).

### D5. Graph construction: node-sharing with layer awareness
Build the road graph from whitelisted ways; an intersection is an OSM node
shared by ≥2 whitelisted ways, **except** where `bridge`, `tunnel`, or
differing `layer` tags mean the roads do not actually meet. Grade-separated
crossings are not junctions and must not become gate-snap targets.

### D6. Elevation: 3DEP 10m, tiles downloaded locally
Primary DEM is USGS 3DEP 10m (lidar-derived for PA) as local COG GeoTIFFs.
1m 3DEP is reserved for disputed profiles, not the bulk compile. Densify way
geometry to ~10m point spacing; bilinear-interpolate elevation per point.
Flag low-confidence profile segments (bridges, high curvature, dense canopy
where derivable) rather than silently trusting them. Record
`dem_source` + compiler version per candidate (TRUTHS §5.2 attested truth).

### D7. Ascent-chain extraction
1. Annotate every edge with draped gradient.
2. Seed chains from edges above a starting-gradient threshold.
3. Extend across intersections by **natural continuation**: same
   `name`/`ref` first, else smallest turn angle; cap branching; apply drop
   tolerance within a chain.
4. Run persistence over the assembled chain profile to set the canonical
   span (this is where `persistence.rs` earns its keep on clean data).
5. Snap start/finish to intersection nodes or clear gradient inflections
   within ~150m, per `docs/rfcs/SEGMENT_WORTHINESS_MODEL.md` (intersections
   are boundary magnets).

#### D7.5 finish controls (Tim, 2026-10-20)

A finish gate never sits at, or past, a traffic control. At a junction with
`highway=traffic_signals`, an all-way or climber-facing stop, a climber-facing
give-way, `crossing=traffic_signals`, or a rail crossing on its node or within
30m along the climb's own way, set the finish 25–30m before the junction
centre (default 27m), and at least 15m before every applicable control or mapped
stopping line. A junction joins differently named roads on the same layer;
a same-road way split does not qualify. Recheck controls around each cut
until clearance holds. Recompute the span and net rise from the unrounded
canon profile; snap a sub-metre last segment upstream and keep the gate
perpendicular to the resulting final segment. Starts and interior timing
retain D2/D11. A changed finish uses the default 25m half-width: D10 overrides
whose centre/span changed are superseded. An unchanged start gate keeps an
evidence-backed D10 width as an active, re-evidenced revision on the
successor (Black Rock's 30m start; see the finish decisions file).
Every moved finish follows §14's new-version/fresh-Record-Board rule.

The [implementation brief](../../history/codex-briefs-2026-10-20/gate-rule.md)
admits the research's 15 finishes (Tim, 20 October: “yes all 15”).
Under [Claude's fix-round-1 call](../../history/codex-briefs-2026-10-20/gate-rule-fix-1.md),
the 15m clearance takes precedence over the default 25–30m setback band.
On 20 October Tim also approved two stop-evidence shifts (“yes shift both
back”): Wises Mill to 30m and Centennial to 29.06m before the junction, each
15m clear of a recurring stop spot in his own rides.
Additional compiler findings are “proposed by rule, not admitted”; see the
[offline review report](../../history/codex-reports-2026-10-20/gate-rule/REPORT.md).
No successor publication is authorized by this rule's implementation.

A founder-approved crest finish may end a climb at its natural top without a junction, as approved for [Lafayette Road's lump crest](../../history/codex-briefs-2026-10-20/lafayette-crest.md) on 21 October 2026 at 00:13 UTC; D7.5's junction setback does not apply to that crest.

### D8. Canon climbs are directional
One canon climb = one span ridden in one (ascending) direction. The far side
of a hill is a separate candidate. Gates encode direction; traversal must
match it.

### D9. IDs are registry-owned; the compiler emits fingerprints
The compiler never assigns canon ids. It emits **candidates** keyed by a
geometric fingerprint (e.g. hash over ordered way refs + span endpoints) used
to dedupe across recompiles: a re-run of the county must recognize existing
candidates/canon by fingerprint overlap and propose diffs, never duplicates.
Stable opaque `canon_id`s (UUID) are assigned once, at **ratification**, by
the registry (database), and never change thereafter. Version starts at 1.

### D10. Geometry representation
- Corridor: way geometry buffered ~25m each side. Stored as PostGIS geometry
  (Supabase has PostGIS) **and** as H3 res-10 cell set for the fast path.
- Gates: line segments perpendicular to the road at the boundary, ~25m
  half-width, stored as coordinate pairs. Gates are geometric lines, not hex
  cells — timing interpolates raw GPS crossings to ±1–2s at 1Hz.
- Canonical profile: ordered `(dist_m, elev_m)` pairs at ~10m spacing,
  compact JSONB in v0.
- Every canon row carries ODbL provenance (source way refs, extract date).

<a id="d10-revisions-and-identity"></a>

#### D10 capture-tolerance policy (Tim, 2026-07-21)

- The default gate half-extent remains **25m** and the default corridor
  half-width remains **25m**. There is no global widening.
- A ratified candidate may use an evidence-backed, symmetric perpendicular
  gate half-extent up to **40m** and corridor half-width up to **35m** only
  when its gate anchor and center, gate orientation, centerline, and measured
  start-to-finish span remain unchanged.
- Each override is a deterministic minor geometry revision. Its exact widths,
  evidence source, prior geometry policy, and revision provenance must be
  recorded. It keeps the same `canon_id` and carries records forward.
- Moving a gate anchor or center, changing gate orientation, changing the
  centerline, or changing the measured span is a boundary change. It follows
  the normal new-version and fresh-Record-Board rule; a tolerance override
  must never disguise it as record-continuous maintenance.
- Compiler v0.2.4's gate-arm conformance repair makes an emitted arm equal its
  configured extent. That repair is not approval to exceed the default or the
  per-candidate limits above.

### D11. Traversal rule
Gate-in → gate-out in the canon direction, ≥80% of intermediate GPS points
inside the corridor, monotonic along-track progress (no U-turn credit).
Each qualifying pass is a separate traversal; a ride's best traversal per
climb feeds records. Partial traversals produce nothing (no partial times).
Crossing time = linear interpolation between the bracketing GPS samples.
Economic elevation always comes from the canonical profile, never rider
barometry (TRUTHS §14.6).

### D12. Canon commitment byte layout (64 bytes, for the vault field)
```
[0]      version        = 0x01
[1..17]  canon_id       (UUID, 16 bytes)
[17..19] canon_version  (u16 BE)
[19..32] reserved       (zero)
[32..64] blake3(canonical profile bytes)  (32 bytes)
```
Defined now so the Anchor/cutover lane (`4crx.11`) never waits on the
compiler lane. The profile-bytes serialization used for the hash must be
specified in code with a test vector.

### D13. Validation ground truth
Run the corpus replay (`4crx.10`) and report Philadelphia coverage
explicitly. If the golden corpus is thin on Philly (it spans 4 geographies),
Tim's Garmin ride archive — which ClimbLab already inventories from
`/Volumes/GARMIN/Garmin/Activities` — is the primary traversal validation
set, plus the dogfood harness fixtures. Manayunk Wall is the reference
climb: if its boundaries don't land where a Philly cyclist would put them,
the compiler is wrong, whatever the metrics say.

#### D13 amendment: geometry and timing agreement (Tim, 2026-10-20)

The founder ratified these changes after review of the clipped-projection
finding. The [20 October implementation brief](../../history/codex-briefs-2026-10-20/gate-consistency-2.md)
records the decisions. The July contract is retained below as history.

- **Correct the crossing calculation.** Project the observed gate intersection
  itself onto the canonical centreline, in the local metric projection. Do not
  interpolate the already-clipped projections of its bracketing samples.
  Compare every crossing's progress with its Climb/gate median, pool the absolute
  deviations, and require nearest-rank **p95 ≤ 10 m**. Eligibility still requires
  at least two distinct rides per Climb/gate; repeated crossings keep their full
  weight. Keep the strict maximum and per-gate p95 as diagnostics.
- **Name what this measures.** Corrected D13 is a **gate-geometry check**, not a
  measure of physical GPS accuracy. For straight perpendicular gates it can
  only fail where an arm reaches beside another part of the road, at a bend.
  It passes at about **0.03 m** on the current corpus. That small number is
  largely a consequence of the geometry; it is not centimetre-level rider truth.
- **Add an independent timing-agreement cutover bar.** For every accepted crossing
  recorded at 1 s, keep every eighth sample at **all eight offsets**, and compare
  each thinned, interpolated crossing time with the original interpolated time.
  Pool absolute changes with full crossing/offset weighting and require
  nearest-rank **p95 ≤ 2 s**, reporting the median, p95, maximum and denominators
  both pooled and per gate. At about 5 m/s climbing speed, 2 s is the founder's
  10 m expressed in the unit the leaderboard uses. The review measured a median
  of 0.13 s and p95 of about 1.5 s before the final finish-rule fix.
- **Guard recording pauses before scoring.** A 1 s crossing has a positive
  bracketing interval no greater than 1.5 s. Every original interval inside a
  span covering the original and thinned brackets must also be positive and at
  most 1.5 s, with consecutive
  source samples. Never bridge a recording pause and call it an eight-second
  sample. Report pause-guarded and recording-edge offsets, non-1 s crossings,
  and lost/ambiguous forward crossings explicitly. Guarded offsets carry no
  fabricated zero error. Lost/ambiguous crossings remain in the p95 population,
  ranked beyond every finite error (positive infinity); they cannot disappear
  from its denominator. If the p95 rank reaches that tail, the bar fails with
  an unbounded p95. Missing probes or a missing denominator cannot pass. The
  median and largest measured change are reported separately from this failure
  tail. Use the reviewed three-stride neighbourhood on each side of the crossing;
  multiple forward crossings in a phase are ambiguous, not an invitation to
  select the closest time. Climb/gate
  eligibility remains two distinct accepted rides, fixed before examining errors.
- Freeze all observations and timing probes before scoring; report input hashes,
  eligible groups/rides, crossings, compared offsets and guarded denominators.
  Preserve elapsed timing, the 80% corridor rule, direction and U-turn rejection,
  and all accepted-crossing weighting. Neither bar changes which efforts the
  traversal engine accepts. The old calculation is available only through the
  explicitly named `--legacy-clipped-projection` historical-reproduction flag;
  it cannot authorize the current boundary cutover bar.
- Scan all gates for arms projecting beside bends, including gates without rides.
  These flags support boundary review; they do not change the two pooled bars.
  **Lafayette Road finish** remains for the founder's Finish Lines review.
  **Bryn Tyddyn Drive start**, with its roughly 100° bend and no rides yet, also
  requires founder boundary review before publication. Do not move either
  boundary under this amendment. Report Andorra Road finish and Rockland Avenue
  start in the geometry review, and Black Rock start and Centennial's moved
  finish in the timing review. (Resolved 21 October: Lafayette got its crest
  finish; Black Rock's and Bryn Tyddyn's starts stay. See the edge cases below.)

#### Edge cases: what makes a climb (Tim, 2026-10-21)

The rules above describe ordinary climbs. Some roads are edge cases, where the
road's own character settles a boundary rather than a metric. The founder
decides each one. Record it here, so later reviews report it as an accepted
edge case and never re-propose the change.

- **Black Rock Road start: the run-in.** Riders cross the start already
  carrying speed off the bridge approach: “that hill is always whooshed into
  just a fact of the hill”. The start stays where it was ratified, with its 30m
  D10 width. Its timing-agreement miss is accepted: 12 of 23 one-second
  recordings move more than 1s when thinned, and the gate's p95 is unbounded.
  Report it as an accepted edge case, not a defect. Options considered:
  [start-lines research](../../history/codex-reports-2026-10-20/start-lines/REPORT.md).
- **Bryn Tyddyn Drive start: the driveway bend.** The ratified start sits on a
  roughly 100° bend. The founder: “its basically someones driveway … what
  makes a climb, this is a special case”. The start stays as ratified, and its
  gate-geometry flag is accepted: one arm projects 36m along the canon, the
  largest of the 114 gates. No rides yet.
- **Lafayette Road finish: the natural crest.** The finish ends on the
  climb's natural top with no junction, under the crest-finish rule in D7.5
  above.
- **Wises Mill and Centennial finishes: where riders actually stop.** Each
  finish keeps 15m clear of a recurring stop spot in the founder's own rides,
  not only of mapped controls.

When the compiler or the climb finder meets a road like these, flag it for
founder review as a candidate edge case instead of forcing the rule. Examples
are momentum run-ins, driveway entries, natural crests and unmapped stops.

#### Historical D13 repeat-ride boundary-agreement metric (Tim, 2026-07-21)

- Measure each observed start or finish crossing as an **along-track distance
  on the canonical centerline**. For each Climb and gate, compare every
  observation with that Climb/gate's repeat median and take the absolute
  along-track deviation.
- A Climb/gate is eligible only when its observations come from at least
  **two distinct rides**. Pool all eligible endpoint deviations; the cutover
  gate passes when their p95 is **less than or equal to 10m**.
- Preserve the strict maximum as a diagnostic. It does not replace the p95
  pass/fail rule.
- Freeze the observation set before calculating the outcome. No observation
  may be removed after seeing its deviation or the aggregate result.
- Before `4crx.10` closes, its scorecard must encode this exact arithmetic and
  report the eligible Climb/gate count, distinct ride count, endpoint count,
  p95, strict maximum, and input manifest hashes. The ratification evidence
  snapshot contained 176 endpoints, with p95 **4.416m** and strict maximum
  **12.763m**; a passing snapshot does not waive the required full replay.

---

## Canon math freeze (compiler v0.2.x, 2026-07-18)

This section records the implemented arithmetic for D1, D6, D9, D10, and
D13. These rules are part of the compiler contract, not tuning knobs.

- **Road scope:** unnamed `service` ways cannot launch or bridge a candidate.
  Named service roads remain launch-eligible under D1.
- **Directional extraction:** compiler v0.2.1 treats every v0.2.0 primary
  candidate as an exact compatibility floor, then runs a supplemental
  pre-chain pass for the opposite source-profile orientation. The supplemental
  pass selects at most one maximal persistence span per orientation, requires
  its own positive net rise and candidate thresholds, and emits only a new v3
  fingerprint. Directional fragments may reuse source ways without taking
  ownership from the primary chain. Equal-score supplemental continuations use
  a stable way/direction/geometry key; a segment is consumed by a supplemental
  chain only after that chain produces a new fingerprint.
- **Vertical:** candidate `vert_m` is finish elevation minus start elevation.
  It is not cumulative positive gain. Profile segments shorter than 1m do not
  contribute a gradient, so duplicate coordinates cannot manufacture a grade.
- **Confidence:** `high` requires score >=75 with no material flags; `medium`
  requires score >=55 with no material flags; `needs_review` requires score
  >=35 with at most one material flag; all other candidates are `low`.
  `topographic_isolation_not_scored_v0` is explicitly informational until
  isolation is implemented, so it does not make `high` unreachable.
- **Fingerprint:** `blake3_way_refs_geometry_sketch_v3` hashes ordered OSM way
  refs plus 17 fixed along-track centerline samples quantized to a 0.00005
  degree grid. Harmless centerline resampling and elevation/profile changes
  preserve the candidate fingerprint. Sub-meter coordinate noise is stable
  while it remains inside the same grid cells; crossing a cell boundary is a
  geometry change. Material centerline or ordered-way changes do not preserve
  the fingerprint. The canonical profile has a separate hash; a profile-hash
  change keeps identity but requires a new ClimbLab check. Every v3 candidate
  also emits its exact endpoint-only v2 lineage fingerprint:
  ClimbLab carries the matching prior decision but requires recheck, and the
  publisher locks the matching registry lineage before upsert. An exact-current
  fingerprint republishes the current row without advancing its version. A
  changed boundary fingerprint creates a successor row with the same
  `canon_id`, `version + 1`, `supersedes_climb_id`, and
  `record_continuity_policy = new_record_board`; the prior row is retired but
  remains permanent. Lineage spanning multiple canon identities, an unknown
  newer version, or an unratified predecessor fails closed.
- **Corridor:** the database authority is a metric PostGIS geography buffer of
  the centerline using the candidate's half-width (25m by default; at most 35m
  for a provenance-bound per-candidate D10 override). H3 res-10 coverage
  conservatively expands densified centerline and gate cells by that width.
  Republish deletes the candidate's old cells before inserting the new set.
  The compiler's `corridor_wkt` is a conservative review preview, not the
  stored corridor authority.
- **DEM registration and seams:** the exporter honors
  `GTRasterTypeGeoKey`: PixelIsArea samples are shifted to pixel centers and
  PixelIsPoint samples are not. Missing registration defaults to PixelIsArea;
  malformed values or mixed registration across tiles fail the export. Chained
  way profiles require endpoint elevation seams within 8m in either direction.

The 137-candidate Tim review fixture remains the field judgment input. Unit
fixtures freeze the arithmetic above.

### Boundary ratification update (2026-07-18)

- D1 remains unchanged. Spring Garden Lane / Rene Road is excluded from the
  launch canon; do not restore an unnamed service-road connector exception to
  manufacture that candidate.
- Tim's original named-gate notes for the other ten disputed climbs are hard
  boundary requirements. If the current compiler or source data cannot emit
  them, treat that as engineering work rather than permission to move the gate.
- Falls Road starts at the midpoint of the first curve coming off Falls Bridge,
  not at the Falls Road / Conshohocken Avenue junction. Tim visually approved
  the gate on 2026-07-19: OSM node `110113531`, center
  `40.0072221, -75.1990102`, with a 25 m half-width perpendicular line from
  `40.0073808, -75.1992190` to `40.0070634, -75.1988014`. Preserve the approval
  image at
  `history/canon-boundary-ratification-2026-07-18/falls-road-gate-review.png`.
- Parker / Umbria and Hagys / Hollow are validated boundary outcomes to preserve
  through the current compiler recompile.

### Boundary implementation outcome (2026-07-19)

- Compiler `canon-compile-v0.2.3` applies the tracked eleven-decision
  Philadelphia boundary registry after the generic pass. Every decision must
  replace exactly one known fingerprint; prior fingerprints remain explicit
  lineage, and duplicate or ambiguous identity fails closed.
- Tim's approval evidence and the agent-autonomous OSM translation are separate
  fields. The ten named requirements cite Tim's July 18 decision and the pinned
  OSM fixture cites the exact geometry translation. Falls Road additionally
  carries Tim's July 19 visual approval of the exact gate line.
- The pinned 53-way 3DEP profile bundle is authoritative over the generic DEM
  export for those ways. An explicit custom bundle can override it. Compiler
  reports record the base and supplemental profile digests, road-graph and
  registry digests, profile replacement counts, and applied and retained
  decision counts.
- Ordered ways must join through one real shared OSM node. Declared OSM-node
  anchors are verified against node-ID-aligned source geometry, and ambiguous
  seams, anchors, or fingerprint lineage reject the whole replacement set.
- Exact timing-gate geometry participates in candidate identity. A changed gate
  requires review under a new fingerprint. Publishing through legacy lineage
  preserves the prior row and creates a same-`canon_id` successor at the next
  version with a fresh Leaderboard.
- `--max-candidates` fails before removing a ratified boundary. It cannot emit a
  partial approved set while claiming all decisions were applied.
- Diagnostic skip mode cannot emit SQL, and ClimbLab plus the DB publisher
  refuse to publish any compiler report whose run mode is not `applied`.
- A fresh Pennsylvania field compile emitted 2,051 candidates: exactly eleven
  tracked replacements, 2,040 otherwise unchanged candidate objects in the
  same compiler run, zero anchor offset for all approved gates, and zero
  geometric or elevation seam at every ordered-way join. The combined Spring
  Garden Lane / Rene Road climb remained absent. Parker / Umbria and Hagys /
  Hollow remained unchanged.
- ClimbLab carries a decision only through one exact lineage match. Explicit but
  unmatched lineage and ambiguous route-only matches remain new work instead of
  inheriting the first same-name review record.

The detailed historical measurements and the complete named-gate list live in
`history/CANON_PHASE1_BOUNDARY_DIFF_2026-07-06.md`. The implementation evidence
and field diff live in
`history/CANON_BOUNDARY_RATIFICATION_OUTCOME_2026-07-19.md`; closure remains
under `boulderroller-v2-4crx.7`.

---

## Standing constraints (inherited, restated for one-page handoff)

- Two live lanes + one gate max; this epic is one lane (AGENTS.md cadence).
- Keep the matched-climbs API response shape stable through traversal work.
- No shadow modes in production; validation is offline replay tooling.
- Rider-first language on any surface work (LANGUAGE_SPEC.md); "canon",
  "registry", "commitment", "gate" are internal vocabulary, not rider copy.
- Detector heuristic tuning stays frozen; the detector's only new work is
  the discovery/nomination queue.
