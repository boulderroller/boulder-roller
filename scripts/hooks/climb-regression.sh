#!/bin/bash
# climb-regression.sh - Check for climb detection regressions after workout-parse edits
# Compares v2 persistence detection on 8 validation FIT files against baseline counts.

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
FIXTURES_DIR="$REPO_ROOT/tests/validation"
BASELINE_FILE="$REPO_ROOT/.claude/climb-baseline.json"

# Check if the edited file is in workout-parse
EDITED_FILE="${1:-}"
if [ -n "$EDITED_FILE" ]; then
    if [[ ! "$EDITED_FILE" =~ workout-parse/ ]]; then
        exit 0
    fi
fi

echo "=== Climb Regression Check ==="

# Verify fixtures exist
if [ ! -d "$FIXTURES_DIR" ] || ! ls "$FIXTURES_DIR"/*.fit 1>/dev/null 2>&1; then
    echo "No FIT fixtures in $FIXTURES_DIR - skipping"
    exit 0
fi

# Build if needed (cargo is smart about no-op builds)
cd "$REPO_ROOT/workout-parse"
echo "Building workout-parse..."
if ! cargo build --release 2>&1 | tail -3; then
    echo "Build FAILED - cannot run regression check"
    exit 1
fi

# Run detection on all fixture files
echo ""
echo "Running v2 persistence detection on validation fixtures:"
CURRENT=$("$REPO_ROOT/backend/venv/bin/python" -c "
import workout_parse as wp
import json, glob

def parse_samples(filepath):
    activity = wp.parse_file(filepath)
    n = len(activity.time_ms)
    start_ms = activity.time_ms[0]
    samples = []
    for i in range(n):
        s = {'t': int((activity.time_ms[i] - start_ms) / 1000)}
        if activity.elevation_m is not None and i < len(activity.elevation_m):
            s['elevation_m'] = float(activity.elevation_m[i])
        if activity.lat_e7 is not None and i < len(activity.lat_e7):
            s['lat'] = float(activity.lat_e7[i]) / 1e7
            s['lon'] = float(activity.lon_e7[i]) / 1e7
        if activity.pwr_w is not None and i < len(activity.pwr_w):
            pw = int(activity.pwr_w[i])
            if 0 < pw < 5000:
                s['power_w'] = pw
        samples.append(s)
    return samples

results = {}
for fit_file in sorted(glob.glob('$FIXTURES_DIR/*.fit')):
    fname = fit_file.split('/')[-1]
    samples = parse_samples(fit_file)
    climbs = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)
    sig_count = sum(1 for c in climbs if c.vert_m >= 20)
    results[fname] = {'total': len(climbs), 'significant': sig_count}
    print(f'  {fname}: {len(climbs)} total, {sig_count} significant')
print('---JSON---')
print(json.dumps(results))
" 2>&1)

# Extract JSON from output
CURRENT_JSON=$(echo "$CURRENT" | sed -n '/^---JSON---$/,$ p' | tail -1)
echo "$CURRENT" | grep -v '^---JSON---$' | head -20

# Compare to baseline
if [ -f "$BASELINE_FILE" ]; then
    echo ""
    echo "Comparing to baseline..."
    DIFF=$("$REPO_ROOT/backend/venv/bin/python" -c "
import json, sys

baseline = json.load(open('$BASELINE_FILE'))
current = json.loads('$CURRENT_JSON')

changed = False
for fname in sorted(set(list(baseline.keys()) + list(current.keys()))):
    b = baseline.get(fname, {})
    c = current.get(fname, {})
    bt, bs = b.get('total', 0), b.get('significant', 0)
    ct, cs = c.get('total', 0), c.get('significant', 0)
    if bt != ct or bs != cs:
        changed = True
        dt = ct - bt
        ds = cs - bs
        print(f'  CHANGED: {fname}: total {bt}->{ct} ({dt:+d}), sig {bs}->{cs} ({ds:+d})')

if not changed:
    print('  No regression detected.')
else:
    print()
    print('  To update baseline: cp the current results to .claude/climb-baseline.json')
" 2>&1)
    echo "$DIFF"
else
    echo ""
    echo "No baseline file at $BASELINE_FILE"
    echo "To create: run this script and save .claude/climb-baseline.json"
fi

echo "===================="
