> **Reading this repository?** Start with `AGENTS.md`, a guide written for
> agents. In this public copy that path holds the guide; the agent contract
> that the text below calls `AGENTS.md` is kept unchanged at
> `docs/process/AGENTS.md`.

# BoulderRoller Claude Entry Point

Follow AGENTS.md; it is the binding delivery and safety contract for every
Claude session and subagent. Use docs/AGENT_OPERATING_MODEL.md for the compact
preflight, direct-JSONL Beads commands, worktree handling, risk-scaled gates,
landing, and cleanup. Do not restate either source here.

## Read Only What the Task Needs

Route to the narrowest current authority:

| Question or change | Authority |
|---|---|
| Protocol meaning, roles, canon, permanence, attestation | docs/PROTOCOL_TRUTHS.md |
| Current product strategy and frozen inventory | docs/FRESHEST_SPEC.md |
| Backend behavior | docs/BACKEND_TRUTHS.md |
| Portal behavior | docs/PORTAL_TRUTHS.md |
| Native/mobile behavior | docs/MOBILE_TRUTHS.md |
| Rider vocabulary and CTAs | relevant section of docs/design/LANGUAGE_SPEC.md |
| CAL/DUNG visible-state composition | relevant section of docs/design/PROOF_ECONOMY_PRIMITIVES.md |
| Brand hierarchy and identity | relevant section of docs/design/BR_IDENTITY_SYSTEM.md |
| Canon implementation decisions | docs/design/CANON_BUILD_DECISIONS.md |
| Runtime behavior | current source, tests, migrations, and deployed state |

Do not load every authority automatically. Follow the risk-based language
routing in AGENTS.md. Current branch, tracker, deployment, provider, and
world-state status must be checked live rather than inferred from this file.

## Standing Product Frame

- Zero-start: no TGE is scheduled or presented as a horizon.
- Canon-first climb identity: rides provide evidence; they do not define climb
  identity.
- First Cohort and Philadelphia are the current product spine.
- BeetleCard leveling/upgrades, archetypes, marketplace, emission tuning, and
  liquidity-era mechanics remain frozen until explicitly ratified otherwise.
- Product filter: *does it make the hill matter more?*

The cited authority files contain the exact boundaries; these bullets are
routing context, not a parallel specification.

## Repository Map

- backend/ — Python API and ride processing
- web/portal/ — rider portal
- mobile/ and ios/ when present — native clients; verify the current lane
- workout-parse/ — Rust parsing and climb analysis
- protocol/anchor/ — Solana programs
- backend/sql/ — canonical database migrations
- backend/supabase/migrations/ — Supabase CLI mirrors of canonical migrations
- supabase/migrations/ — retired, checksum-frozen historical files
- scripts/ and tools/ — repository operations and focused utilities

Addresses come from protocol/anchor/addresses.devnet.json; environment
requirements come from the relevant .env.example; secrets stay in ignored
environment files. Do not copy changing addresses, test totals, deployment
status, or infrastructure state into this entrypoint.

Tracked hooks and focused scripts protect H3 resolution, detector parameters,
tokenomics, devnet addresses, and touched-language surfaces. Let the relevant
hook run; do not run every unrelated gate preemptively.

The existing H3 tile invariant remains resolution 10:

# H3 tiles
cells = workout_parse.get_h3_strings(activity.lat_e7, activity.lon_e7, resolution=10)

# Climb detection (terrain-adaptive)

## Working Relationship

- Take initiative inside admitted scope.
- A short affirmative such as “yes”, “ok”, “1”, or “go” means proceed with the
  bounded proposal.
- Use subagents only for independent parallel work or a genuinely separate
  authority/risk. Routine work stays single-agent.
- Prefer concise owner/status/blocker/next-action updates and compact tool
  output.
- Be cost-conscious and identify provider spend before proposing it.
- Diagnose from current source and evidence; fix root causes rather than
  wrapping symptoms.
- For resume/status requests, inspect recent Git, admitted Beads, relevant
  worktrees, and live state without re-reading the entire repository.

## Product Feel

Fitness-first, not crypto-first. Clean, minimal, utilitarian interfaces. Use the
beetle metaphor lightly. Favor readable training data over spectacle, and make
the hill matter more.
