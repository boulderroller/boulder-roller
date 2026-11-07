# Edge Proxy Source of Truth

This directory codifies production ingress behavior so edge config is versioned in-repo instead of managed as snowflake host state.

## Canonical Domain Policy

- Public app origin: `https://app.boulderroller.xyz`
- Public API origin: `https://api.boulderroller.xyz`
- Legacy API host: `https://api.boulderroller.org` redirects permanently to `.xyz`

## Files

- `nginx/api.boulderroller.xyz.conf`: host-level nginx TLS + reverse proxy config for API droplets.

## Deployment

Use the helper script:

```bash
infrastructure/scripts/deploy-edge-nginx.sh <droplet-ip-or-hostname>
```

The script:

1. Copies the tracked nginx config to `/etc/nginx/sites-available/api.boulderroller.xyz.conf`
2. Symlinks it into `/etc/nginx/sites-enabled/`
3. Runs `nginx -t`
4. Reloads nginx

## Certificate assumptions

The nginx config expects certbot-managed certs at:

- `/etc/letsencrypt/live/api.boulderroller.xyz/*`
- `/etc/letsencrypt/live/api.boulderroller.org/*` (legacy redirect host)

If cert locations differ on a target host, adapt the config in this directory and redeploy via the same script so drift remains codified.
