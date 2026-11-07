# Review the 16 finishes in ClimbLab

Use the existing `/dev/climb-lab/review` page with [CLIMBLAB.json](CLIMBLAB.json).
The pack contains 32 entries, labelled `BEFORE` and `PROPOSED` for each
admitted climb. It is explicitly `review_only`: zero entries can publish.
[SUCCESSORS.json](SUCCESSORS.json) contains the separate prepared version-2
records with fresh Record Boards. Founder placement approval is complete in
[APPROVALS.json](APPROVALS.json); publication ratification is a separate action.

What remains is field verification at Black Rock, Youngs Ford and Port Royal,
and Centennial paint, plus passing the founder's revised 20 October scorecard
bars. Corrected boundary and timing metrics now use the pinned gate-consistency
definitions in [REPLAY.md](REPLAY.md), including round-2/round-3 comparisons
for Wises Mill and Centennial. The historical 10 m pooled diagnostic in [REPLAY.md](REPLAY.md) is not the current publication bar.
The [round-3 brief](../../codex-briefs-2026-10-20/gate-rule-fix-3.md) records the two additional approved shifts.

From this worktree, launch the existing app locally:

```sh
PYTHONPATH=backend:. PYTHONDONTWRITEBYTECODE=1 \
ENVIRONMENT=test ENABLE_DEV_ROUTES=true \
ACCESS_TOKEN_SECRET=gate-rule-local-test-access-secret \
REFRESH_TOKEN_SECRET=gate-rule-local-test-refresh-secret \
SENTRY_DSN= SUPABASE_URL= SUPABASE_SERVICE_ROLE_KEY= \
CLIMB_LAB_CANON_COMPILE_REPORT_PATH="$PWD/history/codex-reports-2026-10-20/gate-rule/CLIMBLAB.json" \
CLIMB_LAB_REVIEW_STATE_PATH=/private/tmp/lafayette-crest-6ewxw/tim-review.json \
/private/tmp/gate-rule-6ewxw/venv/bin/python -B -m uvicorn app.main:app \
  --host 127.0.0.1 --port 8769 --lifespan off
```

Open <http://127.0.0.1:8769/dev/climb-lab/review>. `--lifespan off` keeps
the production startup database checks and background workers out of this
local review. The configured compiler report supplies the candidates, so
no Overpass or elevation scan is needed. The recorded founder approvals are authoritative for these placements;
any additional local notes stay in the named temporary state file. The local
ClimbLab decision counters do not import the separate founder approval record.

1. The 15 traffic-control placements and Lafayette crest are approved in [APPROVALS.json](APPROVALS.json). For follow-up,
   select each `BEFORE` entry, then its `PROPOSED` counterpart. Compare the
   centreline finish and elevation profile with the table in [DIFF.md](DIFF.md).
2. Inspect the eight named boundaries: Calumet / West Coulter, Conshohocken
   State, Falls / Conshohocken, Midvale, Port Royal, West School House, Wises
   Mill and Youngs Ford.
3. Inspect Black Rock's **32.14 m** placement and reset **25 m** end
   half-width; check any lost crossings in [REPLAY.json](REPLAY.json).
   Its unchanged 30 m start half-width is an active re-evidenced D10 revision. Claude's D7.5 call gives
   every control at least 15 m clearance even beyond the default setback band.
4. Inspect West School House's **33.79 m** placement: the 32.89 m clearance
   cut snaps a further 0.90 m upstream to avoid a tiny final segment.
   This precise snap is covered by the founder-informed note in [APPROVALS.json](APPROVALS.json).
   Field checks remain for Black Rock, Youngs Ford, Port Royal and Centennial paint.
5. Inspect the round-3 amendments: Wises Mill is **30.00 m** before its junction;
   Centennial is **29.06448 m**, within 0.5 m of the approved nominal 29.0 m.
   The extra 6.45 cm gives the published aggregate stop the full 15 m clearance.
   Both retain the founder’s “yes shift both back” in APPROVALS and the tracked decisions.
6. Compare the Lafayette BEFORE/PROPOSED pair: the start is unchanged, and the finish is 715.53 m farther along the road at the lump crest. Its two Stony Lane turners do not complete this longer climb; see [the aggregate replay](../lafayette-crest/REPLAY.json).
7. Record review notes. Falls / Neill stays unchanged because its same-name
   road split is not a qualifying junction. There is no extra proposal to admit.

The existing page renders centreline endpoints and profiles. It does **not**
render the exact gate-line width/orientation, traffic-control markers, or
an old/new geometry overlay. Those views would require existing ClimbLab
map-detail support for gate lines and control markers plus a paired overlay;
they were not built as a new tool in this brief. For exact placement review,
use `new_gate_endpoints_lon_lat`, `new_gate_center`, and
`rule.controls` in [DIFF.json](DIFF.json). A page screenshot alone cannot
establish the 15 m stop-line clearance or physical junction truth.

All 32 existing map/profile endpoints and the review page were checked
locally; [CLIMBLAB-PROBE.json](CLIMBLAB-PROBE.json) records that evidence.
Founder placement review is complete in [APPROVALS.json](APPROVALS.json). Field
verification, the revised scorecard, fresh publication checks and explicit publication go remain outstanding.

The compact pack retains profiles, polylines, gate WKTs, identity, metrics
and actual corridor-cell counts. Duplicate full corridor/centreline WKT and
raw compiler provenance are omitted. The three `COMPILER-*`/`ADMITTED-AFTER`
files are review summaries, not compiler inputs; `INPUTS.json` pins the full
local sources. Every saved envelope and prepared payload is non-applied and
must remain non-publishable during review.
