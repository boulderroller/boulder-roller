# CI/CD Secrets Configuration Guide

**Date:** 2024-11-28  
**Purpose:** Configure GitHub Actions secrets for automated deployment

---

## Overview

GitHub Actions workflows require sensitive credentials (API tokens, database URLs, etc.) to deploy and test the application. These are stored as **repository secrets** and accessed as environment variables in workflows.

Do not paste raw secret values into this guide. Use the active secret manager,
GitHub repository secrets, and the staging droplet `.env` as the operational
records. Rotate credentials when there is confirmed exposure, a broad trust
boundary compromise, or a concrete operational reason; otherwise update
inventory and access controls without doing rotation theater.

### Operational source of truth

The provider dashboard is authoritative for whether a credential is active.
GitHub repository secrets hold the CI copy, and `/root/boulder-repo/.env` on
the production host holds the deployed backend copy until the managed-secrets
work is complete. A developer `.env` is only a local convenience copy; it is
not the inventory or the recovery record.

| Credential | Runtime name | Active consumers | Rotate when |
|---|---|---|---|
| Supabase server API key | `SUPABASE_SERVICE_KEY` | Backend API, CI, backend maintenance tools | Confirmed exposure, provider revocation, or access-boundary change |
| Strava OAuth client secret | `STRAVA_CLIENT_SECRET` | Backend API and Strava corpus tools | Confirmed exposure, provider revocation, or ownership change |
| Database password | embedded in `DATABASE_URL` | Backend API, indexer, CI, migrations | Evidence that the database credential itself was exposed or compromised |
| App signing secrets | `JWT_SECRET`, `ACCESS_TOKEN_SECRET`, `REFRESH_TOKEN_SECRET` | Backend authentication | Confirmed exposure or signing-boundary change |
| Privy verification key | `PRIVY_VERIFICATION_KEY` | Backend authentication | Provider revocation or confirmed exposure |
| Deployment/provider tokens | provider-specific names | CI/deployment only | Confirmed exposure, owner removal, or scope reduction |

Review this inventory quarterly for ownership, scope, and unused credentials.
That review does not require blind quarterly rotation.

`STRAVA_CLIENT_SECRET` is runtime-only today. Do not copy it into GitHub
Actions unless a workflow is added that actually consumes it.

---

## Required Secrets

### 1. DigitalOcean Token
**Secret Name:** `DO_TOKEN`  
**Value:** Your DigitalOcean API token (starts with `dop_v1_...`)  
**Used By:** Backend CI/CD, Infrastructure deployment  
**Permissions:** Read + Write

**How to Add:**
1. Go to GitHub repo: Settings → Secrets and variables → Actions
2. Click "New repository secret"
3. Name: `DO_TOKEN`
4. Value: your current DigitalOcean API token from your secret manager
5. Click "Add secret"

---

### 2. Database URL
**Secret Name:** `DATABASE_URL`  
**Value:** PostgreSQL connection string  
**Used By:** Backend CI/CD, Database migrations  

**Value:**
```
postgresql://postgres:<DB_PASSWORD>@db.qzkqjevawthyboymqrle.supabase.co:5432/postgres
```

**How to Add:**
1. GitHub repo → Settings → Secrets → New repository secret
2. Name: `DATABASE_URL`
3. Value: current connection string from your secret manager
4. Click "Add secret"

---

### 3. Supabase Server API Key
**Secret Name:** `SUPABASE_SERVICE_KEY`
**Value:** Modern Supabase secret key (`sb_secret_...`)
**Used By:** Backend API for admin operations

Use the current server-only secret from the Supabase API Keys page. Never put it
in a browser or other public client, and do not commit it to the repository.

**How to Add:**
1. GitHub repo → Settings → Secrets → New repository secret
2. Name: `SUPABASE_SERVICE_KEY`
3. Value: current Supabase `sb_secret_...` key from the provider dashboard
4. Click "Add secret"

`SUPABASE_SERVICE_ROLE_KEY` is the legacy overlap variable only. Remove it
after every active server consumer is proven on the modern key and the legacy
key has been disabled at Supabase.

---

### 4. JWT Secret
**Secret Name:** `JWT_SECRET`  
**Value:** Random hex string for signing JWT tokens  
**Used By:** Backend API authentication

**Generate New Value:**
```bash
openssl rand -hex 32
```

**Use:** the current backend JWT signing secret from your secret manager. Do not copy literal secrets into this document.

**How to Add:**
1. GitHub repo → Settings → Secrets → New repository secret
2. Name: `JWT_SECRET`
3. Value: current backend JWT signing secret from your secret manager
4. Click "Add secret"

---

### 5. Solana Program IDs
**Secret Names:**
- `BOULDER_ROLLERS_PROGRAM_ID`
- `CAL_MINT_ADDRESS`
- `DUNG_MINT_ADDRESS`

**Values:**
```
BOULDER_ROLLERS_PROGRAM_ID=EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH
CAL_MINT_ADDRESS=4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh
DUNG_MINT_ADDRESS=CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk
```

Legacy `DUNG_MINT_PROGRAM_ID` and `PROOF_VERIFIER_PROGRAM_ID` are archived and are no longer required for the fresh-lane `boulder_rollers` devnet deployment.

**How to Add (for each):**
1. GitHub repo → Settings → Secrets → New repository secret
2. Name: (use exact name above)
3. Value: (paste program ID)
4. Click "Add secret"

---

### 6. Droplet SSH Key (Optional for deployment)
**Secret Name:** `DROPLET_SSH_KEY`  
**Value:** Private SSH key for accessing droplet  
**Used By:** Backend deployment workflow

**Value:**
```
# Deploy-only private key from the active secret manager
# DO NOT share publicly - only add to GitHub secrets
```

**How to Get:**
```bash
# Prefer a deploy-only key stored in the active secret manager.
# Do not paste a personal SSH key into docs, chat, or tickets.
```

**How to Add:**
1. GitHub repo → Settings → Secrets → New repository secret
2. Name: `DROPLET_SSH_KEY`
3. Value: deploy-only private key from your secret manager
4. Click "Add secret"

---

### 7. Droplet IP Address
**Secret Name:** `DROPLET_IP`  
**Value:** Public IP of API server droplet  
**Used By:** Backend deployment workflow

**Value:**
```
[STAGING_IP]
```

**How to Add:**
1. GitHub repo → Settings → Secrets → New repository secret
2. Name: `DROPLET_IP`
3. Value: `[STAGING_IP]`
4. Click "Add secret"

---

### 8. Droplet Host Keys
**Variable Name:** `DROPLET_KNOWN_HOSTS` (a repository variable, not a secret: host keys are public)\
**Value:** The droplet's SSH host keys as known_hosts lines under the alias `droplet`\
**Used By:** Backend deployment workflow, which refuses any host that does not present one of these keys

**How to Get:**
Read the keys on the droplet itself, over a connection you already trust (an
existing known_hosts entry, or the DigitalOcean droplet console for a new
droplet). Never take them from an unauthenticated `ssh-keyscan`.
```bash
ssh root@<droplet> 'cat /etc/ssh/ssh_host_*_key.pub' | awk '{print "droplet", $1, $2}'
```

**How to Add:**
1. GitHub repo → Settings → Secrets and variables → Actions → Variables → New repository variable
2. Name: `DROPLET_KNOWN_HOSTS`
3. Value: the lines printed above
4. Click "Add variable"

Rebuilding or replacing the droplet changes its host keys, and deploys then
fail host-key verification until this variable holds the new ones.

---

## Optional Secrets (For Production)

### 9. Docker Hub Token (If using Docker Hub)
**Secret Name:** `DOCKER_USERNAME` and `DOCKER_TOKEN`  
**Used By:** Docker image push to registry

### 10. Sentry DSN (Error tracking)
**Secret Name:** `SENTRY_DSN`  
**Used By:** Backend error reporting

### 11. Slack Webhook (Notifications)
**Secret Name:** `SLACK_WEBHOOK_URL`  
**Used By:** Deployment notifications

---

## Verification Checklist

After adding secrets, verify:

- [ ] `DO_TOKEN` - Added with correct value
- [ ] `DATABASE_URL` - Added with correct connection string
- [ ] `SUPABASE_SERVICE_KEY` - Added with current server-only key
- [ ] `JWT_SECRET` - Added with secure random value
- [ ] `BOULDER_ROLLERS_PROGRAM_ID` - Added with correct program ID
- [ ] `DUNG_MINT_PROGRAM_ID` - Added with correct program ID
- [ ] `PROOF_VERIFIER_PROGRAM_ID` - Added with correct program ID
- [ ] `DUNG_MINT_ADDRESS` - Added with correct mint address
- [ ] `DROPLET_SSH_KEY` - Added with private key (optional)
- [ ] `DROPLET_IP` - Added with droplet IP (optional)
- [ ] `DROPLET_KNOWN_HOSTS` - Repository variable with the droplet's host keys (needed with the two above)

---

## Using Secrets in Workflows

**Example: Backend CI Workflow**

```yaml
name: Backend CI

on:
  push:
    branches: [main]
    paths:
      - 'backend/**'

jobs:
  test:
    runs-on: ubuntu-latest
    
    env:
      DATABASE_URL: ${{ secrets.DATABASE_URL }}
      JWT_SECRET: ${{ secrets.JWT_SECRET }}
      ACCESS_TOKEN_SECRET: ${{ secrets.JWT_SECRET }}
      REFRESH_TOKEN_SECRET: ${{ secrets.JWT_SECRET }}
      SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
      SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
      SOLANA_RPC_URL: https://api.devnet.solana.com
      BOULDER_ROLLERS_PROGRAM_ID: ${{ secrets.BOULDER_ROLLERS_PROGRAM_ID }}
      DUNG_MINT_PROGRAM_ID: ${{ secrets.DUNG_MINT_PROGRAM_ID }}
      PROOF_VERIFIER_PROGRAM_ID: ${{ secrets.PROOF_VERIFIER_PROGRAM_ID }}
      DUNG_MINT_ADDRESS: ${{ secrets.DUNG_MINT_ADDRESS }}
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          cd backend
          pip install -r requirements.txt
      
      - name: Run tests
        run: |
          cd backend
          pytest -v
```

**Deployment Step**

The `deploy` job in `.github/workflows/backend-ci.yml` runs on pushes to main.
It writes `DROPLET_SSH_KEY` to a 0600 file and runs the release over the
runner's own OpenSSH client with `StrictHostKeyChecking=yes` against
`DROPLET_KNOWN_HOSTS` alone, so no third-party action or downloaded binary
handles the key, and a host that cannot present a pinned key is refused.

---

## Security Best Practices

1. **Never commit secrets to git**
   - Use .gitignore for .env files
   - Use .gitignore for terraform.tfvars
   - Use GitHub secrets for CI/CD

2. **Rotate secrets deliberately**
   - Rotate immediately on confirmed exposure or suspected credential theft
   - Rotate broad-blast-radius credentials after a trusted deploy path compromise
   - Avoid routine rotation that only creates outage risk without reducing an actual exposure
   - Use an overlap-first cutover when the provider supports it: install and prove the replacement before revoking the old credential

3. **Use least privilege**
   - Give CI/CD only required permissions
   - Use separate tokens for dev/staging/prod
   - Limit token scopes when possible

4. **Monitor secret usage**
   - Review GitHub Actions logs
   - Check for failed authentication attempts
   - Audit secret access patterns

5. **Have a breach response plan**
   - Document how to rotate all secrets
   - Know which secrets to rotate first (API tokens)
   - Test secret rotation procedure

---

## Troubleshooting

### Workflow fails with "secret not found"
- Verify secret name matches exactly (case-sensitive)
- Check secret was added at repository level (not organization or environment)
- Verify you have admin access to the repository

### Workflow succeeds but deployment fails
- Check secret values are correct (no extra spaces/newlines)
- Verify secrets haven't expired (API tokens, JWT)
- Check droplet is accessible from GitHub Actions IPs

### Deploy fails with "Host key verification failed"
- The droplet's host keys no longer match `DROPLET_KNOWN_HOSTS`, usually after a rebuild
- Confirm the new keys over a trusted path (section 8), then update the variable; never switch off strict checking

### Database connection fails
- Verify DATABASE_URL format is correct
- Check database allows connections from GitHub Actions IPs
- Test connection string locally first

---

## Quick Setup Script

Run this script to check which secrets still need to be added:

```bash
#!/bin/bash

REPO="your-username/BoulderRollers-v2"

echo "Checking GitHub secrets for $REPO..."

# List of required secrets
REQUIRED_SECRETS=(
  "DO_TOKEN"
  "DATABASE_URL"
  "SUPABASE_SERVICE_KEY"
  "JWT_SECRET"
  "BOULDER_ROLLERS_PROGRAM_ID"
  "DUNG_MINT_PROGRAM_ID"
  "PROOF_VERIFIER_PROGRAM_ID"
  "DUNG_MINT_ADDRESS"
)

# Check which secrets exist (requires GitHub CLI)
for secret in "${REQUIRED_SECRETS[@]}"; do
  if gh secret list -R $REPO | grep -q "$secret"; then
    echo "✅ $secret"
  else
    echo "❌ $secret - MISSING"
  fi
done
```

---

## Next Steps

1. Add all required secrets to GitHub repository
2. Test backend-ci.yml workflow
3. Test solana-ci.yml workflow
4. Enable deployment on main branch merge
5. Monitor first automated deployment

---

**Document Status:** Ready for Use  
**Last Updated:** 2024-11-28
