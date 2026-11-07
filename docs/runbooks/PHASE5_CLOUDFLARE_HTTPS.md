# Phase 5: Cloudflare HTTPS Setup

## Worker Prompt

```
You are a DevOps engineer setting up HTTPS via Cloudflare for Boulder Rollers API.

## Context
- Backend runs at: STAGING_IP:8080 (HTTP)
- Domain needed: api.boulderrollers.com
- Goal: HTTPS without modifying server nginx/certs

## Prerequisites (Manual - User Must Do)
1. Cloudflare account created
2. Domain `boulderrollers.com` added to Cloudflare
3. Nameservers updated at registrar to Cloudflare's
4. DNS propagation complete

## Tasks (After Prerequisites Done)

### TASK 1: Verify Cloudflare DNS
User should have created:
- A record: `api` → `STAGING_IP` (Proxied/Orange cloud)

Test:
```bash
dig api.boulderrollers.com
# Should resolve to Cloudflare IP (not STAGING_IP directly)
```

### TASK 2: Update iOS API Client
**File:** `ios/BoulderRollers/Services/APIClient.swift`

Replace the baseURL initialization with:
```swift
#if DEBUG
baseURL = ProcessInfo.processInfo.environment["BR_API_URL"] ?? "http://STAGING_IP:8080"
#else
baseURL = "https://api.boulderrollers.com"
#endif
```

### TASK 3: Update Web API Client
**File:** `web/portal/src/lib/api.ts`

Change fallback URL:
```typescript
private baseURL = process.env.NEXT_PUBLIC_API_URL || 'https://api.boulderrollers.com';
```

### TASK 4: Update Vercel Environment
Either via Vercel dashboard or create `.env.production`:
```
NEXT_PUBLIC_API_URL=https://api.boulderrollers.com
```

### TASK 5: Clean Up Stale IP References
Search and replace all hardcoded IPs:
```bash
grep -rn "STAGING_LB_IP" . --include="*.swift" --include="*.ts" --include="*.tsx"
grep -rn "STAGING_IP" . --include="*.swift" --include="*.ts" --include="*.tsx"
```

Replace any remaining IPs with `https://api.boulderrollers.com`

### TASK 6: Verify Builds
```bash
# iOS
cd ios && xcodebuild -scheme BoulderRollers -destination 'platform=iOS Simulator,name=iPhone 17 Pro' build

# Web
cd web/portal && npm run build
```

### TASK 7: Test HTTPS
```bash
curl https://api.boulderrollers.com/health
# Should return 200

# Verify SSL cert
openssl s_client -connect api.boulderrollers.com:443 -servername api.boulderrollers.com < /dev/null 2>/dev/null | openssl x509 -noout -issuer
# Should show Cloudflare
```

### TASK 8: Commit & Push
```bash
git add -A
git commit -m "feat: Switch to HTTPS via Cloudflare

- Update iOS/Web API URLs to https://api.boulderrollers.com
- Remove all hardcoded IP addresses
- Debug builds still use direct IP for local testing

🤖 Generated with Claude Code"
git push
```

## Success Criteria
1. `https://api.boulderrollers.com/health` returns 200
2. iOS release build uses HTTPS domain
3. Web production uses HTTPS domain
4. No hardcoded IPs remain in codebase
5. Both builds pass
```

---

## Why Cloudflare?

| Benefit | Description |
|---------|-------------|
| Free SSL/TLS | Automatic certificate provisioning |
| DDoS Protection | Built-in attack mitigation |
| CDN/Caching | Global edge network |
| No Server Changes | Backend stays HTTP, Cloudflare handles HTTPS |

---

## Manual Prerequisites (Before Running Subagent)

### Step 1: Create Cloudflare Account
1. Go to https://dash.cloudflare.com/sign-up
2. Create free account

### Step 2: Add Domain to Cloudflare
1. Click "Add site"
2. Enter: `boulderrollers.com`
3. Select **Free** plan
4. Cloudflare scans existing DNS records

### Step 3: Update Nameservers
Cloudflare will provide 2 nameservers like:
```
ada.ns.cloudflare.com
bob.ns.cloudflare.com
```

Go to your domain registrar (GoDaddy, Namecheap, etc.) and update nameservers.

**Propagation:** Usually 5-30 minutes, can take up to 24 hours.

### Step 4: Create DNS A Record
In Cloudflare DNS dashboard:

| Type | Name | Content | Proxy | TTL |
|------|------|---------|-------|-----|
| A | api | STAGING_IP | Proxied (orange) | Auto |

### Step 5: Configure SSL/TLS
In Cloudflare → SSL/TLS → Overview:
- **Encryption mode:** Full (NOT Full Strict)

In SSL/TLS → Edge Certificates:
- **Always Use HTTPS:** ON
- **Automatic HTTPS Rewrites:** ON
- **Minimum TLS Version:** 1.2

### Step 6: Verify Setup
```bash
# Check DNS resolves to Cloudflare
dig api.boulderrollers.com
# Should show Cloudflare IP, NOT STAGING_IP

# Test HTTPS
curl -I https://api.boulderrollers.com/health
# Should return 200
```

---

## Cloudflare Page Rules (Optional)

For API-specific settings, create a page rule:

**URL:** `api.boulderrollers.com/*`

| Setting | Value |
|---------|-------|
| Cache Level | Bypass |
| SSL | Full |
| Browser Cache TTL | Respect Existing Headers |

---

## Security Settings

In Cloudflare → Security:

| Setting | Recommended Value |
|---------|------------------|
| Security Level | Medium |
| Bot Fight Mode | OFF (API needs bot access) |
| Challenge Passage | 30 minutes |

---

## File Paths to Modify

| File | Change |
|------|--------|
| `ios/BoulderRollers/Services/APIClient.swift` | Add #if DEBUG for URL |
| `web/portal/src/lib/api.ts` | Change fallback to HTTPS domain |
| Vercel Dashboard | Set NEXT_PUBLIC_API_URL env var |

---

## Rollback Plan

If issues occur:
1. In Cloudflare DNS, change `api` A record proxy status to "DNS only" (grey cloud)
2. This bypasses Cloudflare and goes direct to server
3. Revert code changes to use HTTP IP

---

## Troubleshooting

### 522 Connection Timed Out
- Server firewall blocking Cloudflare IPs
- Fix: Allow Cloudflare IP ranges at https://cloudflare.com/ips

### 525 SSL Handshake Failed
- SSL mode set to "Full (Strict)" but server has no valid cert
- Fix: Change SSL mode to "Full" (not strict)

### Mixed Content Warnings
- Some resources still using HTTP
- Fix: Run grep to find and replace all HTTP URLs

### CORS Errors
- Backend not allowing Cloudflare domain
- Fix: Add `api.boulderrollers.com` to CORS allowed origins
