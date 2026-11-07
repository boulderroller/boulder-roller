> Historical record from November 2024, kept for reference and no longer
> maintained. Current work is tracked in the repository's issue tracker.

# Known Issues & Workarounds

**Last Updated:** 2024-11-28
**Project:** Boulder Rollers V2

This document tracks known issues, version mismatches, warnings, and their workarounds.

---

## 🔴 CRITICAL ISSUES

### None Currently

All critical blockers from earlier development have been resolved.

---

## 🟡 WARNINGS & NON-BLOCKING ISSUES

### 1. SPL Token-2022 Clock Warnings

**Issue:**
When running `anchor test`, you see repeated warnings:
```
WARN solana_runtime::message_processor::stable_log - spl_token_2022::extension::transfer_fee::processor::process_initialize_transfer_fee_config: "Using incorrect proof context account for transfer fee"
```

**Severity:** Low - Does not affect functionality
**Component:** Solana programs (anchor-spl dependency)
**Root Cause:** token-2022 program emits clock-related warnings in test environment

**Workaround:**
```toml
# In programs/boulder_rollers/Cargo.toml and programs/dung_mint/Cargo.toml
# Current configuration (includes token-2022):
anchor-spl = { version = "0.29.0", default-features = false, features = ["token", "token_2022"] }

# Alternative (remove token-2022 to eliminate warnings):
anchor-spl = { version = "0.29.0", default-features = false, features = ["token"] }
```

**Status:** Resolved in Session 1 by adding feature flags
**Recommendation:** Keep token-2022 for future-proofing unless warnings are problematic

---

### 2. Anchor Version Mismatch

**Issue:**
Earlier in development, there were mismatches between:
- Anchor CLI version
- anchor-lang crate version
- Rust toolchain version

**Severity:** Resolved - Was high, now low
**Component:** Solana build system

**Resolution Applied:**
```toml
# Cargo.toml (workspace level)
[workspace]
resolver = "2"  # Use Rust 2021 edition resolver

# All Cargo.toml files
[dependencies]
anchor-lang = "0.29.0"
anchor-spl = { version = "0.29.0", default-features = false, features = ["token", "token_2022"] }
```

```bash
# Verify versions match
anchor --version  # Should show: anchor-cli 0.29.0
rustc --version   # Should show: rustc 1.75.0 or higher
```

**Status:** ✅ Resolved in Session 1
**Prevention:** Pin Anchor version in Anchor.toml and all Cargo.toml files

---

### 3. Solana CLI Config Switching

**Issue:**
When switching between localnet/devnet/mainnet, program IDs and configurations can get out of sync.

**Severity:** Medium - Can cause deployment issues
**Component:** Solana CLI, Anchor.toml

**Symptoms:**
- Wrong program deployed to wrong cluster
- IDL doesn't match deployed program
- Transaction errors about unknown program

**Workaround:**
```bash
# Always explicitly set cluster before deploying
solana config set --url https://api.devnet.solana.com

# Verify current cluster
solana config get
# Check: RPC URL matches your intent

# Update Anchor.toml provider.cluster to match
[provider]
cluster = "Devnet"

# Re-build to ensure IDLs are correct
anchor build
```

**Prevention:**
- Create separate Anchor.toml configs for each cluster
- Use anchor deploy --provider.cluster devnet explicitly
- Check `solana config get` before every deployment

---

### 4. Python Dataclass Slots Compatibility

**Issue:**
Backend uses `dataclass(slots=True)` which requires Python 3.10+

**Severity:** Low - Only affects older Python versions
**Component:** Backend API

**Error Message:**
```
TypeError: __init_subclass__() got an unexpected keyword argument 'slots'
```

**Resolution:**
```bash
# Ensure Python 3.10 or higher
python3 --version  # Should show: Python 3.10.x or higher

# If using older Python, either:
# Option A: Upgrade Python
brew upgrade python3

# Option B: Remove slots from dataclasses (not recommended)
# In backend code, change:
@dataclass(slots=True)  # Remove slots=True
class MyClass:
    ...
```

**Status:** ✅ Resolved - Code uses Python 3.10+ features
**Requirement:** Python 3.10+ for backend development

---

## 🔵 INFRASTRUCTURE ISSUES

### 5. Terraform State Not Using Remote Backend

**Issue:**
Terraform state is stored locally, not in remote backend (S3/DO Spaces)

**Severity:** Low for dev, High for production
**Component:** Infrastructure (Terraform)

**Risk:**
- State file can be lost if local machine fails
- Cannot collaborate with multiple developers
- State drift if multiple people run terraform

**Current State:**
```hcl
# No backend configuration in infrastructure/terraform/dev/main.tf
# State stored in: infrastructure/terraform/dev/terraform.tfstate
```

**Recommended Fix (Production):**
```hcl
# Add to infrastructure/terraform/prod/main.tf
terraform {
  backend "s3" {
    bucket = "boulder-rollers-terraform-state"
    key    = "prod/terraform.tfstate"
    region = "us-east-1"
    # Or use DigitalOcean Spaces:
    # endpoint = "https://nyc3.digitaloceanspaces.com"
  }
}
```

**Status:** Acceptable for dev, needs fix before production
**Timeline:** Address in Session 3 (production planning)

---

### 6. No HTTPS/SSL on Dev Environment

**Issue:**
Dev API URL is HTTP only (http://IP:8080), not HTTPS

**Severity:** Low for dev, High for production
**Component:** Load balancer, API deployment

**Current State:**
- Load balancer configured for HTTP only
- No SSL certificate
- No domain name

**Impact:**
- iOS App Transport Security requires HTTPS for production
- Credentials transmitted in plain text
- Not suitable for real user data

**Workaround (Dev):**
```xml
<!-- In iOS Info.plist -->
<key>NSAppTransportSecurity</key>
<dict>
    <key>NSAllowsArbitraryLoads</key>
    <true/>
    <!-- OR allow specific domain: -->
    <key>NSExceptionDomains</key>
    <dict>
        <key>YOUR_DEV_IP</key>
        <dict>
            <key>NSExceptionAllowsInsecureHTTPLoads</key>
            <true/>
        </dict>
    </dict>
</dict>
```

**Production Fix:**
1. Register domain (e.g., api.boulderrollers.com)
2. Point domain to load balancer
3. Add Let's Encrypt SSL certificate via certbot
4. Update load balancer to use HTTPS (port 443)
5. Update iOS app to use https:// URLs

**Status:** Acceptable for dev, must fix for production
**Timeline:** Address in Session 3

---

## 🟢 IOS-SPECIFIC ISSUES

### 7. Xcode Project Must Be Created Manually

**Issue:**
Cannot automate Xcode project creation via CLI/AI

**Severity:** Medium - Blocks Worker 3 progress
**Component:** iOS development

**Reason:**
- Xcode project format is complex binary plist
- SPM dependencies require Xcode IDE to resolve
- Code signing requires manual configuration

**Workaround:**
None - User must create project manually in Xcode

**Status:** ⏳ Blocked on user action
**Reference:** See `/docs/USER_ACTION_REQUIRED.md` Step 4

---

### 8. Mapbox SDK Size (80MB)

**Issue:**
MapboxMaps SDK is ~80MB when included in iOS app

**Severity:** Low - Affects app size
**Component:** iOS dependencies

**Impact:**
- Larger download size for users
- Longer build times
- Increased memory usage

**Workaround:**
- Use conditional compilation (#if MAPBOX)
- Provide placeholder map view without Mapbox
- Make Mapbox optional dependency

**Current Implementation:**
```swift
// iOS code already supports this
#if canImport(MapboxMaps)
import MapboxMaps
// Use Mapbox
#else
// Show placeholder
#endif
```

**Status:** ✅ Implemented - Mapbox is optional
**Recommendation:** Use placeholder for MVP, add Mapbox later

---

### 9. Simulator vs Device Networking

**Issue:**
`localhost:8080` works in simulator but not on physical device

**Severity:** Medium - Affects device testing
**Component:** iOS networking

**Explanation:**
- Simulator shares localhost with Mac
- Physical device is on different network
- Cannot reach Mac's localhost

**Workaround:**
```swift
// Option A: Use ngrok tunnel
// Run on Mac: ngrok http 8080
// Use ngrok URL in iOS app

// Option B: Use Mac's LAN IP
#if DEBUG
baseURL = "http://192.168.1.100:8080"  // Your Mac's IP
#else
baseURL = "https://api.boulderrollers.com"
#endif

// Option C: Wait for Worker 4 to deploy backend
// Use public URL from integration registry
```

**Status:** Will resolve after Worker 4 deploys backend
**Timeline:** Session 2

---

## ⚙️ BUILD & TEST ISSUES

### 10. Anchor Tests Run Serially, Not in Parallel

**Issue:**
Running `anchor test` executes all test files but some tests interfere with each other

**Severity:** Low - Tests still pass individually
**Component:** Anchor test framework

**Symptoms:**
```bash
# This may fail:
anchor test

# But these pass:
anchor test --skip-local-validator tests/boulder_rollers_cal.spec.ts
anchor test --skip-local-validator tests/boulder_rollers_stake.spec.ts
```

**Root Cause:**
- Tests may share global state (clock, accounts)
- Parallel execution causes race conditions

**Workaround:**
```bash
# Run tests individually
for test in tests/*.spec.ts; do
  echo "Running $test"
  anchor test --skip-local-validator "$test"
done
```

**Status:** Acceptable for now, can improve test isolation later
**Timeline:** Future optimization (post-MVP)

---

### 11. Backend Tests Require Mock Data

**Issue:**
Backend tests use mock repository, don't test against real database

**Severity:** Low - Unit tests work, need integration tests
**Component:** Backend testing

**Current State:**
```python
# tests/test_routes.py uses MockRepository
# Does not test:
# - Real database queries
# - Database constraints
# - PostGIS operations
```

**Workaround:**
```bash
# Add integration tests in Session 2
# Create tests/integration/ directory
# Use real database connection
# Test against local Postgres + PostGIS
```

**Status:** Unit tests pass, integration tests needed
**Timeline:** Session 2 Task 2.10

---

## 📋 DOCUMENTATION GAPS

### 12. API Documentation Not Generated

**Issue:**
No OpenAPI/Swagger docs for backend API

**Severity:** Low - Workers know the contract via integration registry
**Component:** Backend API documentation

**Impact:**
- Manual testing requires reading code
- Frontend developers need to reference integration registry
- No interactive API explorer

**Fix:**
```python
# FastAPI automatically generates OpenAPI docs
# Access at: http://localhost:8080/docs (Swagger UI)
# Access at: http://localhost:8080/redoc (ReDoc)

# To customize:
app = FastAPI(
    title="Boulder Rollers API",
    description="Cycling fitness app with blockchain integration",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)
```

**Status:** ✅ Available but not documented
**Action:** Add link to integration registry

---

## 🔍 MONITORING & OBSERVABILITY

### 13. No Logging Infrastructure

**Issue:**
No centralized logging, metrics, or alerting

**Severity:** Low for dev, High for production
**Component:** Infrastructure

**Missing:**
- Application logs aggregation (Loki/ELK)
- Error tracking (Sentry)
- Performance monitoring (Datadog/New Relic)
- Uptime monitoring (UptimeRobot)

**Workaround (Dev):**
```bash
# View logs locally
docker logs -f boulder-api

# View Solana program logs
solana logs | grep "Program <PROGRAM_ID>"
```

**Production Plan:**
- Add Prometheus + Grafana (Worker 4 has configs ready)
- Add Sentry for error tracking
- Add structured logging (JSON format)
- Add health check monitoring

**Status:** Acceptable for dev, plan for production
**Timeline:** Session 3

---

## 🛠️ QUICK FIX REFERENCE

### Reset Everything (Nuclear Option)

```bash
# If you get into a weird state, reset:

# 1. Clean Solana programs
cd protocol/anchor
anchor clean
rm -rf target/
cargo clean

# 2. Rebuild
anchor build

# 3. Reset Solana CLI config
solana config set --url http://localhost:8899
rm -rf ~/.config/solana/cli/config.yml

# 4. Restart local validator (if using)
solana-test-validator --reset

# 5. Reset backend database (if local)
docker compose down -v
docker compose up -d postgres

# 6. Clean iOS (if Xcode project exists)
# In Xcode: Product → Clean Build Folder (Shift+Cmd+K)
```

---

## 📞 Getting Help

### Where to Look First

1. **This file** - Check if your issue is documented
2. **Integration Registry** - `/docs/INTEGRATION_REGISTRY.md`
3. **Worker Start Files** - `/docs/WORKER_[1-4]_START.md`
4. **Session Reports** - `/docs/SESSION_*_AUDIT_REPORT.md`

### Common Error Searches

```bash
# Search codebase for error patterns
cd /Users/gabetemp/curahee/BoulderRollers-v2

# Find TODO comments
grep -r "TODO" --include="*.rs" --include="*.py" --include="*.swift"

# Find FIXME comments
grep -r "FIXME" --include="*.rs" --include="*.py" --include="*.swift"

# Find stub implementations
grep -r "stub" --include="*.py"
```

---

## 📝 Reporting New Issues

If you encounter a new issue:

1. **Document it here** with:
   - Clear title
   - Severity level
   - Component affected
   - Steps to reproduce
   - Current workaround
   - Proposed fix

2. **Update integration registry** if it blocks other workers

3. **Tag it** with appropriate emoji:
   - 🔴 CRITICAL (blocks deployment)
   - 🟡 WARNING (degraded functionality)
   - 🔵 INFRASTRUCTURE (devops/config)
   - 🟢 MINOR (cosmetic/optimization)
   - ⚙️ BUILD/TEST (development tools)

---

**Last Review:** 2024-11-28
**Next Review:** After Session 2 completion
