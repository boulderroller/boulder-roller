# 🚨 USER ACTION REQUIRED - Complete Before Next Session

**Date Created:** 2024-11-28
**Status:** BLOCKING - Workers cannot proceed without these

---

## ✅ Quick Checklist

Before resuming the Codex workers, you must complete:

- [ ] Sign up for DigitalOcean
- [ ] Generate DO API token
- [ ] Install Homebrew tools (terraform, doctl)
- [ ] Generate SSH key
- [ ] Upload SSH key to DigitalOcean
- [ ] Note SSH key ID
- [ ] Create Xcode project manually
- [ ] (Optional) Sign up for Mapbox
- [ ] (Optional) Create Supabase project

---

## 🔴 CRITICAL - Required for All Deployment

### 1. DigitalOcean Account Setup

**Why:** Worker 4 needs this to provision dev server infrastructure
**Cost:** ~$50-70/month for dev environment
**Time:** 10 minutes

**Steps:**

```bash
# 1. Sign up
# Go to: https://cloud.digitalocean.com
# Click "Sign Up" → Create account → Verify email

# 2. Add billing info
# Dashboard → Account → Billing → Add Payment Method
# (You won't be charged until resources are provisioned)

# 3. Generate API Token
# Dashboard → API → Tokens/Keys → Generate New Token
# Name: "BoulderRollers Terraform"
# Scopes: ✅ Read ✅ Write
# Click "Generate Token"

# 4. SAVE THE TOKEN IMMEDIATELY
# It will look like: [REDACTED_DO_TOKEN]...
# Store it securely - you can't see it again!

# Copy it here for reference:
export DO_TOKEN="[REDACTED-DO-TOKEN]"
```

**Where to use it:**
- `infrastructure/terraform/dev/terraform.tfvars` → `do_token = "..."`
- GitHub Actions secrets (for CI/CD later)

---

### 2. Install Development Tools

**Why:** Worker 4 needs these to run Terraform
**Time:** 5 minutes

```bash
# Check if Homebrew is installed
brew --version
# If not installed: /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Terraform (Infrastructure as Code tool)
brew install terraform

# Verify installation
terraform --version
# Should show: Terraform v1.6.x or higher

# Install doctl (DigitalOcean CLI)
brew install doctl

# Verify installation
doctl version
# Should show: doctl version 1.x.x

# Authenticate doctl with your token
doctl auth init
# Paste your DO token when prompted
```

---

### 3. SSH Key Setup

**Why:** Terraform needs SSH access to provisioned servers
**Time:** 5 minutes

```bash
# 1. Generate SSH key (if you don't have one)
ssh-keygen -t ed25519 -C "your-email@example.com"
# Press Enter to accept default location: ~/.ssh/id_ed25519
# Set a passphrase (or press Enter for none)

# 2. Display your public key
cat ~/.ssh/id_ed25519.pub
# Copy the entire output

"ssh-ed25519 [REDACTED]

# 3. Upload to DigitalOcean
# Go to: https://cloud.digitalocean.com/account/security
# Click "Add SSH Key"
# Paste your public key
# Name it: "BoulderRollers Dev Key"
# Click "Add SSH Key"

# 4. Get your SSH key ID
doctl compute ssh-key list
# Note the numeric ID (first column)

52280993

# Example output:
# ID          Name                    FingerPrint
# 12345678    BoulderRollers Dev Key  xx:xx:xx:...

# Save the ID for terraform.tfvars:
export SSH_KEY_ID=52280993
```

**Where to use it:**
- `infrastructure/terraform/dev/terraform.tfvars` → `ssh_key_ids = [52280993]`

---

## 🟡 IMPORTANT - Required for iOS Testing

### 4. Create Xcode Project

**Why:** Worker 3 cannot build iOS app without .xcodeproj file
**Time:** 10 minutes
**Requires:** macOS with Xcode installed

**Steps:**

```bash
# 1. Open Xcode
open -a Xcode

# 2. Create New Project
# File → New → Project
# iOS → App
# Click "Next"

# 3. Project Settings:
# Product Name: BoulderRollers
# Team: (Your Apple Developer account, or "None" for now)
# Organization Identifier: com.boulderrollers
# Bundle Identifier: com.boulderrollers.app
# Interface: SwiftUI
# Language: Swift
# Storage: None
# Click "Next"

# 4. Save Location
# Navigate to: /Users/gabetemp/curahee/BoulderRollers-v2/ios/
# Click "Create"

# 5. Add Existing Files
# In Xcode navigator, select "BoulderRollers" folder
# Right-click → Add Files to "BoulderRollers"
# Select these folders:
#   - Services/
#   - Views/
#   - ViewModels/
#   - Utilities/
# Check: ✅ Copy items if needed
# Check: ✅ Create groups
# Add to targets: BoulderRollers
# Click "Add"

# 6. Add Swift Package Dependencies
# File → Add Package Dependencies
# Add these URLs one by one:
#   1. https://github.com/portto/solana-web3.swift
#      Version: 1.0.0 or latest
#   2. https://github.com/onevcat/Kingfisher
#      Version: 7.10.0 or latest
#   3. https://github.com/mapbox/mapbox-maps-ios (OPTIONAL)
#      Version: 10.18.0 or latest

# 7. Build to Test
# Product → Build (Cmd+B)
# Fix any import errors or missing files
```

**Common Issues:**
- If Solana import fails: Make sure Solana.swift package was added
- If KeychainHelper errors: Make sure Utilities/ folder was added
- If SwiftUI previews don't work: That's normal, they'll work after first build

---

## 🟢 OPTIONAL - Enhances Features

### 5. Mapbox Account (Optional Maps)

**Why:** Enables map view in iOS app (otherwise shows placeholder)
**Cost:** Free tier includes 50,000 map loads/month
**Time:** 5 minutes

```bash
# 1. Sign up
# Go to: https://account.mapbox.com/
# Click "Sign up" → Create account → Verify email

# 2. Get Access Token
# Dashboard → Tokens → Default public token
# Copy the token (starts with: pk.eyJ...)

[MAPBOX_TOKEN]

# 3. Add to iOS Info.plist
# In Xcode, select Info.plist
# Right-click → Add Row
# Key: MBXAccessToken
# Type: String
# Value: pk.eyJ... (paste your token)
```

**Where to use it:**
- `ios/BoulderRollers/Info.plist` → `<key>MBXAccessToken</key>`

---

### 6. Supabase Database (Optional Alternative)

**Why:** Faster setup than DO Managed DB, includes PostGIS
**Cost:** Free tier includes 500MB database + 2GB transfer/month
**Time:** 5 minutes

```bash
# 1. Sign up
# Go to: https://supabase.com
# Click "Start your project" → Sign up with GitHub

# 2. Create Project
# Dashboard → "New project"
# Name: boulder-rollers-dev
# Database Password: (generate strong password)
# Region: (closest to you)
# Plan: Free
# Click "Create new project"

# 3. Enable PostGIS Extension
# Project → SQL Editor → New query
# Paste and run:
CREATE EXTENSION IF NOT EXISTS postgis;

# 4. Get Connection String
# Project → Settings → Database
# Connection string → URI
# Copy the connection pooling URI:


postgresql://postgres:<DB_PASSWORD>@db.qzkqjevawthyboymqrle.supabase.co:5432/postgres

# 5. Save for backend
export DATABASE_URL="postgresql://postgres:<DB_PASSWORD>@db.qzkqjevawthyboymqrle.supabase.co:5432/postgres"
```

**Where to use it:**
- `backend/.env` → `DATABASE_URL=...`
- OR wait for Worker 4 to provision DO Managed DB

---

## 📝 Configuration Files to Create

### terraform.tfvars

Once you have DO token and SSH key ID, create this file:

```bash
cd /Users/gabetemp/curahee/BoulderRollers-v2/infrastructure/terraform/dev

cat > terraform.tfvars <<EOF
do_token = "[REDACTED_DO_TOKEN]"
ssh_key_ids = [YOUR_SSH_KEY_ID]
region = "nyc3"
vpc_cidr = "10.0.0.0/16"
domain = ""  # Leave empty for dev

enable_database = false  # Set true if NOT using Supabase
enable_redis = false     # Not needed for MVP
EOF

# IMPORTANT: Never commit this file to git!
# It's already in .gitignore
```

---

## ✅ Verification Checklist

Before starting Session 2, verify:

### DigitalOcean Setup
```bash
# Test DO authentication
doctl account get
# Should show your account email

# Test SSH key is uploaded
doctl compute ssh-key list
# Should show your key
```

### Tools Installed
```bash
# Verify terraform
terraform version
# Should show: Terraform v1.6.x

# Verify doctl
doctl version
# Should show: doctl version 1.x.x
```

### SSH Key Accessible
```bash
# Verify key exists
ls -la ~/.ssh/id_ed25519
ls -la ~/.ssh/id_ed25519.pub
# Both should exist
```

### Xcode Project Created
```bash
# Verify project exists
ls -la /Users/gabetemp/curahee/BoulderRollers-v2/ios/BoulderRollers.xcodeproj
# Should show the project file

# Try building (in Xcode)
# Product → Build (Cmd+B)
# Should compile without errors
```

---

## 🎯 What Happens Next

Once you complete these steps:

1. **Notify in Integration Registry**
   - Update `/docs/INTEGRATION_REGISTRY.md`
   - Change Worker 4 status to "Ready to provision"

2. **Resume Codex Workers**
   - Give each worker their Session 2 instructions
   - They'll pick up where they left off
   - Worker 4 will provision infrastructure first
   - Worker 1 will deploy programs to devnet
   - Workers 2 & 3 will integrate and test

3. **Timeline**
   - With all credentials ready: 2-4 hours to working MVP
   - Without credentials: Indefinitely blocked

---

## 🆘 Troubleshooting

### "brew command not found"
```bash
# Install Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### "doctl: command not found after install"
```bash
# Restart terminal
# Or add to PATH manually:
export PATH="/opt/homebrew/bin:$PATH"
```

### "SSH key already exists"
```bash
# Use existing key
cat ~/.ssh/id_ed25519.pub
# Upload this to DigitalOcean
```

### "Xcode command line tools not installed"
```bash
xcode-select --install
```

### "Cannot add Swift packages in Xcode"
```bash
# Make sure Xcode project is open
# Make sure you're connected to internet
# Try: File → Packages → Reset Package Caches
```

---

## 💰 Cost Estimate

**Monthly Recurring:**
- DigitalOcean dev environment: ~$50-70/month
- Supabase (if using free tier): $0
- Mapbox (if using free tier): $0

**One-Time:**
- Solana devnet airdrops: Free
- Development tools: Free (Homebrew, Terraform, doctl)

**Total First Month:** ~$50-70 (DigitalOcean only)

---

## 📞 Need Help?

If you get stuck:

1. **Check integration registry:** `/docs/INTEGRATION_REGISTRY.md`
2. **Check known issues:** `/docs/KNOWN_ISSUES.md` (once created)
3. **Check worker logs:** Review Codex output from Session 1
4. **Contact support:**
   - DigitalOcean: https://www.digitalocean.com/support
   - Supabase: https://supabase.com/support
   - Mapbox: https://support.mapbox.com

---

**Ready?** Complete this checklist, then resume your Codex workers for Session 2! 🚀
