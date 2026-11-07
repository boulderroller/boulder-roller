# Worker 4: DevOps Engineer

**Context:** Read `BOULDER_ROLLERS_V1_SPEC.md` first for full game design.

**Your Responsibility:** Infrastructure, deployment, monitoring, and operations.

**Tech Stack:**
- Cloud: AWS/GCP/DigitalOcean
- Containers: Docker
- CI/CD: GitHub Actions
- Monitoring: Grafana + Prometheus
- Logs: Grafana Loki

**Working Directory:** `/infrastructure/`

---

## Current State (Starting Fresh)

No infrastructure exists. You're building from scratch.

---

## Your 7-Week Plan

### Week 1: Development Environment

#### Task 4.1: Set Up Cloud Provider (Day 1)

**Choose Cloud Provider:**
- **AWS** (battle-tested, expensive)
- **GCP** (good pricing, solid)
- **DigitalOcean** (simple, affordable) ← Recommended for V1

**Create Account:**
```bash
# DigitalOcean
# 1. Sign up at digitalocean.com
# 2. Add payment method
# 3. Generate API token
# 4. Install doctl CLI
brew install doctl
doctl auth init
```

**Create VPC:**
```bash
doctl vpcs create \
  --name boulder-rollers-vpc \
  --region nyc3 \
  --ip-range 10.0.0.0/16
```

---

#### Task 4.2: Provision Dev Environment (Day 2-3)

**Create `infrastructure/terraform/dev/main.tf`:**
```hcl
terraform {
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
  }
}

provider "digitalocean" {
  token = var.do_token
}

# Database
resource "digitalocean_database_cluster" "postgres" {
  name       = "boulder-dev-db"
  engine     = "pg"
  version    = "15"
  size       = "db-s-2vcpu-4gb"
  region     = "nyc3"
  node_count = 1
}

# Redis
resource "digitalocean_database_cluster" "redis" {
  name       = "boulder-dev-redis"
  engine     = "redis"
  version    = "7"
  size       = "db-s-1vcpu-1gb"
  region     = "nyc3"
  node_count = 1
}

# API Server
resource "digitalocean_droplet" "api" {
  image  = "docker-20-04"
  name   = "boulder-dev-api"
  region = "nyc3"
  size   = "s-2vcpu-4gb"
  ssh_keys = [var.ssh_key_id]

  user_data = <<-EOF
    #!/bin/bash
    apt update
    apt install -y docker.io docker-compose
    systemctl enable docker
    systemctl start docker
  EOF
}

# Load Balancer
resource "digitalocean_loadbalancer" "api_lb" {
  name   = "boulder-dev-lb"
  region = "nyc3"

  forwarding_rule {
    entry_protocol  = "https"
    entry_port      = 443
    target_protocol = "http"
    target_port     = 8080
    certificate_name = digitalocean_certificate.api.name
  }

  healthcheck {
    protocol = "http"
    port     = 8080
    path     = "/health"
  }

  droplet_ids = [digitalocean_droplet.api.id]
}

# SSL Certificate
resource "digitalocean_certificate" "api" {
  name    = "dev-api-cert"
  type    = "lets_encrypt"
  domains = ["dev-api.boulderrollers.com"]
}

# Outputs
output "api_server_ip" {
  value = digitalocean_droplet.api.ipv4_address
}

output "load_balancer_ip" {
  value = digitalocean_loadbalancer.api_lb.ip
}

output "database_connection_string" {
  value     = digitalocean_database_cluster.postgres.uri
  sensitive = true
}
```

**Create `infrastructure/terraform/dev/variables.tf`:**
```hcl
variable "do_token" {
  description = "DigitalOcean API token"
  type        = string
  sensitive   = true
}

variable "ssh_key_id" {
  description = "SSH key ID for droplet access"
  type        = string
}
```

**Apply Terraform:**
```bash
cd infrastructure/terraform/dev
terraform init
terraform plan
terraform apply

# Save outputs to .env for Worker 2
terraform output database_connection_string > ../../../backend/.env.dev
```

**Deliverable:** Dev environment live, share URLs with team

---

#### Task 4.3: Set Up DNS (Day 4)

**Configure DNS (Cloudflare):**
```bash
# Add A records:
dev-api.boulderrollers.com → Load Balancer IP
api.boulderrollers.com → (Future prod)

# Enable Cloudflare proxy (orange cloud) for:
# - DDoS protection
# - SSL
# - Caching
```

---

#### Task 4.4: Docker Images (Day 5)

**Create `backend/Dockerfile`:**
```dockerfile
FROM rust:1.75 AS builder

WORKDIR /app

# Copy manifests
COPY Cargo.toml Cargo.lock ./
COPY api ./api
COPY workers ./workers
COPY shared ./shared

# Build for release
RUN cargo build --release --bin boulder-api

# Runtime image
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y \
    libpq5 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/target/release/boulder-api /usr/local/bin/boulder-api

EXPOSE 8080

CMD ["boulder-api"]
```

**Build and push:**
```bash
cd backend
docker build -t boulderrollers/api:dev .

# Push to registry (Docker Hub or DigitalOcean Container Registry)
docker push boulderrollers/api:dev
```

---

### Week 2: Production Environment

#### Task 4.5: Provision Production (Day 1-3)

**Create `infrastructure/terraform/prod/main.tf`:**
```hcl
# Similar to dev, but:
# - 3 API servers (high availability)
# - Database with read replicas
# - Larger instance sizes
# - Multi-region (if needed)

resource "digitalocean_droplet" "api" {
  count  = 3  # ← 3 servers instead of 1
  image  = "docker-20-04"
  name   = "boulder-prod-api-${count.index + 1}"
  region = "nyc3"
  size   = "c-4"  # ← 4 vCPU, 8GB RAM
  ssh_keys = [var.ssh_key_id]
}

resource "digitalocean_database_cluster" "postgres" {
  name       = "boulder-prod-db"
  engine     = "pg"
  version    = "15"
  size       = "db-s-4vcpu-8gb"  # ← Larger
  region     = "nyc3"
  node_count = 2  # ← Primary + replica
}

# Add Redis cluster (3 nodes)
resource "digitalocean_database_cluster" "redis" {
  name       = "boulder-prod-redis"
  engine     = "redis"
  version    = "7"
  size       = "db-s-2vcpu-4gb"
  region     = "nyc3"
  node_count = 2
}
```

---

#### Task 4.6: Set Up Secrets Management (Day 4)

**Option A: Environment Variables (Simple)**
```bash
# Store secrets in /etc/boulder/.env on each server
# Load via systemd or docker-compose

# /etc/boulder/.env
DATABASE_URL=postgresql://...
JWT_SECRET=...
SOLANA_RPC_URL=...
```

**Option B: HashiCorp Vault (Advanced)**
```bash
# Install Vault
docker run -d \
  -p 8200:8200 \
  --name vault \
  vault:1.15

# Initialize and unseal
vault operator init
vault operator unseal
```

---

#### Task 4.7: Backups (Day 5)

**Database Backup Script:**
```bash
#!/bin/bash
# /opt/boulder/scripts/backup-db.sh

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/var/backups/boulder"
DB_NAME="boulder_rollers"

mkdir -p $BACKUP_DIR

# Dump database
pg_dump $DATABASE_URL > $BACKUP_DIR/db_backup_$DATE.sql

# Compress
gzip $BACKUP_DIR/db_backup_$DATE.sql

# Upload to S3/Spaces
aws s3 cp $BACKUP_DIR/db_backup_$DATE.sql.gz s3://boulder-backups/

# Delete local file
rm $BACKUP_DIR/db_backup_$DATE.sql.gz

# Keep only last 7 days of backups in S3
# (Add cleanup script)
```

**Cron Job:**
```bash
# Run daily at 2 AM
0 2 * * * /opt/boulder/scripts/backup-db.sh
```

---

### Week 3: CI/CD Pipeline

#### Task 4.8: GitHub Actions - Backend (Day 1-2)

**Create `.github/workflows/backend-ci.yml`:**
```yaml
name: Backend CI/CD

on:
  push:
    branches: [main]
    paths:
      - 'backend/**'
  pull_request:
    branches: [main]
    paths:
      - 'backend/**'

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Install Rust
        uses: actions-rs/toolchain@v1
        with:
          toolchain: stable

      - name: Run tests
        run: |
          cd backend
          cargo test --all

      - name: Run clippy
        run: |
          cd backend
          cargo clippy -- -D warnings

  build:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Build Docker image
        run: |
          cd backend
          docker build -t boulderrollers/api:${{ github.sha }} .
          docker tag boulderrollers/api:${{ github.sha }} boulderrollers/api:latest

      - name: Push to registry
        run: |
          echo ${{ secrets.DOCKER_PASSWORD }} | docker login -u ${{ secrets.DOCKER_USERNAME }} --password-stdin
          docker push boulderrollers/api:${{ github.sha }}
          docker push boulderrollers/api:latest

  deploy:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to production
        uses: appleboy/ssh-action@master
        with:
          host: ${{ secrets.PROD_SERVER_HOST }}
          username: root
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: |
            cd /opt/boulder
            docker pull boulderrollers/api:latest
            docker-compose up -d
```

---

#### Task 4.9: GitHub Actions - Solana Programs (Day 3)

**Create `.github/workflows/solana-ci.yml`:**
```yaml
name: Solana Programs CI/CD

on:
  push:
    branches: [main]
    paths:
      - 'protocol/anchor/**'
  pull_request:
    branches: [main]
    paths:
      - 'protocol/anchor/**'

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Install Solana
        run: |
          sh -c "$(curl -sSfL https://release.solana.com/v1.18.26/install)"
          echo "$HOME/.local/share/solana/install/active_release/bin" >> $GITHUB_PATH

      - name: Install Anchor
        run: |
          cargo install --git https://github.com/coral-xyz/anchor anchor-cli --locked --force

      - name: Run tests
        run: |
          cd protocol/anchor
          anchor test

  deploy:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Deploy to devnet
        run: |
          cd protocol/anchor
          anchor deploy --provider.cluster devnet --provider.wallet ${{ secrets.SOLANA_DEPLOYER_KEY }}
```

---

#### Task 4.10: iOS CI (Day 4)

**Create `.github/workflows/ios-ci.yml`:**
```yaml
name: iOS CI

on:
  push:
    branches: [main]
    paths:
      - 'ios/**'
  pull_request:
    branches: [main]
    paths:
      - 'ios/**'

jobs:
  build:
    runs-on: macos-13
    steps:
      - uses: actions/checkout@v3

      - name: Select Xcode version
        run: sudo xcode-select -s /Applications/Xcode_15.0.app

      - name: Build
        run: |
          cd ios
          xcodebuild -scheme BoulderRollers -configuration Debug build

      - name: Run tests
        run: |
          cd ios
          xcodebuild test -scheme BoulderRollers -destination 'platform=iOS Simulator,name=iPhone 15'
```

---

#### Task 4.11: Deployment Script (Day 5)

**Create `infrastructure/scripts/deploy.sh`:**
```bash
#!/bin/bash

set -e

ENVIRONMENT=$1
VERSION=$2

if [ -z "$ENVIRONMENT" ] || [ -z "$VERSION" ]; then
    echo "Usage: ./deploy.sh <dev|prod> <version>"
    exit 1
fi

echo "Deploying version $VERSION to $ENVIRONMENT"

# Pull latest image
ssh root@$ENVIRONMENT-api.boulderrollers.com << EOF
    cd /opt/boulder
    docker pull boulderrollers/api:$VERSION
    docker tag boulderrollers/api:$VERSION boulderrollers/api:current
    docker-compose up -d --no-deps api
EOF

# Health check
sleep 10
curl -f https://$ENVIRONMENT-api.boulderrollers.com/health || exit 1

echo "Deployment successful!"
```

---

### Week 4: Monitoring & Logging

#### Task 4.12: Prometheus Setup (Day 1-2)

**Create `infrastructure/monitoring/prometheus.yml`:**
```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'boulder-api'
    static_configs:
      - targets:
        - 'api-1:8080'
        - 'api-2:8080'
        - 'api-3:8080'
    metrics_path: '/metrics'

  - job_name: 'postgres'
    static_configs:
      - targets: ['postgres-exporter:9187']

  - job_name: 'redis'
    static_configs:
      - targets: ['redis-exporter:9121']
```

**Deploy Prometheus:**
```bash
docker run -d \
  -p 9090:9090 \
  -v $(pwd)/prometheus.yml:/etc/prometheus/prometheus.yml \
  --name prometheus \
  prom/prometheus:latest
```

---

#### Task 4.13: Grafana Dashboards (Day 3)

**Deploy Grafana:**
```bash
docker run -d \
  -p 3000:3000 \
  --name grafana \
  grafana/grafana:latest
```

**Create Dashboard (JSON):**
```json
{
  "dashboard": {
    "title": "Boulder Rollers API",
    "panels": [
      {
        "title": "Request Rate",
        "targets": [
          {
            "expr": "rate(http_requests_total[5m])"
          }
        ]
      },
      {
        "title": "Error Rate",
        "targets": [
          {
            "expr": "rate(http_requests_total{status=~\"5..\"}[5m])"
          }
        ]
      },
      {
        "title": "Latency (P95)",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))"
          }
        ]
      },
      {
        "title": "Database Query Time",
        "targets": [
          {
            "expr": "rate(database_query_duration_seconds_sum[5m])"
          }
        ]
      }
    ]
  }
}
```

---

#### Task 4.14: Grafana Loki (Logs) (Day 4)

**Deploy Loki:**
```bash
docker run -d \
  -p 3100:3100 \
  --name loki \
  grafana/loki:latest
```

**Configure Promtail (log shipper) on API servers:**
```yaml
# promtail-config.yml
server:
  http_listen_port: 9080

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: boulder-api
    static_configs:
      - targets:
          - localhost
        labels:
          job: boulder-api
          __path__: /var/log/boulder/*.log
```

---

#### Task 4.15: Alerting (Day 5)

**Create `infrastructure/monitoring/alerts.yml`:**
```yaml
groups:
  - name: boulder_alerts
    interval: 30s
    rules:
      - alert: APIDown
        expr: up{job="boulder-api"} == 0
        for: 2m
        annotations:
          summary: "API server is down"

      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
        for: 5m
        annotations:
          summary: "Error rate > 5%"

      - alert: HighLatency
        expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 1
        for: 5m
        annotations:
          summary: "P95 latency > 1s"

      - alert: DatabaseDown
        expr: up{job="postgres"} == 0
        for: 1m
        annotations:
          summary: "Database is down"
```

**Configure PagerDuty:**
```yaml
# alertmanager.yml
route:
  receiver: 'pagerduty'

receivers:
  - name: 'pagerduty'
    pagerduty_configs:
      - service_key: '<your-pagerduty-key>'
```

---

### Week 5: Performance & Scaling

#### Task 4.16: CDN Setup (Day 1)

**Cloudflare CDN:**
```bash
# Enable caching for:
# - Static assets (images, JS, CSS)
# - Segment geojson (5 min TTL)
# - Leaderboards (1 min TTL)

# Cache rules in Cloudflare dashboard:
Cache-Control: public, max-age=300  # Segments
Cache-Control: public, max-age=60   # Leaderboards
```

---

#### Task 4.17: Database Optimization (Day 2)

**PgBouncer (Connection Pooling):**
```ini
# /etc/pgbouncer/pgbouncer.ini
[databases]
boulder_rollers = host=db.internal port=5432

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
auth_type = md5
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 25
```

**Deploy:**
```bash
docker run -d \
  -p 6432:6432 \
  -v $(pwd)/pgbouncer.ini:/etc/pgbouncer/pgbouncer.ini \
  --name pgbouncer \
  edoburu/pgbouncer
```

---

#### Task 4.18: Load Testing (Day 3-4)

**Install k6:**
```bash
brew install k6
```

**Create `infrastructure/load-tests/api-test.js`:**
```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';

export let options = {
  stages: [
    { duration: '2m', target: 100 },   // Ramp up to 100 users
    { duration: '5m', target: 100 },   // Stay at 100 users
    { duration: '2m', target: 1000 },  // Ramp up to 1000 users
    { duration: '5m', target: 1000 },  // Stay at 1000 users
    { duration: '2m', target: 0 },     // Ramp down
  ],
};

export default function () {
  // Test: Get nearby segments
  let res = http.get('https://api.boulderrollers.com/api/v1/segments/nearby?lat=40.7&lon=-74&radius_km=5');

  check(res, {
    'status is 200': (r) => r.status === 200,
    'response time < 500ms': (r) => r.timings.duration < 500,
  });

  sleep(1);
}
```

**Run:**
```bash
k6 run infrastructure/load-tests/api-test.js
```

---

#### Task 4.19: Auto-Scaling (Day 5)

**DigitalOcean Kubernetes (Alternative to manual scaling):**
```bash
doctl kubernetes cluster create boulder-cluster \
  --region nyc3 \
  --node-pool "name=worker-pool;size=s-2vcpu-4gb;count=3;auto-scale=true;min-nodes=3;max-nodes=10"
```

**OR Manual Auto-Scaling Script:**
```bash
#!/bin/bash
# Check CPU usage, scale up if > 80%

CPU=$(ssh api-server "top -bn1 | grep 'Cpu(s)' | awk '{print $2}'")

if (( $(echo "$CPU > 80" | bc -l) )); then
    echo "CPU > 80%, scaling up..."
    terraform apply -auto-approve -var="api_count=5"
fi
```

---

### Week 6: Security

#### Task 4.20: WAF (Web Application Firewall) (Day 1)

**Cloudflare WAF Rules:**
```bash
# Block SQL injection attempts
# Block XSS attempts
# Rate limit: 100 req/min per IP
# Challenge suspicious IPs
```

---

#### Task 4.21: SSL/TLS Configuration (Day 2)

**Enforce HTTPS:**
```nginx
# nginx.conf
server {
    listen 80;
    server_name api.boulderrollers.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.boulderrollers.com;

    ssl_certificate /etc/letsencrypt/live/api.boulderrollers.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.boulderrollers.com/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
}
```

---

#### Task 4.22: Firewall Rules (Day 3)

**DigitalOcean Firewall:**
```bash
doctl compute firewall create \
  --name boulder-api-fw \
  --inbound-rules "protocol:tcp,ports:443,sources:addresses:0.0.0.0/0" \
  --inbound-rules "protocol:tcp,ports:22,sources:addresses:YOUR_IP" \
  --outbound-rules "protocol:tcp,ports:all,destinations:addresses:0.0.0.0/0"
```

---

#### Task 4.23: Secrets Rotation (Day 4)

**JWT Secret Rotation Script:**
```bash
#!/bin/bash
# Rotate JWT secret monthly

NEW_SECRET=$(openssl rand -base64 32)

# Update in all API servers
ssh root@api-1 "echo 'JWT_SECRET=$NEW_SECRET' >> /etc/boulder/.env"
ssh root@api-2 "echo 'JWT_SECRET=$NEW_SECRET' >> /etc/boulder/.env"
ssh root@api-3 "echo 'JWT_SECRET=$NEW_SECRET' >> /etc/boulder/.env"

# Restart services
ssh root@api-1 "systemctl restart boulder-api"
# ...
```

---

#### Task 4.24: Penetration Testing (Day 5)

**Run OWASP ZAP:**
```bash
docker run -t owasp/zap2docker-stable zap-baseline.py \
  -t https://api.boulderrollers.com \
  -r zap-report.html
```

---

### Week 7: Documentation & Launch Prep

#### Task 4.25: Operations Runbooks (Day 1-2)

**Create `docs/runbooks/`:**
```markdown
# Runbook: API Server Down

## Symptoms
- Health check failing
- Users can't access API

## Diagnosis
1. Check server status: `doctl compute droplet list`
2. SSH into server: `ssh root@api-server`
3. Check logs: `journalctl -u boulder-api -f`
4. Check Docker: `docker ps`

## Resolution
1. Restart service: `systemctl restart boulder-api`
2. If still down: Rollback to previous version
3. Check database connection
4. Check for OOM (out of memory)

## Prevention
- Monitor memory usage
- Set up auto-restart on failure
```

---

#### Task 4.26: Disaster Recovery Plan (Day 3)

**Create `docs/disaster-recovery.md`:**
```markdown
# Disaster Recovery Plan

## Database Failure

**RTO:** 15 minutes
**RPO:** 24 hours (daily backups)

### Steps:
1. Promote read replica to primary
2. Update connection strings
3. Restart API servers
4. Restore from last backup if needed

## Total Infrastructure Loss

### Steps:
1. Run Terraform: `terraform apply`
2. Restore database from S3
3. Deploy API: `./deploy.sh prod latest`
4. Verify all services
```

---

#### Task 4.27: Launch Checklist (Day 4)

**Create `docs/launch-checklist.md`:**
```markdown
# Launch Checklist

## Pre-Launch (1 week before)
- [ ] All tests passing
- [ ] Load testing complete (1000+ concurrent users)
- [ ] Security scan clean (no critical vulnerabilities)
- [ ] Backups configured and tested
- [ ] Monitoring and alerts configured
- [ ] DNS configured
- [ ] SSL certificates valid

## Launch Day
- [ ] Deploy to production
- [ ] Smoke test all endpoints
- [ ] Monitor dashboards for 1 hour
- [ ] On-call rotation active

## Post-Launch (1 week after)
- [ ] Review error logs daily
- [ ] Check performance metrics
- [ ] Address user-reported issues
- [ ] Scale up if needed
```

---

#### Task 4.28: Team Handoff (Day 5)

**Share with team:**
- Production URLs
- Monitoring dashboard URLs
- PagerDuty rotation
- SSH access instructions
- Deployment instructions

**Hold knowledge transfer session:**
- How to deploy
- How to rollback
- How to check logs
- Who to contact for issues

---

## Docker Compose (Local Dev)

**Create `docker-compose.yml` in project root:**
```yaml
version: '3.8'

services:
  postgres:
    image: postgis/postgis:15-3.3
    environment:
      POSTGRES_DB: boulder_rollers
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  nats:
    image: nats:2.10-alpine
    command: ["-js", "-sd", "/data"]
    ports:
      - "4222:4222"
    volumes:
      - nats_data:/data

  api:
    build: ./backend
    ports:
      - "8080:8080"
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres/boulder_rollers
      REDIS_URL: redis://redis:6379
      NATS_URL: nats://nats:4222
    depends_on:
      - postgres
      - redis
      - nats

volumes:
  postgres_data:
  nats_data:
```

---

## Communication with Other Workers

**Worker 1 (Solana) needs:**
- Solana RPC endpoint (if you're hosting nodes)
- Deployment keys (securely shared)

**Worker 2 (Backend) needs:**
- Database connection strings
- Redis URLs
- API server URLs (dev + prod)

**Worker 3 (iOS) needs:**
- API base URLs
- TestFlight access for builds

**You provide to all:**
- Infrastructure URLs
- Monitoring dashboards
- On-call schedule

---

## Deliverables Each Week

1. Infrastructure URLs (dev/prod)
2. Monitoring dashboards live
3. CI/CD pipelines working
4. Documentation updated

---

## Resources

- Terraform: https://www.terraform.io/docs
- DigitalOcean: https://docs.digitalocean.com/
- Grafana: https://grafana.com/docs/
- Prometheus: https://prometheus.io/docs/
- Your working directory: `/infrastructure/`
