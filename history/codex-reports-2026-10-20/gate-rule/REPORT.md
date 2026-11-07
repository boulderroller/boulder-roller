# Finish gates before traffic controls

20 October 2026 · `boulderroller-v2-6ewxw` · local/offline evidence only

The [Lafayette crest amendment](#lafayette-crest) extends Lafayette Road by 715.53 m to the founder-approved natural top. The other 56 retained climbs and all 15 previously prepared successors remain unchanged. The shared pack now contains 16 review-only version-2 successors. Nothing was pushed or published; no production, droplet, Supabase or devnet writes occurred. The Bead remains in progress for Claude's review and landing.

## What remains

Founder placement approval is complete in [APPROVALS.json](APPROVALS.json), including both dated round-3 amendments with “yes shift both back” and the Lafayette crest decision. The existing West School House M1 note and 0.5 m position binding remain intact.

- Field checks remain for **Black Rock, Youngs Ford, Port Royal and Centennial paint**. The stop spots below are consenting single-rider aggregates, rounded to five decimals; they are not surveyed stop lines.
- Corrected boundary and timing metrics now use the gate-consistency lane's pinned definitions. The local results below do not establish all other publication gates. The earlier bracket-progress metric is explicitly retained as legacy diagnostic evidence.
- Publication remains separate: explicit go, fresh registry/registration checks and actual ratification actor/time are required. The September manifest is retained indexed evidence; its only indexed climb, Shawmont Avenue, remains unchanged.

## Lafayette crest

The [founder's decision](../../codex-briefs-2026-10-20/lafayette-crest.md), recorded at **2026-10-21 00:13 UTC**, is `decision: "extend_crest", finish_at: "lump crest", finish_m_past_current: 715.53`. It is now a tracked **crest finish (founder-approved)** boundary decision in `philly_ratified_boundaries_v1.json`, with an amendment in [APPROVALS.json](APPROVALS.json). D7.5 now explicitly permits an approved natural top without a junction. The crest uses the existing boundary compiler; there is no Lafayette-specific branch in generic code and no D7.5 junction-setback provenance on this successor.

The ordered route is **12370459 → 12329089 → 594346758 → 12370452**. The existing start gate is exact and unchanged. The finish is at **40.05129374835202, -75.29571220380879**, square to the road with the standard 25 m half-width. The retained OSM/3DEP evidence places it at the downhill edge of the 709.67–715.53 m flat top, 106.73 m before Conshohocken State Road and about 93 m before its climber-facing stop. These are retained map/DEM findings, not a new physical survey.

| Compiler quantity | Previous Lafayette | Crest successor |
|---|---:|---:|
| Length | 1,528.87 m | 2,244.40 m |
| Net rise | 74.28 m | 101.30 m |
| Average grade | 4.858% | 4.513% |
| Maximum sampled grade | 24.944% | 24.944% |
| Canon version / leaderboard policy | 1 / retained | 2 / fresh leaderboard |

The new fingerprint is `7f759d3dc2bea4adb0380bd32c724c5e36d2ec911470e3651a21757bfca377a7`; lineage includes `5082caadd5b7828ea5593ab29ba803fc6b6d2bb70065f6ff9f6aa6a15b60d638` and its July v2 fingerprint. The existing publication resolver, exercised against the retained September rows, returns the same `canon_id`, version 2, and Lafayette's existing registry row as predecessor. No leaderboard or registry row has been created live.

The original 15 boundary decisions and 61 road/profile records are preserved exactly. Four Lafayette way records/profiles are appended. The two existing long-way profiles are copied from the July export; only the two missing short-way profiles are sampled from `USGS_13_n41w076_20221115.tif`, at the compiler's 10 m spacing using the retained `ext_profile.py` half-pixel east/south convention. The pinned crest position is reused, not recalculated from a different elevation source. Length, net rise, grades, canonical profile/hash, fingerprint, corridor and gate are produced by the compiler.

### Lafayette replay

[The aggregate replay](../lafayette-crest/REPLAY.json) scans all **1,416 rides**, with **115** gate-screened ride/climb pairs, through the unchanged `backend/app/services/canon_traversal.py`. SQLite is opened with `mode=ro&immutable=1`; integrity and the original corpus SHA-256 are verified. Before uses the retained September PostGIS corridor; after uses a local exact 25 m metric buffer around the compiled extension. This is local replay evidence, not evidence of a published PostGIS successor or new riding.

- **Traversals: 7 → 7**, on seven distinct rides, with zero losses and zero additions. One further forward crest crossing has no complete start-to-finish traversal and remains uncounted.
- **Time added:** median **97.794 s**, range **79.910–118.203 s**, across all seven paired traversals. Whole-second duration differences have median 97 s and range 80–118 s. No stopped time is removed.
- **The two corner-cutters do not count on the extended climb.** A fresh diagnostic replay using the pinned gate-consistency 27 m inset identifies exactly two efforts that miss the current finish; neither completes the crest climb. The retained `ext-rides-out3.txt` independently says both turn **right onto Stony Lane**, while the extension turns **left up Lafayette**. The brief's prediction that they should now count conflicts with its own route evidence. The approved crest geometry and traversal rule are preserved; credit for an uncompleted extension is not manufactured.
- **Last-100 m stops:** 0/7 → **1/7 stopped efforts**, one **5.0 s** event about **61.09 m before the new finish**. The older retained note about no stops within 50 m of the crest does not cover this event. It remains part of elapsed time.
- The seven accepted crest crossings are **0.947–18.066 m** from the gate centre, consistent with the retained 0.9–18.1 m finding.

Metrics use the unchanged definitions at `codex/1hbjx-gate-consistency`, pinned to `8993e19996ce5c8c2bb050845e03bf5b13d9fa22` and scorer SHA-256 `ffb7e47bed3f8f779e50dad911c8555d6dc815a4245345669dd58dbf1016fad1`. Corrected boundary error projects the actual crossing point and measures deviation from repeat-median progress; timing retains all eight thinning offsets, including failures and pause/edge guards.

| Lafayette metric | Before | Crest |
|---|---:|---:|
| Corrected finish boundary p95 | 18.682 m | **0.014 m** |
| Corrected both-gates pooled p95 | 18.682 m | **0.025 m** |
| Finish timing-agreement p95 | 1.030 s | **0.256 s** |
| Both-gates pooled timing p95 | 0.929 s | **0.636 s** |

Both new per-climb pooled metrics meet the existing 10 m / 2 s bars. The finish timing sample has four dense crossings and 32 measured offsets, zero failed/guarded offsets; three non-1 s crossings remain explicitly reported. Previously it had 26 measured offsets plus six pause-guarded offsets. The start remains seven crossings, three dense, 24 measured offsets. These small-sample local results do not replace the wider publication gates. Only aggregates and public road geometry are committed; there are no new ride IDs, ordinals or tracks in this amendment's outputs.

### Lafayette verification and handoff

- Focused red: both crest tests failed because the decision was absent; the malformed-way test failed because its error omitted the climb name. Green: **100 selected Rust library tests**, **7 CLI tests**, and the full integration test pass. Missing/unknown ways, absent/null IDs and omitted connectors fail loudly with `Lafayette Road` in the error.
- Route assembly initially exposed an off-route orientation ambiguity. The correction bounds only ratified-anchor fitting; the existing traffic-control projection remains unchanged. A first, overly broad implementation was rejected by the full compile at Umbria Street and corrected before the passing runs. No guard or threshold was relaxed.
- **Two full compiles match byte for byte:** 2,051 candidates; all **2,050 non-Lafayette candidate objects** match round 3 apart from the compiler version label. This includes the 17 previously identified span additions, all 15 admitted traffic-control moves and all 33 below-minimum flags. SHA-256: `1b68afacb6c40b2532fbc32fbc610155c8b98b8404a13062bcaecff9207a3372`.
- **Two 57-climb offline runs also match byte for byte**, and their candidate values agree with the full compile apart from retained version labels. SHA-256: `7a08a405812cdb8e0085cb1792b25ba9aeeb1476b50909cbd2c6fda0462164b4`. The admitted review report changes exactly one candidate; the other 56 remain exact.
- **Commit checks:** `git diff --check` and the staged diff check pass. All four tracked guards pass: H3 resolution remains 10; detector parameters, tokenomics constants and devnet addresses are unchanged. The commit uses the tracked hooks without bypass.
- **Backend:** `pytest backend/tests -k canon` under the specified Python **3.12.8** environment: **340 passed, 2 skipped** (existing disposable-Postgres skips). The prescribed dummy token, SOLANA_STUB and locale environment was used.
- **ClimbLab:** the existing local review page and all **32 map/profile HTTP endpoints** pass; **zero publish-ready candidates**. [CLIMBLAB-PROBE.json](CLIMBLAB-PROBE.json) pins the pack. No review decisions, database connections or provider scans were made.
- **Successor-set count correction:** the assigned base contains **15**, not 17, prepared successors. Wises Mill and Centennial are already among those 15; their round-3 amendments did not add two new rows. All 15 existing successor objects are preserved exactly, and Lafayette is appended as the **16th** in [SUCCESSORS.json](SUCCESSORS.json). Every payload remains `review_only`; publication validation rejects Lafayette's payload. Both local profile-point arrays are absent from the entire outgoing set.
- The synthetic merge against current `origin/main` has only the previously known tracker insertion conflict. Its 1,566 common rows are byte-identical; main contributes `boulderroller-v2-jdipu`, this lane contributes the updated `boulderroller-v2-6ewxw`. Claude must preserve both rows when landing, for 1,568 unique IDs. No merge or unrelated tracker copying was performed here.

Full local inputs are pinned in [INPUTS.json](INPUTS.json); rerun the additive pack/replay with `../lafayette-crest/review.py --compiled /private/tmp/lafayette-crest-6ewxw/full/full-1.json --work-dir /private/tmp/lafayette-crest-6ewxw` under the brief's Python/environment. The Rust integration test additionally uses `CANON_TEST_CREST_PREVIOUS` for the exact round-3 full report and `CANON_TEST_RETAINED` for the retained 57-climb input. The local full-run invocation is retained at `/private/tmp/lafayette-crest-6ewxw/full.sh`.

**Ready for Claude's review and landing after the finish-rule branch.** The founder-approved crest is implemented; the corner-cutter recovery prediction is disproved, and no live successor is published. Existing field checks, fresh registry/registration checks, actual ratification metadata and a separate explicit founder publication go remain required.

## Round 3

The tracked compiler decisions and APPROVALS amendments cite stop-map commit `18a4fb39c` and the exact RESULTS.json SHA-256. Wises Mill uses **spot-0387**, six stops on six rides over six days, median 24 s, likely unmapped control (low confidence). Centennial uses **spot-0019**, seven stops on six rides over six days, median 10 s, mapped stop `5673550132` (medium confidence). Both source summaries and their five-decimal positions are copied exactly; no individual stop observations or source ride IDs are included.

The approved nominal setbacks are **30.0 m** and **29.0 m**. Projecting the published Centennial spot onto the unrounded approach leaves only 14.93552 m at exactly 29.0 m. Applying the existing 15 m clearance rule puts its actual finish another **0.06448 m** upstream, inside the approved 0.5 m tolerance. M1 is applied; neither new cut snaps to a vertex, and neither needs a covering note. The final serialized gate centres independently clear both published spots in UTM 18N.

| Climb | Round-2 setback → emitted m | Additional shift m | Native / serialized UTM clearance m | Offset from approved position m |
|---|---:|---:|---:|---:|
| Wises Mill Road | 27.00000 → 30.00000 | 3.00000 | 15.04190 / 15.05854 | 0.00477 |
| Centennial Road | 27.63579 → 29.06448 | 1.42869 | 15.00000 / 15.01441 | 0.06456 |

Both profiles and their hashes, fingerprints, lengths, rise and grades are recomputed. A grade may round to its previous displayed value.

| Climb | Length m, round 2 → 3 | Rise m | Average grade % | New fingerprint |
|---|---:|---:|---:|---|
| Centennial Road | 1612.16 → 1610.73 | 66.57 → 66.50 | 4.129 → 4.129 | `e866f61fc60da9b13e147eca297bed1c79a0bfcac58ecc797974b4eaf11dfcd8` |
| Wises Mill Road | 1060.96 → 1057.96 | 66.40 → 66.01 | 6.258 → 6.239 | `94dd6b16bbfb74da374f13844383c6c729a72b6b7f1f4724a18739ee68da8fbd` |

### Round-3 replay

Fresh immutable/read-only replay scans **1,416 rides**, **5,229** screened ride/climb pairs, with the unchanged traversal engine and the same retained September PostGIS corridors. The two affected climbs also run against their exact round-2 geometry. Registry baseline **425 → 470** accepted, **0 losses**, **45 additions**; frozen reference **94/98 → 94/98**. Corpus integrity and SHA-256 remain unchanged. A fresh private v4 checkpoint contains the timing probes; the old v3 cache was not reused.

| Climb | Traversals, registry / round 2 / round 3 | Last-100 m stopped efforts, same phases | Paired round-2 efforts | Median / range elapsed reduction s |
|---|---:|---:|---:|---:|
| Wises Mill Road | 18 / 18 / 18 | 10 / 0 / 0 | 18 | 0.888 / 0.582–1.313 |
| Centennial Road | 1 / 27 / 27 | 0 / 1 / 1 | 27 | 0.443 / 0.173–5.013 |

Every paired effort has fractional and whole-second changes in [REPLAY.md](REPLAY.md#round-3-wises-mill-and-centennial) and [REPLAY.json](REPLAY.json), including new/lost traversal lists. No stopped time is subtracted.

Metrics use `canon_traversal_replay.py` at gate-consistency commit `8993e19996ce5c8c2bb050845e03bf5b13d9fa22` (SHA-256 `ffb7e47bed3f8f779e50dad911c8555d6dc815a4245345669dd58dbf1016fad1`), read without editing or merging that lane. Corrected boundary projects the intersection itself onto the centreline. Timing uses all eight thinning offsets; pause/edge guards are counted, and missing or ambiguous crossings remain ranked as infinity. The reported value is the full-population p95, never measured-only p95. Both metrics retain every accepted crossing and require at least two distinct rides per gate.

| Climb, both gates pooled | Corrected boundary p95 m, round 2 → 3 | Timing p95 s, round 2 → 3 |
|---|---:|---:|
| Wises Mill Road | 0.018 → 0.018 | 1.705 → 1.661 |
| Centennial Road | 0.030 → 0.030 | 2.253 → 2.562 |

| Climb / gate | Corrected boundary p95 m, round 2 → 3 | Timing p95 s, round 2 → 3 | Round-3 timing comparisons / failed / pause offsets |
|---|---:|---:|---:|
| Wises Mill Road / start | 0.018 → 0.018 | 1.595 → 1.595 | 88 / 2 / 0 |
| Wises Mill Road / finish | 0.037 → 0.035 | 1.899 → 1.666 | 84 / 0 / 4 |
| Centennial Road / start | 0.035 → 0.035 | 1.518 → 1.518 | 130 / 2 / 14 |
| Centennial Road / finish | 0.010 → 0.015 | 9.634 → 3.287 | 124 / 5 / 20 |

Thresholds are corrected boundary p95 ≤10 m and timing p95 ≤2 s. The **all-57-climb pool passes both current bars**: corrected boundary 0.027 m and timing 1.883 s. **Centennial still has timing outliers**: its pooled per-climb p95 rises from 2.253 to 2.562 s even as the finish p95 falls to 3.287 s. Tim/Claude should inspect those remaining outliers and the paint field check. These per-climb/per-gate figures are diagnostics alongside the ratified full-corpus pooled bar. Other publication gates remain.

### Round-3 verification

- **107 Rust tests passed:** 97 canon library (42 finish-rule), one profile-exporter, one parser semantic-vector, seven CLI and one full-compile integration. The new regression failed on the former Wises Mill setback before the fix, then passed for both approaches, serialized clearance and position binding.
- **340 backend tests passed, two skipped, 3,381 deselected.** The two skips require disposable PostgreSQL; none was provisioned.
- **Two full compiles, 2,051 candidates each:** 304 moves (15 admitted, 289 unadmitted), 33 minimum flags, exact prior 17 span additions. The integration checks every geometry/identity/profile/metric field against round 2 and permits changes only for these two admitted finishes; all starts and other 2,049 candidates stay exact.
- Full byte-identical SHA-256: `e45459189984f2e8b1464ef6993497d8533bc865afa75c8f6e06d7e84e881608`. Two 57-climb offline outputs: `64b29d8560626c7761be9c0b2005fbe1a5fd045c247a5696e4d846de182459e4`. The retained 57 still have 15 admitted successors and 42 unchanged originals; 13 other successor geometries remain exact from round 2.
- **ClimbLab:** refreshed 30-entry pack, 30 ready map/profile HTTP endpoints, zero publish-ready entries and no review decisions written. Fifteen prepared successors remain review-only; both amended profiles/identities are included. [CLIMBLAB-PROBE.json](CLIMBLAB-PROBE.json) pins the current pack.
- Independent read-only review checked amendment scope, position binding, exact aggregate provenance, metric definitions and private replay boundaries. Normal tracked commit guards, exact diff and formatting are checked without bypass. Main advanced during the run to `da1f99e68` (V15 kit); the synthetic merge has only a tracker insertion conflict. All 1,566 common rows are byte-identical: main adds `jdipu`, this branch adds `6ewxw`. Claude should preserve all main rows verbatim plus the final owner row, yielding 1,568 unique IDs. This round keeps one scoped commit; no main merge or unrelated tracker row is included. No traversal engine, detector, profile-hash algorithm, H3 policy or protocol program changed.

The following round-2 sections are historical evidence. The round-3 results above and current REPLAY/DIFF/ClimbLab artifacts supersede their finish positions, hashes and scorecard status.

## Fix round 2 (historical)

| Review item | Result |
|---|---|
| Bounded span check | Junctions straight ahead may be up to 12 m past the sampled endpoint; the 1 m lateral guard remains. Tests cover 10 m (moves) and 13 m (unchanged). The real full compile adds exactly the 17 candidates identified by Claude's span comparison. None belongs to the 57-climb review. |
| Minimums | A proposed cut below 90 m length or 8 m rise leaves the original geometry and identity intact and marks it for review. Exactly 33 real candidates are flagged, including Frederick Street and Heritage Drive. |
| Black Rock start | Active, re-evidenced **start-only 30 m** D10 revision in the tracked decisions and successor provenance. Exact start WKT and the July revision ID bind the carry-forward evidence. Anchor, centre and orientation remain unchanged. Finish half-extent stays **25 m**; the historical 35 m end revision remains superseded, and the successor requires a new Record Board. |
| Position-bound approval | All 15 store approved coordinates, junction identity and reviewed setback. Final physical position must be within 0.5 m of an approved position. West School House's explicit note covers only its recorded 33.79 m snapped position. Drift and wrong-junction tests pass. |
| Publication payload | The builder and final publisher boundary recursively strip `compiler_profile_points` and `predecessor_profile_points` from the entire outgoing climb. Tests inspect actual fake-connection SQL parameters, including nested lists and canonical-profile sample extras, while preserving the caller's local review data and hash evidence. No database was contacted. |
| Lynnebrook Lane | A distance-only check rejects off-span controls before ambiguous progress projection. The stop 186.5 m away no longer flags this climb; real on-span ambiguity remains a review flag. |
| Approval/prerequisites | REPORT, CLIMBLAB and every prepared successor cite APPROVALS. Field checks and the revised scorecard remain; founder placement review is done. |
| Main merge | `650d16e38` merges origin/main without rebase. All 1,567 unique tracker IDs survive; main's exact te1n3 and edited pvrwy rows and this branch's 6ewxw row are preserved. Synthetic merged-tree semantics checked. |

The full run contains **2,051 candidates**, **304 moves** (15 founder-admitted, 289 explicitly unadmitted), and **33 unchanged candidates flagged for minimums**. No ambiguous-projection flag remains in this retained full input. Biddlewoods and Falls / Neill remain unchanged. The full integration checks the exact 17 added identities, exact 33 minimum rejections and all approved geometry fields against the reviewed round-1 output.

The 17 newly handled full-compile candidates are: Benezet Street, Berkley Street, Claire Road, East Cliveden Street, Fayette Street, Forrest Avenue, Gates Street, Germantown Avenue, Greene Street, Magnolia Street, Markle Street, North 10th Street, North 6th Street, North Highland Avenue, Pechin Street, West Fisher Avenue, Woodbrook Lane.

## Read-only replay (round 2 history)

A fresh run scanned **1,416 rides** and evaluated **5,229** ride/climb pairs using the unchanged traversal engine. Both phases use the retained September PostGIS corridors to isolate finish/span/profile changes; this is not evidence for newly published successor corridors or surveyed physical accuracy.

| Metric | Before | After |
|---|---:|---:|
| Accepted traversals | 425 | 470 |
| Frozen reference matches | 94/98 | 94/98 |
| Legacy overall pooled p95 | 11.714 m | 11.459 m |
| Legacy moved-set pooled p95 | 6.114 m | 5.550 m |
| Moved-climb last-100 m stopped efforts | 16/93 | 2/138 |

**0 baseline losses, 45 newly accepted; 100.00% baseline retention.** No stopped time is subtracted. [REPLAY.md](REPLAY.md) and [REPLAY.json](REPLAY.json) retain all per-climb diagnostics, fractional/whole-second changes and sanitized crossing evidence. The old overall 10 m comparison still fails; the new founder scorecard remains pending and is not silently treated as passed.

Black Rock retains all 42 baseline efforts. One accepted start (ride ordinal 160, 2683.902 s) crosses **29.265 m** off-centre, supporting the retained 30 m start extent. Against the earlier 35 m finish proposal, one effort remains excluded: ordinal 200 crossed 26.012 m from the finish centre; the 25 m finish produces `partial_traversal` with no finish crossing. The predecessor proposal comparison is re-evaluated with both exact geometries; it is separate from baseline retention. The brief states that poor-GPS effort never counted on the live board; this local replay does not independently establish live-board history.

The corpus passed SQLite integrity checking and its SHA-256 remained `64b15790bed2628b3e7e8371657b408ec5e96305db84bfe050507b14860b98ee`. SQLite was immutable/read-only throughout. A fresh private v3 checkpoint was written outside the repository; source activity IDs and raw rider coordinates are excluded from the committed pack.

## Verification (round 2 history)

- **Rust: 106 passed** — 96 canon library tests (41 finish-rule tests), one profile-exporter test, one parser semantic-vector test, seven compiler CLI tests and the full-compile integration test. The latter executes two complete local runs.
- **Backend: 340 passed, 2 skipped, 3,381 deselected** with `pytest backend/tests -k canon -q -rs`. The two skips require disposable PostgreSQL; none was provisioned.
- **Focused red → green:** four compiler regressions failed before the fix. A subsequent full run exposed an over-tight control extension (31 instead of 33 minimum flags); a new control-beyond-end regression failed before the correction restored the expected 17 additions and 33 flags. Both payload filter cases failed before correction; independent review exposed profile-sample extras, and both extended cases failed before the whole-payload fix. All pass now. The old Neill tangent fixture received a valid-length uphill approach while retaining its terminal geometry, so the new minimum guard does not turn it into an unchanged-climb test.
- **Determinism:** two full outputs match SHA-256 `7429c3e3c0ce32461489e1d12382a487330646fbcae564013e40a9a59bd1b684`; two 57-climb offline outputs match `9773a3e18935afe23ceca653ca0a736f81d46ed1157eeea624db18ea0f25b745`. Rehydrated source points match round 1 byte-for-byte. All 57 geometry/identity/profile/metric fields match round 1 exactly.
- **ClimbLab:** [CLIMBLAB.json](CLIMBLAB.json) contains 30 before/proposed entries, ready profiles/geometries and zero publish-ready candidates. [CLIMBLAB-PROBE.json](CLIMBLAB-PROBE.json) pins the loopback HTTP/data probe. This is local functional data evidence, not physical verification or new UI rendering work.
- **Independent review:** checked position binding, start-only D10 provenance, minimums and ambiguity handling; identified the profile-sample publication bypass, now fixed and covered.
- Existing traversal parameters, timing, profile-hash algorithm, H3 resolution and protocol program are unchanged. Exact diff, Rust formatting and tracker semantics are checked; normal tracked commit guards run without bypass.

## Follow-up only

- **City Avenue:** its other arm is a motorway ramp, outside the current qualifying road list. Leave it for a separately scoped follow-up.
- **Other re-review nits:** deferred as directed by the round-2 brief, which does not enumerate them. They are not treated as authority for additional changes in this round.
- Existing ClimbLab does not draw exact gate width/orientation, control markers or paired geometry overlays. Use the road geometry and control evidence in [DIFF.json](DIFF.json); the existing page alone cannot establish stop-line clearance or physical truth.

## Reproduce

Inputs and hashes are pinned in [INPUTS.json](INPUTS.json). Use Python 3.12.13, Shapely 2.0.4 and NumPy 2.0.2 in `/private/tmp/gate-rule-6ewxw/venv`; no dependency or provider configuration changed.

```sh
cargo test --manifest-path workout-parse/Cargo.toml --no-default-features --features osm canon
cargo test --manifest-path workout-parse/Cargo.toml --no-default-features --features osm --bin canon-compile
# Set CANON_TEST_PBF, CANON_TEST_PROFILES, CANON_TEST_BASELINE,
# CANON_TEST_REVIEWED, CANON_TEST_SPAN, CANON_TEST_PREVIOUS and CANON_TEST_OUTPUT_DIR:
cargo test --release --manifest-path workout-parse/Cargo.toml --no-default-features --features osm --test canon_finish_full_compile -- --ignored --nocapture
```

The full baseline is Claude's `review-gate-rule/out/full-compile-base.json`; REVIEWED and SPAN are `review-gate-rule-r2/out/full-1.json` and `full-span.json`. PREVIOUS is the round-2 `fix2/full/full-1.json`. The local runner `/private/tmp/gate-rule-6ewxw/fix3/full.sh` records exact paths. For [review.py](review.py), use the inputs in INPUTS: hydrate the original 57 plus full-precision points with `--hydrate-only`, run `canon-compile --finish-gates-input` twice, then invoke the review runner for preparation and replay. Round 3 also requires `--previous-round-report`, `--stop-map-results`, and `--metric-module` from INPUTS. Extract the latter without editing the other lane: `git show 8993e19996ce5c8c2bb050845e03bf5b13d9fa22:tools/corpus/canon_traversal_replay.py > /private/tmp/gate-rule-6ewxw/fix3/metrics/canon_traversal_replay.py`; its exact hash is enforced. The local `fix3/review.sh` records the full invocation. A checkpoint must be outside the worktree; it is mode 0600 and bound to all input hashes. The compact committed compiler summaries are not compiler inputs.

## Fix round 1 history

Commit `50dfe886b` fixed differently named junctions, iterative 15 m clearance, tiny terminal segments, unrounded grades and review-only publication/SQL guards. Its 319-move/one-unresolved full-run result and outstanding founder-review/old-scorecard wording are superseded above. The original `b93e09ea4` proposal had 471 traversals; the 25 m Black Rock finish reduced that to 470 without losing any registry-baseline effort. The 15 round-1 successor geometries remained exactly unchanged in round 2; round 3 changes only Wises Mill and Centennial.
