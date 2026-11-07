# BoulderRollers Infrastructure (Worker 4)

This folder owns deployment and operations for the BoulderRollers API. It follows the Worker 4 plan: DigitalOcean-first, Dockerized API, Terraform-managed environments, and GitHub Actions-based delivery.

## Layout
- `terraform/` – DigitalOcean infra definitions (dev + prod) built from a shared module.
- `scripts/` – Deployment helpers.
- `edge/` – Version-controlled reverse-proxy/TLS configs for live ingress.
- `monitoring/` – Prometheus/Grafana/Loki configs (stub; fill in when targets are live).

## Terraform (DigitalOcean)
**Prereqs:** DigitalOcean account, API token, SSH key uploaded, Terraform >=1.6.

```bash
cd infrastructure/terraform/dev   # or prod
cp ../terraform.tfvars.example ./terraform.tfvars  # set tokens/keys/domain
terraform init
terraform plan
terraform apply
```

### Inputs
- `do_token` (string, sensitive) – DigitalOcean API token.
- `ssh_key_ids` (list) – SSH key IDs allowed onto droplets.
- `region` (default `nyc3`) – DO region.
- `vpc_cidr` – CIDR for the VPC (10.0.0.0/16 dev, 10.1.0.0/16 prod by default).
- `domain` – Domain for TLS (`api.boulderroller.xyz` in prod; optional for dev).
- `enable_database` / `enable_redis` – Toggle managed Postgres/Redis if you rely on Supabase or external services.

### What gets created
- VPC per environment.
- Managed Postgres + Redis (toggle-able).
- API droplets (1x dev, 3x prod) with Docker pre-installed.
- Load balancer with HTTP + optional HTTPS (LetsEncrypt) and healthcheck on `/health/db`.

**Note:** If Supabase hosts your data, set `enable_database = false`/`enable_redis = false` to avoid duplicating managed services.

### Outputs
- Droplet public/private IPs.
- Load balancer IP.
- Database/Redis URIs (sensitive).

## Deployments
- Build a backend image: `docker build -t boulderrollers/api:dev ./backend`
- Push to registry (DOCR or Docker Hub).
- Use `infrastructure/scripts/deploy.sh <host> <tag>` to pull + restart on a target droplet or via the LB hostname. Customize SSH hostnames as needed.
- To apply canonical host-level nginx ingress config: `infrastructure/scripts/deploy-edge-nginx.sh <host>`.

## Backups
- `scripts/backup-db.sh` dumps `DATABASE_URL` to gzip and optionally ships to an S3/Spaces bucket (`SPACES_BUCKET`). Add a cron entry (e.g., `0 2 * * *`) on the DB host or a runner; keeps 7 local copies by default.

## Local Dev (Docker Compose)
Use the root `docker-compose.yml` to run the API plus optional Redis/NATS. Provide secrets via environment (see `backend/.env.example`):

```bash
docker compose up --build
# API on http://localhost:8080
```

## Monitoring (stub)
`monitoring/` contains starter configs:
- `prometheus.yml` – scrape API droplets, Postgres exporter, Redis exporter.
- `alerts.yml` – API/latency/error/DB alerts.
- `loki-config.yml` / `promtail-config.yml` – log aggregation wiring (mount log dir `/var/log/boulder/*.log`).

Run locally for testing:
```bash
docker run -d -p 9090:9090 -v $PWD/monitoring/prometheus.yml:/etc/prometheus/prometheus.yml prom/prometheus
docker run -d -p 3100:3100 -v $PWD/monitoring/loki-config.yml:/etc/loki/local-config.yaml grafana/loki:latest -config.file=/etc/loki/local-config.yaml
docker run -d -p 9080:9080 -v $PWD/monitoring/promtail-config.yml:/etc/promtail/config.yml grafana/promtail:latest -config.file=/etc/promtail/config.yml
```
