# Reader's-Path Pass

**Status:** COMPLETE except item 6 (founder one-pager, reserved for Tim)
**Date:** 2026-08-07 (applied same day, bead `boulderroller-v2-twp51`)
**Origin:** Founder conversation (deli session). Prepared by a read/write
Filesystem session without git access; apply on a branch per the
one-branch-per-bead convention in AGENTS.md.
**Suggested location:** `docs/design/READERS_PATH_PASS.md`

## Why

Zero-start makes the repository the product's credibility layer. With no
market and no TGE horizon, DUNG receipts carry weight only through social
belief in the system's integrity — and the repo is where that belief gets
audited. Readers forgive mess; they punish *dishonest* mess: documents that
claim to be current but aren't, authority claims that aren't real, dead lanes
that look alive. The front door must tell the truth about the present. The
honest-witness principle applies reflexively to the witness itself.

## Done this pass (files prepared; apply and review diff before commit)

1. **README.md — full rewrite.** The prior README presented a TGE horizon
   ("Points convert to DUNG tokens at TGE"), described the removed points
   period as current, and listed live devnet systems (staking, distributions)
   as "planned post-launch" — a direct contradiction of ratified zero-start
   language. Rewritten to describe the August 2026 present: production +
   devnet status, the four ratified strategy decisions, honest lane markers
   in the repo layout, source-of-truth hierarchy, ODbL note.
2. **PROJECT_BRIEF.md — tombstoned.** Codex-era brief (Merkle-batch
   architecture, points era, client-ios as active lane) preserved verbatim
   under a HISTORICAL header pointing at current truth. Visible eras, not
   erasure.

## Remaining (for the branch-per-bead lane)

> **2026-08-07 outcome:** items 3–5 executed under bead `twp51`. iOS lanes
> moved to `archive/ios/` and `archive/client-ios/` with era notes.
> `poopy.html` untracked and kept locally as
> `private/series-a-specification-2025.html` (Tim directed "just clean it up";
> reversible — git history retains it). Sweep tombstoned
> `docs/PRE_TGE_WORK.md` and `docs/TWITTER_LAUNCH_CONTENT.md`, fixed the stale
> spec pointer in `archive/README.md`; gitbook was clean; remaining TGE
> mentions in tracked docs are zero-start declarations or historical/internal
> records. Item 6 remains Tim's.

3. **Archive the superseded iOS lanes.** `git mv ios/ archive/` and
   `git mv client-ios/ archive/`, each with a two-line era note (check
   `git log --follow` for actual date ranges before writing the notes; note
   `client-ios` Features still use segments/mint vocabulary — that dates it).
   Update the README layout markers from "pending archive" once moved.
   *Classification: Tim confirmed direction in conversation; execution
   agent-autonomous.*
4. **`poopy.html` disposition.** It is a styled "Series A Specification"
   document sitting tracked at the public repo root. A fundraising-framed
   spec in a zero-start public tree is an external-narrative artifact and
   deserves a deliberate call: likely `private/` (already gitignored) or
   `archive/` under a real filename, plus `git rm --cached` if it leaves
   tracking. *Classification: Tim-ratifies (external narrative).*
5. **Stale-pointer and horizon-language sweep.** Grep tracked, public-facing
   docs for `TGE`, `token launch`, `post-launch`, `points period`, and
   `Latest protocol spec: history/` pointers; fix or tombstone per the
   TRUTHS hierarchy. Anything touching `docs/gitbook/` runs through the
   rider-first language rules before landing. *Classification:
   agent-autonomous, mechanical.*
6. **Founder one-pager — reserved for Tim. Agents must not draft this.**
   One page, founder-authored, founder-voiced: what this is and why the
   rules are the rules. It is the ratification act that makes "Ratified by
   Tim" load-bearing, and the document a reader checks to answer the 2026
   audit question — *is there a mind behind this?* Suggested slot:
   `docs/FOUNDER.md`, linked from README and the top of PROTOCOL_TRUTHS.
   *Classification: Tim only.*

## Mechanics note

Items 1–2 were prepared without git access (Filesystem MCP only, which then
went unresponsive; local state verified unchanged as of last read). Whoever
applies them: drop the files in, `git diff` review, commit on a short-lived
branch as one bead. Do not intermingle with in-flight work.
