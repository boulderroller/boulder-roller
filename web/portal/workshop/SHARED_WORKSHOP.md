# Shared portal review workshop

## Consolidated checkpoint · 15 September 2026

Branch `claude/workshop-finals` carries the shared checkpoint forward with every
generation Tim settled since it was cut: Climb V7–V13 (V13 locked 14 Sep),
Map V4–V7 (V7 settled 14 Sep) and Rider Profile V2–V6 (V6 locked 14 Sep), on top
of Ride V1–V13 (V12 accepted 11 Sep), Feed V1–V9 (V9 accepted 13 Sep) and the
eighteen retained V1 rooms. Settings stays on its live lane until it is locked;
the unreviewed Rides, Training and Portfolio V2 drafts are not carried.

**Finals.** Tick **Finals** in the page bar (or add `&finals=1` to any workshop
URL). The page dropdown then lists only the rooms that have a final — Ride,
Feed, Climb, Map and Rider Profile — each opening on its locked, settled or
accepted candidate, with the candidate ladders hidden and the page bar naming
the decision and its date. Untick to return to every room and the full ladder. No candidate file changes in either mode.

Evidence captures proving closed lanes stay on their lane branches; only code,
fixtures, data, the Strava reference captures and the frozen-source archive
land with the checkpoint.

## Original shared checkpoint · 13 September 2026

Integration owner: Bead `boulderroller-v2-14q9w`, branch
`codex/14q9w-portal-baselines`, checkout
`/Users/gabetemp/curahee/BoulderRoller-worktrees/portal-baselines`.
Preview: http://localhost:4324/ (`npm run workshop -- --port 4324`).
Candidate authors keep isolated checkouts. This checkout has one writer.

The initial shared checkpoint is `44e517b2b9e6f174c4106e6513b90dff8491d261`.
The current shared preview retains Ride V1–V13, Feed V1–V9, Climb V1–V6 and Map V1–V3,
plus eighteen retained portal V1 rooms with 98 supported scenarios.
Sources: Map `2673c094d54deac52d672bc415e9cf4817f04d17`, Climb V5
`00da7dc1240452847d80739dec13a76a64ca6ed0`, main
`a63ffc77f9638b78d3a404be2575aaa7ddd9c145`.
Climb V6 became clean, completed and pushed at
`aaa7f71db2e6d673bf9dca30e8367f6966f911ff`; that exact checkpoint is now integrated.
The retained source/fixture commit is `e6a000183`; its separate room registration
commit is `698cc9787`. V1 is shipped as a hash-verified frozen source archive;
preview/build startup materializes it automatically. No candidate edits V1.

To carry the checkpoint forward, fetch this branch and merge its completed
checkpoint into the author's isolated worktree. For a subsequent candidate,
provide its completed, tested, pushed commit and owning Bead. The integration
owner merges that exact commit, reconciles individual registry and dispatcher
changes, checks Climb destination dispatch, and semantically three-way merges
tracker rows by ID. Never replace a whole conflicting file or copy dirty files.
Run the synthetic merged-tree tracker check, workshop tests/typecheck/build,
and desktop/phone journeys before advancing the shared branch and preview.
There is no automatic synchronization. Map V4 follows this checkpoint; Rider
Profile remains the next recommended design workshop after Map.

`shared-evidence/` records one local supplied-data session switching between
Map V3 and Climb V5 at 1440×1000 and 390×844 on 13 September 2026, viewer=rider.
These are local candidate renders, not production or real-rider proof.
Existing V1 and Strava captures retain their original provenance. No main
merge or production deployment is part of this workshop.

The completed baseline rooms cover Profile Overview, Rides, Training, Portfolio,
Settings, Notifications, Upload, Guide, Search, Access/onboarding, three public
preview types, attached Vault flows, account-deletion status, shell/overlays,
original Ride flows and legacy Analyze. All private and economic fixtures stay
local. See `baseline/PROVENANCE.md` for source/access/capture limits.

The `*-final-session-*` captures demonstrate Map V3 and Climb V6 in one browser
session at both sizes. Future candidates enter through an explicit completed
commit merged by the integration owner into this branch; authors should carry
this final branch checkpoint into their own isolated worktrees first. Preserve
the room registry and candidate-specific destination dispatch.

The retained V1 harness now matches the shared review controls: Squint,
adjacent historical Strava screenshots with section controls, separate
Provenance, marked imported data, Copy JSON, Restore supplied scenario,
and in-place release/recovery of supplied data. Reference capture widths are
labeled accurately (Strava phone 430 px; Boulder Roller phone 390 px).
`baseline/evidence/reference-controls/` retains the correction's local proof.
