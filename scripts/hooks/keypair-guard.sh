#!/bin/sh
# Blocks a commit that stages a Solana keypair file.
#
# A Solana keypair file is a JSON array of exactly 64 integers in 0..255
# (secret key followed by public key). Devnet and throwaway keys are blocked
# too: anything committed stays in Git history for good.

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT" || exit 0

found=0
git diff --cached --name-only --diff-filter=ACMR -z -- '*.json' |
    tr '\0' '\n' > "${TMPDIR:-/tmp}/keypair-guard.$$"

while IFS= read -r path; do
    [ -n "$path" ] || continue
    if git show ":$path" 2>/dev/null | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)
ok = (isinstance(data, list) and len(data) == 64
      and all(isinstance(x, int) and 0 <= x <= 255 for x in data))
sys.exit(0 if ok else 1)
'; then
        echo "keypair-guard: $path looks like a Solana keypair (64-byte array)." >&2
        found=1
    fi
done < "${TMPDIR:-/tmp}/keypair-guard.$$"
rm -f "${TMPDIR:-/tmp}/keypair-guard.$$"

if [ "$found" -ne 0 ]; then
    echo "Keep keypairs outside the repository (for example ~/.config/solana/)." >&2
    exit 1
fi
exit 0
