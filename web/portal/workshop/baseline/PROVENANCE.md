# Retained portal V1 baseline provenance

All runnable baseline rooms render the unmodified portal source at
`a63ffc77f9638b78d3a404be2575aaa7ddd9c145`, frozen on 13 September 2026 in
`source.tar.gz`, materialized into ignored `src/` by the preview/build startup,
with its server presentation helpers and public assets. The source
manifest records SHA-256 hashes. The surrounding harness, local storage,
transport, authentication runtime and signing boundaries are workshop code.
Production files are unchanged.

The primary supplied data is the existing `e2e/portal-v2-routes.spec.ts`
response fixture (its date anchor is 5 May 2026). The excerpt in
`fixtures/portal.ts` removes the unused test imports, adds exports, types an
optional object spread, and removes generic success for unspecified writes.
No rider results, geography or economic readiness were authored for this work.
Additional supplied recipes come from `e2e/public-previews.spec.ts`,
`e2e/portfolio-snapshot.spec.ts`, `e2e/threshold-read-states.spec.ts`,
`e2e/settings.spec.ts`, `e2e/account-deletion.spec.ts`, and
`e2e/upload-entry.spec.ts` with its retained upload-sheet board data. The private
profile uses the minimal non-owner projection from `backend/app/routes/users.py`
and `backend/tests/routes/test_social_contracts.py`; private identity, totals,
relationships, capabilities and modules are redacted consistently.

The Profile family retains its actual wrapper and tab ownership. Another rider
is public-only; signed-out riders use the distinct PublicPreview implementation.
Rides include the supplied Waiting Ride. Empty Rides uses the empty response
recipe. Portfolio empty uses the complete empty collection-population recipe;
partial coverage never creates collection readiness. Training retains missing
load snapshot authority and the source's paired establishing state.

Settings retains five rails and its source editing, validation and confirmation
UI. Submitted text/preferences remain inside local fixture responses. Account,
social, email/provider, export-service, signing and economic actions never run
against a live service. Funding and withdrawal preparation use existing fixture
responses; signing remains unavailable. Collection is the actual inline action,
not an invented sheet. Cancellation and failure paths remain functional.
Upload transfers file bytes only into the in-memory fixture boundary and uses
the existing completed/processing/duplicate/error response recipes. A completed
fixture is not a claim that a real uploaded file was processed.

The notification fixture contains one historical event. The source's 20-row
pagination is retained, but no larger ledger is supplied; a complete imported
GET response can exercise it without repeating events. Search retains all four
categories, recent searches, the empty suggestions response and its supplied
rider result. No Climb/Ride result or populated suggestion set is supplied;
those categories correctly show no results for this fixture. Missing live data
and unavailable provider workflows remain explicit capture/interaction gaps.

Route aliases are navigation checks, not duplicate rooms: `/training` and
`/my-activities` → Rides; `/data` → Training; `/portfolio` → Portfolio;
`/map` → `/climbs` preserving query/hash; `/vaults` → Climb discovery with Vaults;
Vault detail resolves its Climb. Ride, Climb and Rider aliases remain in the
frozen router. The legacy `/activities/:id/analyze` implementation has its own
retained room. `/admin` is operator-only; `/admin/significance` redirects there.
Admin source is in the frozen source closure but has no new workshop room.

Current live inspection on 13 September 2026 used a signed-out browser at
`https://app.boulderroller.xyz/profile`. It reached the sign-in door, so no
current live private-profile, Training, Portfolio or Settings capture is claimed.
The signed-out public Climb at `/climbs/aec5dcc5-ea67-46ec-8b8a-4f0d77fa1862`
was also inspected and captured live at both sizes on 13 September 2026. Its
public page showed no leaderboard times. The deployment revision was not
exposed, so it remains unknown. `evidence/additional-captures.json` records
these four current live captures separately from all local fixtures.

`references/provenance.json` identifies 14 historical portal fixture captures
and 26 relevant Strava screenshots from 9 September 2026. The dedicated
**Strava reference** control opens the applicable screenshots beside the
interactive preview, with section controls, source-page and full-image links.
The original screenshots are byte-identical to the historical study archive at
`fa5c5ca33bb9ac69fdc7b85986e36a0dc23a287d`. That is the archive revision,
not a known revision of the application captured; capture application revisions
remain unknown. Strava desktop sources used a 1440 px viewport and phone
sources used 430 px, captured at 2×. The Boulder Roller phone preview remains
390 px. Screenshot dimensions and SHA-256 hashes are retained in the manifest.

Strava references show Tim's signed-in free-tier account, with the original
paywall, modal and missing-data states. They cover Profile, My Activities,
Training, Settings, segment search, Ride, Analysis, Climb and navigation.
Signed-in Strava object screenshots do not prove signed-out privacy behavior;
Climb screenshots do not provide a CAL, DUNG or Vault-action analogue. No
relevant Strava screenshot was supplied for Portfolio, Notifications, Upload,
Guide, Access or account deletion, so those rooms explicitly record the gap.
Historical Boulder Roller fixture links remain separate under Provenance.

Current generated captures are **local implementation baselines rendered with
supplied fixtures**, with URL, date, selected viewer, viewport and source
revision recorded in `evidence/captures.json`. Reference-panel controls do not
change the retained source. Squint blurs the preview and reference together.
Imported data is labeled, can be copied or downloaded, and can be restored to
the original supplied scenario. Held data can be released in place; stale data
availability can be restored without discarding local read state. Supported
viewer and state combinations remain the existing named scenarios.

`evidence/reference-controls/checks.json` records the subsequent reference and
control correction at 1440×1000 and 390×844. Its captures are additive; the
original scenario and interaction evidence remains unchanged. The focused red
checks observed the absent Squint button, unavailable release function and
missing reference mapping before their fixes. Browser verification additionally
caught stale export text after restoring supplied data; a fresh export now
clears the previous text before receiving the selected frame's response.

The original full portal source has pre-existing TypeScript diagnostics outside
its production typecheck gate. `check-source.mjs` verifies byte-identical source,
reproduces those diagnostics on the original implementation, and rejects any
new adapter diagnostic. The existing workshop typecheck remains unchanged.

Verification: all 98 supplied scenarios have exact 1440×1000 and 390×844 local
captures (196 images). Twelve additional local captures retain funding and
withdrawal sheets, upload audience/validation, search results and Power curve.
`evidence/interactions.json` records fourteen desktop/phone journeys plus two
browser-error checks; `additional-checks.json` includes a phone touch selection.
All passed. The retained source check reports 441 byte-identical source files,
zero new adapter type errors and 15 independently reproduced original source
diagnostics. Workshop tests and typecheck pass; the build keeps its existing
large-chunk and third-party annotation warnings.

Focused red-to-green checks caught query-key export collisions, imported read
state, owner alias/private-data access and viewer changes on cross-room routes.
Browser checks caught room returns losing their source router state. The
adapter now hands cross-room navigation to the parent before changing the
source room; internal route changes remain in the source router and scenario
export. Imported responses not yet requested remain in subsequent exports.
Each worktree now owns its Vite cache; linked dependencies do not share it.

Reproduce locally with `npx tsx workshop/baseline/verify-browser.mts` and
`node workshop/baseline/check-source.mjs`. Captures are immutable evidence of
this checkpoint: a subsequent candidate should write its own output directory,
not overwrite these files. `capture.mts` and `capture-more.mts` record how these
images were made; do not rerun them over retained evidence after changing V1.

The H3 commit hook initially flagged a pre-existing heatmap-query default when
the original source was staged as hundreds of new text files. The final
source is therefore stored as one immutable archive, verified against every
recorded source hash and automatically materialized for rendering. It keeps
all original bytes, including pre-existing whitespace. Materialization refuses
altered archives or source files. No H3 behavior, hook or guard was changed or
disabled; the final tracked diff passes the normal whitespace and commit hooks.
