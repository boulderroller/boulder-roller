# Monitoring Stack

Prometheus, Grafana, and exporters for the Boulder Rollers API/worker stack.

## Required environment

- `POSTGRES_EXPORTER_DSN` (read-only Supabase connection string recommended)
  - Example: `postgresql://readonly:***@db.<project>.supabase.co:5432/postgres?sslmode=require`
  - Supabase direct DB hosts are IPv6-only. Enable IPv6 on the droplet and ensure Docker supports IPv6, or use the Supabase pooler host as a fallback (reduced metrics fidelity).

## IPv6 setup (DigitalOcean)

- Enable IPv6 on the droplet in the DO control panel.
- Configure Docker for IPv6 so containers can reach Supabase:
  - `/etc/docker/daemon.json`: `{"ipv6": true, "fixed-cidr-v6": "fd00:1::/64"}`
  - `systemctl restart docker`

## Notes

- Celery worker metrics are exposed on `CELERY_METRICS_PORT` (see `docker-compose.yml`).
- Redis metrics are provided via `redis-exporter` on port `9121`.
- Auth-entry funnel metrics are exported as:
  - `auth_funnel_events_total{stage,result}`
  - `auth_funnel_stage_duration_seconds{stage}`
- Grafana includes `Boulder Auth Entry` dashboard for invite/login/refresh funnel health.
