#!/usr/bin/env bash
# Deploy the Vercel sites that are no longer connected to Git — the org site
# (web/org), BoulderScan (web/scan) and the docs (docs/gitbook) — whenever their
# directory changed after the site's current production deployment. The portal
# (web/portal) still deploys from Git on every push to main.
#
# Why: the Hobby plan allows 100 deployments a day per team, and a Git link on
# four projects turned every push into four builds (2026-09-07). One push now
# means one build; these three go out only when they changed.
#
# Usage, from the repository root after landing on main:
#   scripts/deploy-sites.sh            # deploy whichever of the three changed
#   scripts/deploy-sites.sh --force    # deploy all three
#   scripts/deploy-sites.sh web/scan   # deploy one, if it changed
# Needs a Vercel CLI login (`npx vercel@latest login`) for the team.
set -euo pipefail

TEAM_ID="team_44x4Lqp9nIQGMFthk8ltYw8V"
# macOS ships bash 3.2 (no associative arrays), so the project map is a function.
project_for() {
  case "$1" in
    web/org) echo "prj_1ia1qbwfvKObAFRa5GJ0tOUeNvJ1" ;;
    web/scan) echo "prj_EzeqRpGlN8kA40oVdQOr9g58YxK6" ;;
    docs/gitbook) echo "prj_GbeIQjy7vs2JONtJJLaVi7sygtHp" ;;
    *) echo "unknown site: $1" >&2; return 1 ;;
  esac
}

force=0; only=()
for arg in "$@"; do
  case "$arg" in
    --force) force=1 ;;
    web/org|web/scan|docs/gitbook) only+=("$arg") ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done
[ ${#only[@]} -eq 0 ] && only=(web/org web/scan docs/gitbook)

root="$(git rev-parse --show-toplevel)"
cd "$root"
auth="$HOME/Library/Application Support/com.vercel.cli/auth.json"
token="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("token",""))' "$auth" 2>/dev/null || true)"
if [ -z "$token" ]; then echo "No Vercel CLI login found; run: npx vercel@latest login" >&2; exit 1; fi

production_created_at() {
  curl -fsS -H "Authorization: Bearer $token" "https://api.vercel.com/v9/projects/$1?teamId=$TEAM_ID" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); t=(d.get("targets") or {}).get("production") or {}; print(int((t.get("createdAt") or 0)/1000))'
}

mkdir -p .vercel
previous=""
[ -f .vercel/project.json ] && previous="$(cat .vercel/project.json)"
restore() { if [ -n "$previous" ]; then printf '%s' "$previous" > .vercel/project.json; else rm -f .vercel/project.json; fi; }
trap restore EXIT

for dir in "${only[@]}"; do
  project="$(project_for "$dir")"
  changed_at="$(git log -1 --format=%ct -- "$dir")"
  deployed_at="$(production_created_at "$project")"
  if [ "$force" -eq 0 ] && [ "$changed_at" -le "$deployed_at" ]; then
    echo "$dir: unchanged since its production deploy ($(date -r "$deployed_at" '+%Y-%m-%d %H:%M')), skipping"
    continue
  fi
  echo "$dir: deploying $(git log -1 --format=%h -- "$dir") to production"
  printf '{"projectId":"%s","orgId":"%s"}' "$project" "$TEAM_ID" > .vercel/project.json
  npx -y vercel@latest deploy --prod --yes
done
