#!/bin/sh
# Build the portal workshop and push it to Vercel as a static, unlisted site.
#
#   WORKSHOP_PASSPHRASE='the word the designer will type' scripts/deploy-workshop.sh
#
# Run from web/portal. The passphrase is hashed here and only the hash reaches the
# bundle (VITE_WORKSHOP_GATE_SHA256); the page compares hashes. Search engines are
# told to stay out by meta tag and header. No git hookup: deploys happen only when
# this script runs. Project name defaults to boulder-workshop (WORKSHOP_VERCEL_PROJECT).
set -e
cd "$(dirname "$0")/.."
[ -n "$WORKSHOP_PASSPHRASE" ] || { echo "Set WORKSHOP_PASSPHRASE first." >&2; exit 1; }
NORMALIZED=$(printf '%s' "$WORKSHOP_PASSPHRASE" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | tr '[:upper:]' '[:lower:]')
HASH=$(printf '%s' "$NORMALIZED" | shasum -a 256 | cut -d' ' -f1)
PROJECT="${WORKSHOP_VERCEL_PROJECT:-boulder-workshop}"
# The upload endpoint needs a current CLI; the Homebrew one on this Mac (v41) is too old, so always use the latest via npx.
VERCEL="npx -y vercel@latest"
VITE_WORKSHOP_GATE_SHA256="$HASH" npm run -s workshop:build
cat > workshop-dist/vercel.json <<'JSON'
{ "headers": [ { "source": "/(.*)", "headers": [ { "key": "X-Robots-Tag", "value": "noindex, nofollow" } ] } ] }
JSON
cd workshop-dist
$VERCEL project add "$PROJECT" >/dev/null 2>&1 || true
$VERCEL link --yes --project "$PROJECT" >/dev/null
$VERCEL deploy --prod --yes
