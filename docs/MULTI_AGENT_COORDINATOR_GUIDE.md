# Multi-Agent Coordinator Guide

## Overview

You now have a complete setup to execute the Boulder Rollers V2 MVP using 4 parallel AI agents (Claude Code instances). This document explains how to spawn and manage these workers.

---

## Setup Complete ✅

The following documents have been created:

1. **`/docs/INTEGRATION_REGISTRY.md`** - Shared coordination document
   - All workers read from and write to this file
   - Acts as "shared memory" between agents
   - Contains program IDs, API URLs, database URLs, etc.

2. **`/docs/WORKER_1_START.md`** - Solana Engineer starting instructions
3. **`/docs/WORKER_2_START.md`** - Backend Engineer starting instructions
4. **`/docs/WORKER_3_START.md`** - iOS Engineer starting instructions
5. **`/docs/WORKER_4_START.md`** - DevOps Engineer starting instructions

---

## How to Spawn Workers

### Option A: Spawn via Claude Code Sessions

For each worker, open a new Claude Code session and give them this exact prompt:

#### Worker 1 (Solana)
```
I am Worker 1, the Solana Programs Engineer for Boulder Rollers V2.

Please read and execute the instructions in /docs/WORKER_1_START.md

This is my starting point. I will work independently and update /docs/INTEGRATION_REGISTRY.md as I complete tasks.

My primary goal: Deploy all 3 Solana programs to devnet and publish program IDs to the integration registry.

Please begin by reading the START document and proceeding with the tasks.
```

#### Worker 2 (Backend)
```
I am Worker 2, the Backend API Engineer for Boulder Rollers V2.

Please read and execute the instructions in /docs/WORKER_2_START.md

This is my starting point. I will work independently and update /docs/INTEGRATION_REGISTRY.md as I complete tasks.

My primary goal: Complete the FastAPI backend with Solana integration and deploy to the dev server.

Please begin by reading the START document and proceeding with the tasks.
```

#### Worker 3 (iOS)
```
I am Worker 3, the iOS App Engineer for Boulder Rollers V2.

Please read and execute the instructions in /docs/WORKER_3_START.md

This is my starting point. I will work independently and update /docs/INTEGRATION_REGISTRY.md as I complete tasks.

My primary goal: Complete the SwiftUI iOS app with backend integration.

Please begin by reading the START document and proceeding with the tasks.
```

#### Worker 4 (DevOps)
```
I am Worker 4, the DevOps Engineer for Boulder Rollers V2.

Please read and execute the instructions in /docs/WORKER_4_START.md

This is my starting point. I will work independently and update /docs/INTEGRATION_REGISTRY.md as I complete tasks.

My primary goal: Provision dev infrastructure and deploy the backend API.

Please begin by reading the START document and proceeding with the tasks.
```

### Option B: Use the `/task` Command (if available in your CLI)

```bash
# Spawn Worker 1
/task --role="Worker 1 Solana Engineer" --instructions="/docs/WORKER_1_START.md" --registry="/docs/INTEGRATION_REGISTRY.md"

# Spawn Worker 2
/task --role="Worker 2 Backend Engineer" --instructions="/docs/WORKER_2_START.md" --registry="/docs/INTEGRATION_REGISTRY.md"

# Spawn Worker 3
/task --role="Worker 3 iOS Engineer" --instructions="/docs/WORKER_3_START.md" --registry="/docs/INTEGRATION_REGISTRY.md"

# Spawn Worker 4
/task --role="Worker 4 DevOps Engineer" --instructions="/docs/WORKER_4_START.md" --registry="/docs/INTEGRATION_REGISTRY.md"
```

---

## Monitoring Progress

### Check Integration Registry Regularly

```bash
# View current state
cat docs/INTEGRATION_REGISTRY.md

# Check for updates (look for timestamps)
git log --oneline docs/INTEGRATION_REGISTRY.md

# See what each worker has updated
git log --all --grep="Worker" --oneline
```

### Checkpoint Schedule

**End of Day 1** - Verify:
- [ ] Worker 1: Programs compile, tests in progress
- [ ] Worker 2: Database set up, API running locally
- [ ] Worker 3: Xcode project created, dependencies added
- [ ] Worker 4: Terraform applied, droplet IP obtained

**End of Day 2** - Verify:
- [ ] Worker 1: Program IDs published to integration registry (CRITICAL!)
- [ ] Worker 2: Solana client skeleton ready
- [ ] Worker 3: Auth flow updated to nonce-challenge
- [ ] Worker 4: Backend deployed to droplet

**End of Day 3** - Verify:
- [ ] Worker 2: Real Solana transactions working
- [ ] Worker 3: Testing against live backend
- [ ] All: Integration tests passing

---

## Handling Worker Questions

Workers may ask you questions via the integration registry or git commits. Monitor for:

```bash
# Check for questions in commits
git log --all --grep="QUESTION" --oneline

# Check for blocked status
grep "❌ Blocked" docs/INTEGRATION_REGISTRY.md
```

If a worker is blocked:
1. Identify the blocker (usually waiting for another worker)
2. Check if blocking worker has completed their task
3. Intervene if necessary (update integration registry manually)

---

## Integration Registry Workflow

### Workers will update the registry like this:

```bash
# Worker pulls latest
git pull origin main

# Worker edits their section
# Worker 1 updates: Solana Programs section
# Worker 2 updates: Backend API section
# Worker 3 updates: iOS App section
# Worker 4 updates: Infrastructure section

# Worker commits
git add docs/INTEGRATION_REGISTRY.md
git commit -m "chore(integration): Worker 1 - deployed programs to devnet"
git push origin main
```

### You can track updates:

```bash
# Watch for changes (run in background)
watch -n 30 'git pull && tail -20 docs/INTEGRATION_REGISTRY.md'

# View update history
git log --oneline --all docs/INTEGRATION_REGISTRY.md

# See current state
cat docs/INTEGRATION_REGISTRY.md | grep "✅"
cat docs/INTEGRATION_REGISTRY.md | grep "⏳"
cat docs/INTEGRATION_REGISTRY.md | grep "❌"
```

---

## Critical Coordination Points

### 1. Program IDs (Worker 1 → Workers 2 & 3)

**When**: End of Day 1 or early Day 2
**What**: Worker 1 must publish program IDs to integration registry
**Impact**: Workers 2 & 3 are soft-blocked without this

**Monitor**:
```bash
grep "proof_verifier:" docs/INTEGRATION_REGISTRY.md
grep "dung_mint:" docs/INTEGRATION_REGISTRY.md
grep "boulder_rollers:" docs/INTEGRATION_REGISTRY.md
```

If still `[PENDING]` after Day 2, intervene.

### 2. API URL (Worker 4 → Workers 2 & 3)

**When**: End of Day 1
**What**: Worker 4 must publish dev API URL to integration registry
**Impact**: Workers 2 & 3 need this to test/deploy

**Monitor**:
```bash
grep "Dev API URL:" docs/INTEGRATION_REGISTRY.md
```

If still `[PENDING - from Worker 4]` after Day 1, intervene.

### 3. Backend Deployment (Worker 2 → Worker 3)

**When**: Day 3
**What**: Worker 2 must deploy functional API
**Impact**: Worker 3 can't test iOS app without live backend

**Monitor**:
```bash
# Test API health
API_URL=$(grep "Dev API URL:" docs/INTEGRATION_REGISTRY.md | awk '{print $4}')
curl $API_URL/health/db
```

---

## Success Metrics

### End of Week 1 - Target State

**Infrastructure**:
- [ ] Dev droplet running
- [ ] Backend API deployed and healthy
- [ ] Database provisioned and migrated

**Solana**:
- [ ] All 3 programs on devnet
- [ ] 15+ tests passing
- [ ] Program IDs published

**Backend**:
- [ ] All pytest tests passing
- [ ] Real Solana transactions working
- [ ] API accessible publicly

**iOS**:
- [ ] App builds and runs
- [ ] Auth works with backend
- [ ] CAL and staking UIs functional

**Integration Test** (Run this yourself):
```bash
# 1. Open iOS app
# 2. Create wallet
# 3. Authenticate
# 4. View CAL balance
# 5. Mint daily CAL
# 6. Stake in segment
# 7. View staking claims

# All should work end-to-end
```

---

## If Things Go Wrong

### Worker Not Making Progress
1. Check integration registry for blocked status
2. Review worker's git commits
3. Spawn new session with more specific instructions
4. Or manually complete blocking task

### Workers Conflicting
1. Check for merge conflicts in integration registry
2. Manually resolve conflicts
3. Update registry with resolution
4. Instruct workers to pull latest

### Missing Coordination
1. Identify what wasn't communicated
2. Update integration registry manually
3. Alert workers via commit message

### Need to Restart a Worker
Simply spawn a new session with the same starting prompt. The START files are idempotent - workers can pick up where they left off by reading the integration registry.

---

## Timeline Expectations

**Day 1**: Setup and foundation work
- All workers setting up their environments
- Worker 4 provisions infrastructure fastest
- Worker 1 starts test writing

**Day 2**: First integration point
- Worker 1 deploys programs (unblocks others)
- Worker 4 deploys backend (enables testing)
- Workers 2 & 3 start integration work

**Day 3**: End-to-end flows
- Backend calling Solana programs
- iOS calling backend APIs
- First complete user flow working

**Days 4-5**: Polish and testing
- Bug fixes from integration testing
- UI polish
- Comprehensive testing

---

## Your Role as Coordinator

1. **Monitor** - Check integration registry daily
2. **Unblock** - Identify and resolve blockers
3. **Verify** - Test integration points
4. **Communicate** - Update workers when needed
5. **Validate** - Ensure MVP scope maintained (no Swanny Seats, no Epochs)

You are NOT coding - you are orchestrating 4 AI agents to code in parallel.

---

## Quick Reference Commands

### Check Status
```bash
cat docs/INTEGRATION_REGISTRY.md
```

### See Recent Updates
```bash
git log --oneline docs/INTEGRATION_REGISTRY.md -10
```

### Test API Health
```bash
API_URL=$(grep "Dev API URL:" docs/INTEGRATION_REGISTRY.md | awk '{print $4}')
curl $API_URL/health/db
```

### Check Program IDs Published
```bash
grep "Program IDs" docs/INTEGRATION_REGISTRY.md -A 5
```

### Monitor for Blockers
```bash
grep "❌" docs/INTEGRATION_REGISTRY.md
```

---

## Ready to Launch? 🚀

1. **Commit all setup files**:
   ```bash
   git add docs/INTEGRATION_REGISTRY.md docs/WORKER_*_START.md
   git commit -m "chore: add multi-agent execution setup"
   git push origin main
   ```

2. **Spawn all 4 workers** using Option A prompts above

3. **Monitor progress** daily via integration registry

4. **Intervene** only when workers are blocked

5. **Celebrate** when full stack is working! 🎉

---

**Estimated Timeline to Working MVP**: 5-7 days

**Key Success Factor**: The integration registry keeps workers coordinated without manual intervention.

**Good luck! Your MVP is within reach.**
