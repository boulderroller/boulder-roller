# Worker 4: DevOps Engineer - START HERE

## Your Role
You are the DevOps/Infrastructure Engineer for Boulder Rollers V2.

## Your Mission
Provision development infrastructure, deploy the backend API, and set up CI/CD pipelines.

---

## MVP SCOPE - What to Focus On

Focus on development environment only:
- ✅ Dev droplet (1 server, 4GB RAM)
- ✅ Load balancer
- ✅ PostgreSQL database (Supabase or DigitalOcean managed)
- ✅ Backend API deployment
- ✅ GitHub Actions CI/CD pipelines
- ✅ Basic monitoring (DigitalOcean monitoring or simple Prometheus)

You do NOT need to provision:
- ❌ Production environment (that's post-MVP)
- ❌ Multiple availability zones
- ❌ Advanced monitoring (Grafana dashboards, Loki logging)
- ❌ CDN or edge caching
- ❌ Redis (not used yet)

---

## Quick Start - Your First 3 Tasks

### Task 1: Read Your Documentation (10 minutes)
1. Read `/docs/WORKER_4_DEVOPS.md` - Your detailed task breakdown
2. Read `/docs/INTEGRATION_REGISTRY.md` - Coordination document (UPDATE THIS as you work)
3. Review infrastructure code: `/infrastructure/terraform/dev/`

### Task 2: Gather Prerequisites (30 minutes)
```bash
# Install tools if not present
brew install terraform
brew install doctl  # DigitalOcean CLI

# Get DigitalOcean API token
# Go to: https://cloud.digitalocean.com/account/api/tokens
# Generate New Token → Name: "BoulderRollers Terraform" → Read + Write
# Copy token (you won't see it again)

# Authenticate doctl
doctl auth init
# Paste your API token

# Get SSH key ID
doctl compute ssh-key list
# Note the numeric ID

# If no SSH key exists:
ssh-keygen -t ed25519 -C "your-email@example.com"
doctl compute ssh-key import boulder-key --public-key-file ~/.ssh/id_ed25519.pub
```

### Task 3: Configure Terraform Variables (15 minutes)
```bash
cd /Users/gabetemp/curahee/BoulderRollers-v2/infrastructure/terraform/dev

# Create terraform.tfvars (NOT committed to git)
cat > terraform.tfvars <<EOF
do_token = "[REDACTED_DO_TOKEN]"
ssh_key_ids = [YOUR_SSH_KEY_ID]
region = "nyc3"
vpc_cidr = "10.0.0.0/16"
domain = ""  # Leave empty for dev, or set if you have one

# Database options
enable_database = false  # Use false if using Supabase, true for DO managed DB
enable_redis = false     # Not needed for MVP
EOF

# Verify file created
cat terraform.tfvars
```

---

## Your Complete Task List

### Phase 1: Infrastructure Provisioning (Day 1)

**Priority 1 - Provision Resources**:
1. Configure Terraform variables (terraform.tfvars)
2. Initialize Terraform: `terraform init`
3. Plan infrastructure: `terraform plan`
4. Review plan output carefully
5. Apply infrastructure: `terraform apply`
6. Save outputs: `terraform output > outputs.txt`
7. Verify resources in DigitalOcean console

**Priority 2 - Database Setup**:
8. OPTION A: Use Supabase (recommended for speed)
   - Create project at https://supabase.com
   - Get connection string from Settings → Database
   - Enable PostGIS extension
9. OPTION B: Use DO Managed PostgreSQL
   - Set `enable_database = true` in terraform.tfvars
   - Get connection string from terraform output
10. Update integration registry with database URL

### Phase 2: Backend Deployment (Days 2-3)

**Priority 3 - Deploy Backend API**:
11. SSH into dev droplet: `ssh root@[DROPLET_IP]`
12. Clone repository on droplet
13. Set up environment variables (.env file)
14. Pull Worker 2's backend code (or build from source)
15. Deploy backend via Docker:
    ```bash
    cd /root/boulder-repo/backend
    docker build -t boulder-api:dev .
    docker run -d --name boulder-api --restart unless-stopped \
      -p 8080:8080 --env-file .env boulder-api:dev
    ```
16. Verify health check: `curl http://localhost:8080/health/db`
17. Configure load balancer health checks
18. Test from external IP: `curl http://[LB_IP]/health/db`

**Priority 4 - DNS & SSL (Optional for MVP)**:
19. If domain available: Configure A record to load balancer IP
20. If SSL needed: Set up Let's Encrypt via certbot
21. Otherwise: Use IP address for dev (Workers 2&3 will use IP)

### Phase 3: CI/CD Setup (Days 3-4)

**Priority 5 - GitHub Actions**:
22. Add GitHub secrets (repo Settings → Secrets):
    - `DO_TOKEN` - DigitalOcean API token
    - `DO_SSH_KEY` - Private SSH key for deployment
    - `DEV_DROPLET_IP` - Your droplet IP
    - `DATABASE_URL` - Database connection string
23. Test backend CI/CD pipeline:
    - Make small change to backend
    - Push to GitHub
    - Verify workflow runs and deploys
24. Test Solana CI/CD pipeline:
    - Verify it builds and tests Anchor programs
25. Update iOS CI/CD to just build (no deployment yet)

**Priority 6 - Monitoring**:
26. Enable DigitalOcean monitoring on droplet
27. Set up alerts for:
    - Droplet CPU > 80%
    - Droplet disk > 90%
    - Load balancer health checks failing
28. Optional: Deploy simple Prometheus/Grafana

---

## Success Criteria

By end of your work, you should have:
- [ ] Dev droplet provisioned (4GB RAM, 2 vCPUs)
- [ ] Load balancer configured with health checks
- [ ] Database provisioned (Supabase or DO managed)
- [ ] Backend API deployed and running
- [ ] Health checks returning 200 OK
- [ ] API accessible from public internet
- [ ] GitHub Actions CI/CD pipelines functional
- [ ] Monitoring/alerts configured
- [ ] Integration registry updated with all URLs and IPs

---

## Coordination with Other Workers

### You UNBLOCK these workers:
- **Worker 2 (Backend)**: Needs your droplet IP and database URL
- **Worker 3 (iOS)**: Needs your load balancer IP/URL to connect to API

### Your Integration Registry Updates:
Update `/docs/INTEGRATION_REGISTRY.md`:

```markdown
## Infrastructure (Worker 4)

### Provisioned Resources
- **Dev Droplet IP**: `123.45.67.89` ← YOUR UPDATE
- **Load Balancer IP**: `234.56.78.90` ← YOUR UPDATE
- **Database URL**: `postgresql://...` ← YOUR UPDATE

### API Endpoints
- **Dev API URL**: `http://234.56.78.90:8080` ← YOUR UPDATE
  (or `https://dev-api.boulderrollers.com` if domain configured)

### Current Status
- Infrastructure provisioned: ✅ ← YOUR UPDATE
- Backend deployed: ✅ ← YOUR UPDATE
- CI/CD configured: ✅ ← YOUR UPDATE
- Health checks passing: ✅ ← YOUR UPDATE
```

Commit with: `git commit -m "chore(integration): Worker 4 - infrastructure live"`

---

## Key Commands Reference

### Terraform
```bash
cd infrastructure/terraform/dev

# Initialize
terraform init

# Plan (preview changes)
terraform plan

# Apply (create resources)
terraform apply

# Get outputs
terraform output
terraform output -raw api_droplet_ips

# Destroy (if needed)
terraform destroy
```

### DigitalOcean CLI
```bash
# List droplets
doctl compute droplet list

# List load balancers
doctl compute load-balancer list

# Get droplet info
doctl compute droplet get [DROPLET_ID]

# SSH directly
doctl compute ssh [DROPLET_NAME]
```

### Docker Deployment
```bash
# SSH to droplet
ssh root@[DROPLET_IP]

# Check if Docker running
docker --version
docker ps

# Pull/build/run backend
cd /root/boulder-repo/backend
git pull
docker build -t boulder-api:dev .
docker stop boulder-api || true
docker rm boulder-api || true
docker run -d --name boulder-api --restart unless-stopped \
  -p 8080:8080 \
  --env-file /root/.env.api \
  boulder-api:dev

# View logs
docker logs -f boulder-api

# Check health
curl http://localhost:8080/health/db
```

### GitHub Actions Secrets
```bash
# In GitHub repo:
# Settings → Secrets and variables → Actions → New repository secret

# Add these:
DO_TOKEN: [your DigitalOcean API token]
DO_SSH_KEY: [contents of ~/.ssh/id_ed25519 - private key]
DEV_DROPLET_IP: [your droplet IP]
DATABASE_URL: [your database connection string]
BOULDER_ROLLERS_PROGRAM_ID: [from Worker 1 - or placeholder]
DUNG_MINT_PROGRAM_ID: [from Worker 1 - or placeholder]
JWT_SECRET: [generate with: openssl rand -hex 32]
```

---

## Environment Variables for Backend

Create `/root/.env.api` on droplet:

```bash
# Database
DATABASE_URL=postgresql://postgres:password@db.xxx.supabase.co:5432/postgres

# Authentication
JWT_SECRET=your-secret-here-generate-with-openssl-rand-hex-32

# Solana (placeholders until Worker 1 deploys)
SOLANA_RPC_URL=https://api.devnet.solana.com
BOULDER_ROLLERS_PROGRAM_ID=11111111111111111111111111111111
DUNG_MINT_PROGRAM_ID=11111111111111111111111111111111
PROOF_VERIFIER_PROGRAM_ID=11111111111111111111111111111111
DUNG_MINT_ADDRESS=11111111111111111111111111111111

# App config
ENVIRONMENT=dev
LOG_LEVEL=info
```

Update program IDs once Worker 1 publishes them!

---

## Terraform Modules Structure

```
infrastructure/terraform/
├── dev/
│   ├── main.tf          # Module instantiation
│   ├── terraform.tfvars # YOUR CONFIG (not in git)
│   └── outputs.tf       # What to output
├── prod/
│   └── ...              # (not needed for MVP)
└── modules/
    ├── api/             # API server module
    ├── database/        # Database module
    └── networking/      # VPC/firewall module
```

---

## Health Check Configuration

### Load Balancer Health Check Settings
```
Protocol: HTTP
Port: 8080
Path: /health/db
Interval: 10 seconds
Timeout: 5 seconds
Healthy threshold: 3
Unhealthy threshold: 3
```

### Expected Response
```bash
curl http://[LB_IP]:8080/health/db
# Should return:
{"status":"healthy"}
```

If unhealthy:
- Check backend logs: `docker logs boulder-api`
- Verify database connection
- Check environment variables
- Test from inside droplet: `curl localhost:8080/health/db`

---

## Monitoring Setup

### DigitalOcean Built-in Monitoring
```bash
# Enable on droplet (automatic with recent droplets)
# View in DO console:
# Droplets → [Your Droplet] → Graphs tab

# Metrics available:
- CPU usage
- Memory usage
- Disk usage
- Bandwidth
- Disk I/O
```

### Set Up Alerts
```bash
# In DO console:
# Manage → Alerts
# Create Alert → Droplet
# Conditions:
- CPU > 80% for 5 minutes → Email alert
- Disk > 90% → Email alert
- Load balancer health check failing → Email alert
```

### Optional: Prometheus + Grafana
```bash
# On droplet:
docker run -d --name prometheus \
  -p 9090:9090 \
  -v /root/prometheus.yml:/etc/prometheus/prometheus.yml \
  prom/prometheus

docker run -d --name grafana \
  -p 3000:3000 \
  grafana/grafana-oss

# Access:
# Prometheus: http://[DROPLET_IP]:9090
# Grafana: http://[DROPLET_IP]:3000 (admin/admin)
```

---

## Troubleshooting Common Issues

### Issue: Terraform times out creating load balancer
**Solution**:
- Check DO account limits
- Verify droplets are healthy
- Increase timeout in terraform config

### Issue: Health checks failing
**Solution**:
- SSH to droplet
- Check if Docker container running: `docker ps`
- Check backend logs: `docker logs boulder-api`
- Test endpoint locally: `curl localhost:8080/health/db`
- Verify database connection in .env file

### Issue: Can't SSH into droplet
**Solution**:
- Verify SSH key ID in terraform.tfvars is correct
- Check DO firewall rules
- Use DO console's recovery console as backup

### Issue: GitHub Actions failing
**Solution**:
- Check secrets are set correctly
- Verify SSH key has correct permissions
- Test SSH manually: `ssh root@[DROPLET_IP]`
- Check workflow logs in GitHub Actions tab

---

## Need Help?

### Documentation Resources:
- Terraform DO Provider: https://registry.terraform.io/providers/digitalocean/digitalocean/latest/docs
- DigitalOcean Docs: https://docs.digitalocean.com/
- Docker Docs: https://docs.docker.com/
- GitHub Actions: https://docs.github.com/en/actions

### Debug Commands:
```bash
# Check droplet status
doctl compute droplet list

# View load balancer
doctl compute load-balancer list

# SSH and check services
ssh root@[IP]
docker ps
docker logs boulder-api
systemctl status docker

# Test health endpoint
curl -v http://[IP]:8080/health/db
```

---

## Communication Protocol

**Daily Update** - Post to integration registry:
```
Worker 4 Status:
✅ Completed: [list]
⏳ In Progress: [current task]
❌ Blocked By: [issues]
📊 Resources: Droplet IP: X.X.X.X, LB IP: Y.Y.Y.Y
```

**When infrastructure is live** - Alert in integration registry:
```
🚨 WORKER 4: Infrastructure live!
- Droplet IP: 123.45.67.89
- Load Balancer: 234.56.78.90
- API URL: http://234.56.78.90:8080
- Workers 2&3 can now deploy/test against this URL
```

---

**Ready? Start with Task 1: Read your documentation. Good luck! 🚀**
