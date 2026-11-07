# Runbook: API Server Down

## Symptoms
- `/health/db` failing on load balancer
- Elevated 5xx in Grafana/Loki logs
- Alerts: `APIDown`, `HighErrorRate`

## Immediate Checks
1) Verify LB targets: `doctl compute load-balancer get <lb-id>` or Cloudflare DNS.
2) SSH to droplet: `ssh root@<api-host>`; ensure Docker is running: `systemctl status docker`.
3) Check containers: `docker ps`; inspect logs: `docker logs api`.
4) Verify dependencies: Postgres/Redis reachable from droplet (`pg_isready`, `redis-cli ping`).

## Remediation
- Restart API container: `docker compose -f /opt/boulder/docker-compose.yml up -d --no-deps api`.
- Pull known-good image: `docker pull $IMAGE_REPO:<tag>; docker tag ...:current`.
- If DB connectivity: restart pgbouncer/db or failover to replica (prod).
- If image broken: roll back to previous tag (`docker tag $IMAGE_REPO:<prev> $IMAGE_REPO:current; docker compose ...`).

## Postmortem Notes
- Capture Grafana/Loki timelines.
- Note deploy SHA, start time, remediation steps.
- File issue with repro and logs.
