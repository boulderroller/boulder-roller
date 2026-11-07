# API DNS Setup (api.boulderroller.xyz)

## Overview

The backend API runs on a DigitalOcean droplet behind a Caddy reverse proxy that
auto-provisions TLS via Let's Encrypt. The frontend at `app.boulderroller.xyz`
makes direct HTTPS requests to `https://api.boulderroller.xyz`.

## Architecture

```
Browser (app.boulderroller.xyz)
  |
  | HTTPS (cross-origin, CORS)
  v
Caddy (:443, auto-TLS)  <-- api.boulderroller.xyz
  |
  | HTTP (internal Docker network)
  v
FastAPI (:8080)          <-- api container
```

## Manual Step: Create DNS A Record

Create an A record in the DNS provider for `boulderroller.xyz`:

| Type | Name | Value           | TTL  |
|------|------|-----------------|------|
| A    | api  | STAGING_IP  | 300  |

This points `api.boulderroller.xyz` to the staging droplet.

Once DNS propagates (typically under 5 minutes with a 300s TTL), Caddy will
automatically detect the domain and provision a Let's Encrypt certificate.
No manual certificate management is needed.

`api.boulderroller.org` should be configured as a permanent redirect to
`https://api.boulderroller.xyz` to avoid split API origins.

## Deploy

After DNS is configured, SSH into the droplet and bring up the updated stack:

```bash
ssh root@STAGING_IP
cd /root/boulder-repo
git pull
docker compose up -d --build
```

Caddy will start, detect `api.boulderroller.xyz` in the Caddyfile, and begin
the ACME challenge to obtain a TLS certificate. This usually completes in
under 30 seconds.

## Verify

```bash
# Check DNS resolution
dig api.boulderroller.xyz +short
# Expected: STAGING_IP

# Check TLS and API health
curl -v https://api.boulderroller.xyz/health

# Check from the droplet itself
docker compose logs caddy --tail=20
```

A successful response from `/health` confirms:
1. DNS is resolving correctly
2. Caddy provisioned TLS
3. Caddy is reverse-proxying to FastAPI
4. FastAPI is responding

## Troubleshooting

**Caddy logs show ACME challenge failure:**
- Ensure ports 80 and 443 are open on the droplet firewall (`ufw allow 80,443/tcp`)
- Ensure no other process is binding to ports 80/443

**curl: Could not resolve host:**
- DNS hasn't propagated yet. Wait a few minutes or check with `dig @8.8.8.8 api.boulderroller.xyz`

**CORS errors in browser console:**
- Verify `backend/app/main.py` includes `app.boulderroller.xyz` and required frontend origins
- Check the `CORS_EXTRA_ORIGINS` env var on the droplet if additional origins are needed

## Related Files

- `infrastructure/Caddyfile` -- Caddy reverse proxy config
- `docker-compose.yml` -- Caddy service definition
- `backend/app/main.py` -- CORS allowed origins
- `web/portal/.env.production` -- Frontend API URL
