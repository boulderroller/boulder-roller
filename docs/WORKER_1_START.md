# Worker 1: Solana Programs Engineer - START HERE

> **Note:** This onboarding doc references legacy program deployments. Current protocol mechanics live in
> `history/BR_cal_allocation_refactor_spec.md`.

## Your Role
You are the Solana Programs Engineer for Boulder Rollers V2.

## Your Mission
Deploy the 3 Solana programs to devnet and ensure CAL/staking features work end-to-end.

---

## MVP SCOPE - What to SKIP

You do NOT need to implement these for MVP:
- ❌ Swanny Seats (governance feature - post-MVP)
- ❌ Epochs and leaderboards (competition feature - post-MVP)
- ❌ Reward distribution (depends on epochs - post-MVP)

Focus ONLY on:
- ✅ CAL system (mint_daily_cal, burn_cal_for_segment)
- ✅ Segment creation (create_segment, initialize_counter)
- ✅ Staking system (stake_in_segment, unstake_from_segment, LP tokens)
- ✅ Proof verification (proof_verifier program - already complete)
- ✅ DUNG minting (dung_mint program - already complete)

---

## Quick Start - Your First 3 Tasks

### Task 1: Read Your Documentation (10 minutes)
1. Read `/docs/WORKER_1_SOLANA_PROGRAMS.md` - Your detailed task breakdown
2. Read `/docs/INTEGRATION_REGISTRY.md` - Coordination document (UPDATE THIS as you work)
3. Read `/docs/schemas.md` - On-chain account structures reference

### Task 2: Verify Current State (15 minutes)
```bash
cd /Users/gabetemp/curahee/BoulderRollers-v2/protocol/anchor

# Verify programs compile
anchor build

# Check existing tests
ls tests/
# You should see: proof_and_mint.spec.ts, boulder_rollers_cal.spec.ts, boulder_rollers_stake.spec.ts

# Run existing tests
anchor test
```

Expected result: All programs compile, existing tests pass.

### Task 3: Write Missing Tests (Day 1 Priority)
The programs work but tests are incomplete. You need to write comprehensive tests for:
- User initialization
- Daily CAL minting (verify once-per-day limit)
- Segment creation (verify DUNG burn, SOL payment)
- LP token math (first staker 1:1, subsequent pro-rata)
- Unstaking (verify correct DUNG return)

Target: **15+ test cases** covering all 8 implemented instructions.

---

## Your Complete Task List

### Phase 1: Testing & Deployment (Days 1-2)

**Priority 1 - Testing**:
1. Write comprehensive Anchor tests for all 8 instructions
2. Test edge cases (daily limit, insufficient balance, etc.)
3. Ensure 100% test pass rate

**Priority 2 - Deployment**:
4. Deploy proof_verifier to devnet
5. Deploy dung_mint to devnet (requires proof_verifier program ID)
6. Create DUNG SPL token mint
7. Set DUNG mint authority to dung_mint PDA
8. Deploy boulder_rollers to devnet
9. Generate IDL files for all programs

**Priority 3 - Documentation**:
10. Update `/docs/INTEGRATION_REGISTRY.md` with:
    - All 3 program IDs
    - DUNG token mint address
    - Treasury account address
11. Commit IDL files to repo
12. Document any breaking changes or assumptions

### Phase 2: Integration Support (Days 3-4)

13. Help Worker 2 integrate programs via Anchor client
14. Test program calls from Python (Worker 2's backend)
15. Debug any transaction failures
16. Monitor devnet for program stability

---

## Success Criteria

By end of your work, you should have:
- [ ] All 3 programs deployed to devnet
- [ ] 15+ Anchor tests passing (100% pass rate)
- [ ] Program IDs published in Integration Registry
- [ ] IDL files committed to `/protocol/anchor/target/idl/`
- [ ] DUNG token mint created and authority set
- [ ] Treasury account configured
- [ ] No compilation errors or warnings
- [ ] Documentation updated

---

## Coordination with Other Workers

### You UNBLOCK these workers:
- **Worker 2 (Backend)**: Needs your program IDs and IDL files to integrate Solana calls
- **Worker 3 (iOS)**: Needs program IDs if they do direct Solana calls (likely via backend proxy)

### Your Integration Registry Updates:
Update `/docs/INTEGRATION_REGISTRY.md` with this info:

```markdown
## Solana Programs (Worker 1)

### Deployed Program IDs (Devnet)
- **proof_verifier**: `ABC123...` ← YOUR UPDATE
- **dung_mint**: `DEF456...` ← YOUR UPDATE
- **boulder_rollers**: `GHI789...` ← YOUR UPDATE

### Token Addresses
- **DUNG Mint**: `JKL012...` ← YOUR UPDATE
- **Treasury Account**: `MNO345...` ← YOUR UPDATE

### Current Status
- Programs compile: ✅
- Tests written: ✅ (15 tests) ← YOUR UPDATE
- Deployed to devnet: ✅ ← YOUR UPDATE
```

Commit with: `git commit -m "chore(integration): Worker 1 - deployed programs to devnet"`

---

## Key Commands Reference

### Build & Test
```bash
cd protocol/anchor
anchor build                 # Compile all programs
anchor test                  # Run test suite
anchor test -- --grep "CAL"  # Run specific test
```

### Deploy
```bash
# Set to devnet
solana config set --url https://api.devnet.solana.com

# Airdrop SOL for deployment
solana airdrop 2

# Deploy all programs
anchor deploy

# Get program IDs
solana address -k target/deploy/proof_verifier-keypair.json
solana address -k target/deploy/dung_mint-keypair.json
solana address -k target/deploy/boulder_rollers-keypair.json
```

### Create DUNG Token
```bash
# Create mint
spl-token create-token --decimals 9

# Get mint authority PDA (from dung_mint program)
# Set authority to dung_mint PDA
spl-token authorize <MINT_ADDRESS> mint <PDA_ADDRESS>
```

---

## Need Help?

### Documentation Resources:
- Anchor Docs: https://www.anchor-lang.com/docs
- Solana Cookbook: https://solanacookbook.com/
- SPL Token Docs: https://spl.solana.com/token

### Debug Issues:
- Check test output for specific errors
- Use `solana logs` to view program logs
- Verify account sizes and rent-exemption
- Check PDA derivation matches test expectations

---

## Communication Protocol

**Daily Update** - Post to integration registry:
```
Worker 1 Status:
✅ Completed: [list]
⏳ In Progress: [current task]
❌ Blocked By: [none/issue]
```

**When you publish program IDs** - Alert in integration registry:
```
🚨 WORKER 1: Program IDs published! Backend and iOS can now integrate.
```

---

**Ready? Start with Task 1: Read your documentation. Good luck! 🚀**
