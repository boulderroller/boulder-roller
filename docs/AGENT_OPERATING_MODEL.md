# BoulderRoller Agent Operating Model

AGENTS.md is the normative contract. This file is the single procedural
runbook for branch, worktree, Beads, verification, and landing operations.

## 1. Compact Preflight

Run this only before repository writes:

    git status --short --branch
    git worktree list --porcelain |
      awk '/^worktree /{n++} /^detached$/{d++} END{printf "worktrees=%d detached=%d\n",n,d}'
    bd ready --assignee codex --json --no-db --no-daemon |
      jq '[.[] | {id,title,status,assignee}]'

Report one line naming the branch, dirty state, Bead, and whether the checkout
is the root or a sibling worktree. Expand only if a conflict, stale base,
occupied branch, or unrelated dirty file affects the task. Do not paste the
full worktree registry or complete tracker rows into context by default.

Read-only answers and diagnostics do not need this write preflight.

## 2. Select or Create the Lane

Pull only assigned NOW/NEXT work. A direct user-requested repository change may
create one bounded Bead when capacity exists. Use:

    bd show <id> --json --no-db --no-daemon
    bd update <id> --status in_progress --json --no-db --no-daemon

Project large JSON through jq to the fields needed for the decision. Load full
notes, comments, or dependencies only when they are relevant evidence.

Use one short-lived branch per Bead:

    git fetch origin --prune
    git switch -c codex/<bead-id>-<short-slug> origin/main

Do not pull, reset, clean, or rebase a dirty human root. When isolation is
needed, create a visible sibling worktree:

    mkdir -p /Users/gabetemp/curahee/BoulderRoller-worktrees
    git fetch origin --prune
    git worktree add -b codex/<bead-id>-<short-slug> \
      /Users/gabetemp/curahee/BoulderRoller-worktrees/<short-slug> origin/main

Use codex/<short-purpose> only for direct user setup before the Bead exists;
rename it once the Bead is created.

## 3. Beads Direct-JSONL Rules

Every command uses the worktree's tracked JSONL authority:

    bd show <id> --json --no-db --no-daemon
    bd update <id> --status in_progress --json --no-db --no-daemon
    bd close <id> --reason "Completed observable outcome" --json --no-db --no-daemon

Do not use sync, import, export, init, a database, a daemon, automatic staging,
or a custom merge driver. Review .beads/issues.jsonl exactly and stage it with
the related change.

When origin/main moved, tracker-bearing branches overlap, or an existing row
is reconciled, create and inspect the synthetic merged tree before landing:

    git fetch origin --prune
    git merge-tree --write-tree origin/main HEAD

Inspect the merged JSONL for unique IDs and preservation of the exact statuses,
comments, close reasons, timestamps, tombstones, and protected gates affected
by the merge. On an unchanged base with one isolated new row, exact diff review
is sufficient.

## 4. Risk-Scaled Verification

- Docs/copy: exact diff review and git diff --check.
- Localized code: focused production-path red, smallest fix, targeted green,
  then the relevant existing suite.
- UI: functional interaction, truth and accessibility checks, plus exact
  desktop/mobile renders.
- Protocol, economics, custody, privacy, migrations, deployment, or permanent
  state: retain the governing corpus, full relevant suite, and independent
  outcome checks.
- Physical/provider/chain claims: verify the external state directly; local or
  deployed evidence is not a substitute.

Do not add reviewers, builds, screenshots, full suites, or evidence artifacts
that do not reduce uncertainty about the admitted outcome.

For non-semantic edits to guarded parser files, use the `Parser-Semantics:
unchanged` trailer with a one-line reason and run
`tools/check_parser_semantics_version.sh <base-ref>`. The
[parser semantic gate](design/RIDE_CANONICALIZATION_SPEC.md#parser-semantic-version-gate)
defines the trailer format and required Rust/mobile vector verification.

## 5. Landing

Before committing:

    git diff --check
    git status --short
    bd show <id> --json --no-db --no-daemon

Then:

1. Close or update the Bead with the observable outcome.
2. Review the exact tracker diff.
3. Explicitly stage only the owned files and .beads/issues.jsonl.
4. Commit with the Bead ID.
5. Fetch and confirm the branch can land without losing tracker semantics.
6. Push and verify the remote received the intended commit.
7. A push to main deploys only the portal (Vercel Git link). The org site,
   BoulderScan and the docs are off Git: run `scripts/deploy-sites.sh` from the
   root after landing, and it deploys whichever of the three changed. The team
   is on Vercel's Hobby plan (100 deployments a day), so never push a commit to
   a branch and to main at once, and use CLI previews only when a function
   cannot be exercised locally.

Do not use a casual tracker-bearing rebase as reconciliation. If remote main
moved, use the synthetic merge check above and integrate explicitly.

## 6. Cleanup and Handoff

After a lane is landed and its contents are preserved, remove its temporary
worktree promptly:

    git worktree remove /Users/gabetemp/curahee/BoulderRoller-worktrees/<short-slug>
    git worktree prune --dry-run --verbose

Resolve exact targets first; never remove dirty, unmerged, active, or
evidence-bearing worktrees merely because they look old.

Hand off with: changed outcome, live/deployed state, remaining untrue or gated
state, and one next decision if needed. Keep hashes and command transcripts
subordinate to that explanation.
