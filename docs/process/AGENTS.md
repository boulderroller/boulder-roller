# Agent Instructions

BoulderRoller uses bd (Beads) for repository tracking. This file is the
normative agent contract. Procedural commands live in
docs/AGENT_OPERATING_MODEL.md; product truth lives in the named TRUTHS and
design documents. Do not duplicate those sources into agent entrypoints.

## Delivery Contract

- **Deliver the admitted outcome.** Feature work ends in behavior a rider or
  consuming system can exercise. Plans, audits, docs, tests, and refusal paths
  may support it; they do not independently complete it.
- **Work only from admitted scope.** Pull assigned NOW/NEXT work or a direct
  user request. A tracker census is not permission to start backlog work.
- **Do not manufacture work.** Record discoveries on the existing owner.
  Create a Bead only for a direct user-requested repository change, a
  P0/data-loss risk, or a blocker to the admitted outcome.
- **Keep process subordinate to delivery.** Do not create a dashboard,
  certificate, ledger, evidence site, or process document as progress unless
  the admitted outcome genuinely requires it.
- **Honesty is absolute.** Never weaken a gate, bless broken output, hard-code
  demo success, or present a fixture, mock, retained capture, or hand-inserted
  row as live evidence.
- **Name the evidence class.** Keep local/offline proof, deployed state, and
  physical rider/world-state evidence distinct.
- **Act autonomously inside ratified contracts.** Tim is a gate only for new
  product direction; authority, privacy, permanence, or provider-spend policy;
  materially destructive actions not already authorized; or required physical
  evidence.
- **Hand off in human terms.** Lead with what changed, what is actually live,
  what remains untrue or gated, and the one decision needed, if any.

If recent activity is mostly governance while the runnable deliverable is not
moving, stop extending the machinery and return to the admitted outcome.

## Scope and Decision Control

- Maximum capacity is two implementation lanes plus one physical/world-state
  gate. Live assignment belongs in Beads; do not hard-code current issue IDs or
  scheduling state in instruction files.
- NOW means assigned and in progress. NEXT means one assigned open successor
  per lane. Unassigned open work is library material, not an active queue.
- Use agent-autonomous inside ratified contracts. Use Tim-ratifies only for the
  decision classes above, and batch those decisions rather than interrupting
  Tim for agent correctness or subjective polish.
- Keep implementation and its tests in one feature Bead. Do not split a feature
  into planning, implementation, and test closures.
- Strategic authority is recorded in docs/FRESHEST_SPEC.md, the TRUTHS docs,
  or the owning Bead. Conversation-only decisions do not exist.
- Apply the standing product filter: *does it make the hill matter more?*

## Repository and Tracker Safety

- The human-visible root is /Users/gabetemp/curahee/BoulderRoller-v2 and
  should normally remain on main.
- Start new writes from current origin/main. If the root is dirty, stale, or
  occupied, preserve it and use a clean visible sibling worktree. Never reset,
  clean, rebase, or discard unrelated user state.
- Use one short-lived branch and one Bead per implementation lane. Avoid
  catch-all branches and hidden .git/beads-worktrees workspaces.
- .beads/issues.jsonl is the exact tracker authority in each worktree. Use
  direct JSONL mode only: --json --no-db --no-daemon.
- Never run bd sync, bd import, bd export, bd init, database/daemon workflows,
  automatic staging, or a custom JSONL merge driver.
- Review the exact tracker diff and commit it with the related change. Preserve
  row IDs, comments, close reasons, timestamps, tombstones, and explicit gates.
- Use the synthetic merged-tree semantic check when origin/main moved, when
  tracker branches overlap, or when an existing row is reconciled. A Git-clean
  merge is not sufficient evidence that tracker meaning survived.
- Destructive repository or data actions require exact targets and appropriate
  authority. Never use broad unresolved paths, globs, or environment variables.

The compact command path and landing procedure are in
docs/AGENT_OPERATING_MODEL.md.

## Evidence and Completion

1. **Done claims cite outcomes, not activity.** Tests passing is activity.
   State the changed observable result and attach the relevant proof.
2. **A new test must fail before its fix.** Record one focused red, make the
   smallest correction, then show the relevant green. Do not manufacture a red
   by weakening production behavior.
3. **Scale evidence to risk.** A docs correction needs an exact diff check.
   Localized code needs focused red-to-green plus the relevant suite. Protocol,
   custody, privacy, migrations, economics, deployment, or physical-world
   claims retain their full authority and outcome gates.
4. **Functional UI closes on working evidence.** Truth, accessibility,
   interaction, and exact desktop/mobile rendering must hold. Batch subjective
   taste into a later holistic review; do not defer broken or misleading UI as
   polish.
5. **External state remains external.** CI, HTTP 200, a local fixture, or a
   deployed commit cannot substitute for a required rider, chain, provider, or
   world-state outcome.

## Usage and Review Discipline

- **Routine docs or copy:** one agent, targeted source sections, exact diff
  review, and git diff --check. Do not spawn a review swarm.
- **Localized implementation:** one focused red-to-green, the smallest relevant
  suite, and one outcome probe. Add a specialist only for a genuinely separate
  authority or risk.
- **High-risk work:** use independent review and broader gates when protocol,
  money, custody, privacy, migrations, permanent state, or physical claims
  warrant them.
- Use subagents only for independent work that materially benefits from
  parallelism. Do not delegate sequential same-file edits or routine status
  checks.
- Keep tool output compact. Summarize large worktree, tracker, log, test, and
  diff outputs; expose full material only when it is the evidence under review.
- Do not create planning artifacts by default. Use Beads for durable work and
  concise commentary for progress.
- For read-only questions, explanations, and diagnoses, do not create a branch,
  Bead, worktree, or implementation preflight unless a write follows.

## Naming

Every name you choose, for files, scripts, directories, functions, variables,
classes, commits, branches, anything, must use precise professional vocabulary.
Choose the word a 1972 IBM engineer would write in a specification. No slang,
no casual shorthand, no cute or clever names, no words borrowed from chat
culture. This applies universally, not only to the one example that follows: a
script that deploys dashboards is `deploy_dashboards.sh`, not
`push_dashboards.sh`. That is one illustration of the principle, not the extent
of it.

This extends to everything that persists or is referred to later: artifact
titles, headings, section and button labels, memory entries, tracker titles,
session and chapter titles, task-list items. A page that compares two deposit
designs is "Deposit Design Comparison", not "Deposit Showdown". In conversation
the same vocabulary governs the words for actions and objects: deploy, remove,
verify, defect; not ship, nuke, sanity-check, busted. Do not coin nicknames for
concepts; name them. Sentences remain plain and natural. The rule concerns
precise words, not stiff prose.

Words riders read are not names in this sense; they follow Rider-Facing
Language Routing below.

## Rider-Facing Language Routing

Start from the literal rider experience:

    action -> rider object -> visible state -> optional technical detail

Use rides, climbs, results, time, power/place when known, bests, Top 10,
leaderboards, history, CAL, DUNG, Vault actions, and explicit proof detail. Do
not headline internal primitives, generic outcomes/rewards/points, yield, or
stake when a concrete rider object exists.

Read only the authority needed for the proposed change:

- **Routine wording or CTA:** the relevant section of
  docs/design/LANGUAGE_SPEC.md plus the surface-specific TRUTHS document.
- **Protocol meaning, canon, roles, permanence, or attestation:** also read the
  relevant section of docs/PROTOCOL_TRUTHS.md.
- **CAL/DUNG state composition, Balance, receipts, or settlement:** also read
  the relevant section of docs/design/PROOF_ECONOMY_PRIMITIVES.md.
- **Brand hierarchy, identity, or a branded reveal:** also read the relevant
  section of docs/design/BR_IDENTITY_SYSTEM.md.
- **Changing the language contract itself:** read all directly affected
  authorities and reconcile downstream sources.

Do not load the full protocol, economy, identity, and surface stack for a
low-risk wording change. Do not invent slogans, poetic lines, or product nouns.
CTAs must name a real action or destination.

## Working and Landing

Before a repository write, follow the compact preflight in
docs/AGENT_OPERATING_MODEL.md. Report branch, dirty state, Bead, and worktree
location in one concise update; expand only when an anomaly affects the work.

Run the smallest gate that proves the outcome, close or update the Bead with
outcome evidence, explicitly stage the tracker row with the related files,
commit, push, and verify the remote. Clean landed temporary worktrees promptly
when their contents are preserved and removal is safe.

## Parallel Agents

Parallel writers must own distinct Beads, branches, worktrees, and file scopes.
Audits remain read-only. The lead owns landing order and final truth checks.
The same delivery, evidence, scope, and usage rules apply to every teammate.
