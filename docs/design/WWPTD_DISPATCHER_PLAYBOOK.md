# WWPTD Dispatcher Playbook

**Status:** HISTORICAL — April 2026 orchestration during the protocol-agent freeze
**Date:** 2026-04-17
**Audience:** Mobile/backend orchestrator agent, any spawned worktree agent
**Parent docs:**
- [PROTOCOL_TRUTHS](../PROTOCOL_TRUTHS.md) / [MOBILE_TRUTHS](../MOBILE_TRUTHS.md) / [BACKEND_TRUTHS](../BACKEND_TRUTHS.md)
- [WWPTD_EPIC_PORTFOLIO_2026-04-17](./WWPTD_EPIC_PORTFOLIO_2026-04-17.md)

Current orchestration authority is [AGENTS.md](../../AGENTS.md) and [AGENT_OPERATING_MODEL.md](../AGENT_OPERATING_MODEL.md), including the two-implementation-lanes-plus-one-physical-gate limit.

---

## The role

While the protocol agent is frozen (through ~2026-04-22), the mobile/backend
agent holds the **dispatcher role**. This role carries three hats:

1. **Orchestrator** — pick which bead each agent takes, in what order, in
   what worktree.
2. **WWPTD reviewer** — review every PR against the TRUTHS trio before
   merging to main. Arrow-of-truth, role separation, naming discipline,
   no silent failures, attestation lineage intact.
3. **Merger** — hold the main branch. Merge clean; bounce drift with tight
   feedback.

When the protocol agent thaws, the role continues for mobile/backend lane
work but the protocol agent resumes authority over `wdvr` + `0uv8` + related
beads. Dispatcher hands back the protocol lane immediately.

---

## Dispatch principles

### P-D1 Parallel cadence is gated on reviewer bandwidth

**Max 3 agents in parallel.** More agents ≠ more throughput when the
reviewer is the bottleneck. Six agents = rubber-stamp reviews = TRUTHS drift
sneaks in = gift posture broken.

Three agents land work at a cadence the dispatcher can review honestly.
Scale up only if review time genuinely frees.

### P-D2 Worktree isolation for parallel agents

Every parallel agent gets `isolation: "worktree"` on the `Agent` tool
invocation. Each worktree is its own branch. No two agents edit main
simultaneously.

Dispatcher merges worktree branches back to main in sequence, reviewing
each.

### P-D3 File-overlap check before spawning parallel

Before spawning N agents in parallel, verify their bead scopes do not
touch the same files. If they do, serialize within that lane and
parallelize across lanes (mobile ∥ backend ∥ docs).

When conflict is unavoidable, choose merge order up front (typically:
structural refactor first, surface rename second).

### P-D4 WWPTD check at merge, not at spawn

Agents may drift mid-bead. The dispatcher catches drift at PR review, not
by over-specifying the brief. Briefs should be tight on scope fences and
TRUTHS citations, not exhaustive on implementation detail.

### P-D5 Gift posture is the merge gate

Before merging any bead's PR to main, the dispatcher asks:

> Would the protocol agent, returning from freeze, love to find this in
> the repo? Does it read as work they'd want to build on — or work they'd
> want to undo?

If the answer is the second, bounce. Tighter brief, spawn again.

### P-D6 Bead bookkeeping is part of the role

When a bead's PR merges, the dispatcher closes the bead in `bd`. Updates
dependencies on downstream beads. Writes a one-line commit note to
MEMORY.md if the bead changed durable state.

### P-D7 Escalation on stall

If any agent is blocked > 1 day on a single bead, the dispatcher:
1. Breaks the bead into smaller sub-beads, or
2. Takes the bead inline (dispatcher implements), or
3. Flags to Tim for scope renegotiation

Silent stalling = wasted agent-hours.

### P-D8 Inline for small, spawn for big

Rule of thumb:
- **< 2 hours** = dispatcher inline (faster than spawning + reviewing)
- **2 hours – 3 days** = spawn a worktree agent
- **> 3 days** = spawn dedicated slow-cooker agent; consider sub-beading

M1 clock-domain (~1hr) is inline. M2 BLE (3-4 wks) is slow-cooker with
sub-beads as needed.

---

## Agent dispatch brief template

Every agent spawn includes these fields in the prompt:

```
Bead: {bead-id} — {title}
Status: {status} / Dependencies: {deps}

Why this matters:
{one paragraph — the outcome, not the task}

TRUTHS guardrails:
- {PROTOCOL_TRUTHS §N or MOBILE_TRUTHS §N or BACKEND_TRUTHS §N} — {what it requires}
- {repeat for every relevant section}

Scope — in:
- {bullet}
- {bullet}

Scope — out (explicitly deferred):
- {bullet — usually other beads that cover this}

Done-when:
- {measurable done criterion}
- {measurable done criterion}

Gift-posture check before you stop:
- Does every string use post-TRUTHS vocabulary?
- Are roles held distinct (attester vs executor vs projector, or witness vs wallet)?
- Does the arrow of truth flow the right way (chain → backend → rider)?
- If the protocol agent read this PR, would they smile?

Worktree: {branch name — isolation: worktree}
Report back: PR-style diff summary, test results, gift-posture self-check.
```

---

## Current sprint state — 2026-04-17

### Phase 0 (today)

- [ ] Dispatcher lands `5hdl.1` M1 clock-domain inline (~1 hr)
- [x] Cut remaining beads (`mfab.5`, `wg8t`)
- [ ] Write dispatch briefs for Phase 1 beads

### Phase 1 (Apr 17-18) — parallel spin-up

Three agents in parallel worktrees (no critical file overlap):

| Agent | Bead | Worktree | Expected runtime |
|-------|------|----------|------------------|
| α | `mfab.5` B1 Phase A nomenclature | `wt-backend-name` | ~1 wk |
| β | `5hdl.4` M4 Local ride archive | `wt-mobile-archive` | ~1 wk |
| γ | `5hdl.5` M5 Android + Seeker | `wt-mobile-android` | ~1 wk |

### Phase 2 (Apr 19-21) — rolling dispatch

As Phase 1 agents finish:
- Next: `mfab.1` B2 role decomposition (after `mfab.5` clean, same lane)
- Next: `5hdl.2` M2 BLE sensor pairing (3-4 wk slow-cooker, dedicated agent)

### Phase 3 (Apr 22+) — protocol thaw

Protocol agent returns, resumes `0uv8` + `wdvr.8`. Phase B backend beads
(`mfab.3`, `mfab.4`) unblock when `0uv8` lands. Dispatcher dispatches them.

### Phase 4 (Apr 29 – May 5) — convergence

Mobile + backend lanes converge. Dispatcher drives `flqu` X2 demo script
personally. Demo narrative frozen by Apr 28.

### Phase 5 (May 6-11) — demo hardening

No new features. Regressions only. Rehearse end-to-end. Submit May 11.

---

## Continuous responsibilities

1. WWPTD review on every PR.
2. Merge discipline — never accept a PR that leaks TRUTHS.
3. Bead bookkeeping — close beads, update deps, memory snapshots.
4. Context preservation — memory updates before compact, so role survives.
5. Escalation — flag blocked work > 1 day.

---

## Failure modes watched

- **Agent drifts from TRUTHS mid-bead** → caught at review, bounced.
- **Two worktrees collide** → reconcile at merge, adjust order.
- **Agent runs out of context on slow-cooker bead** → break into sub-beads.
- **Protocol agent returns and disagrees with Phase A rename** → adjust;
  `mfab.5` was always feeder, never final.
- **Hackathon scope creep** → demo script is the gate. Bead without a
  demo beat waits.
- **Dispatcher context compacts mid-sprint** → memory + this playbook
  restore the role; spawned agents continue their worktrees independently.

---

## Handing off the role

If the dispatcher hands off (compact, Tim takes over directly, or protocol
agent returns and subsumes the role):

1. Push all open branches.
2. Update this doc's "Current sprint state" section with the latest.
3. Close or re-assign any stale spawned-agent tasks.
4. Update memory pointer.

The repo is the durable handoff surface. Memory is the pointer. Agent
conversations are ephemeral.
