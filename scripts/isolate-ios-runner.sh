#!/usr/bin/env bash
# Move the self-hosted iOS runner off Tim's account to a standard macOS user
# (blind-spot item BS-008; steps in docs/runbooks/SELF_HOSTED_RUNNER_ISOLATION.md).
#
# Run from Tim's own account: bash scripts/isolate-ios-runner.sh
# It asks for the admin password once and for the new user's password once.
# It then installs the runner as a boot-time service (ios-runner-boot-service.sh),
# so iOS CI runs after any reboot with nobody logged in to "CI Runner".
set -euo pipefail

REPO=dungbeetlephoenix/boulder-roller
CI_USER=ci
RUNNER_VERSION=2.338.0
OLD_RUNNER="$HOME/actions-runner"

command -v gh >/dev/null || { echo "gh is required"; exit 1; }
token="$(gh api -X POST "repos/$REPO/actions/runners/registration-token" --jq .token)"

echo "Stopping the runner that runs as $(whoami)..."
pkill -TERM -f "$OLD_RUNNER/bin/Runner.Listener" || true

if ! id "$CI_USER" >/dev/null 2>&1; then
    echo "Creating the standard user '$CI_USER'. First your admin password, then a new password for $CI_USER:"
    sudo sysadminctl -addUser "$CI_USER" -fullName "CI Runner" -password -
    # sysadminctl exits 0 even when it fails, so check the user exists.
    id "$CI_USER" >/dev/null 2>&1 || { echo "sysadminctl did not create '$CI_USER'"; exit 1; }
    sudo createhomedir -c -u "$CI_USER" > /dev/null
fi

echo "Locking $HOME to $(whoami)..."
chmod 700 "$HOME"

sudo xcodebuild -runFirstLaunch

echo "Installing Rust and the runner for $CI_USER..."
sudo -u "$CI_USER" -H bash -s -- "$token" "$RUNNER_VERSION" "$REPO" <<'AS_CI'
set -euo pipefail
token="$1"; version="$2"; repo="$3"
cd "$HOME"
[ -x "$HOME/.cargo/bin/rustup" ] || curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path
"$HOME/.cargo/bin/rustup" target add aarch64-apple-ios aarch64-apple-ios-sim
grep -q '/opt/homebrew/bin' "$HOME/.zprofile" 2>/dev/null \
    || echo 'export PATH="/opt/homebrew/bin:$HOME/.cargo/bin:$PATH"' >> "$HOME/.zprofile"
# The runner records this PATH (.path) for every job: replace, don't extend,
# what sudo passed on from Tim's shell, whose folders ci cannot read.
export PATH="/opt/homebrew/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
mkdir -p actions-runner && cd actions-runner
if [ ! -x ./config.sh ]; then
    curl -fsSLo runner.tar.gz "https://github.com/actions/runner/releases/download/v$version/actions-runner-osx-arm64-$version.tar.gz"
    tar xzf runner.tar.gz && rm runner.tar.gz
fi
./config.sh --url "https://github.com/$repo" --token "$token" \
    --labels boulder-ios --name boulder-ios-ci --unattended --replace
printf '%s\n' "$PATH" > .path
AS_CI

echo "Installing the runner as a boot-time service..."
bash "$(dirname "$0")/ios-runner-boot-service.sh"

if [ -x "$OLD_RUNNER/config.sh" ] && [ -f "$OLD_RUNNER/.runner" ]; then
    echo "Removing the old runner's registration..."
    (cd "$OLD_RUNNER" && ./config.sh remove \
        --token "$(gh api -X POST "repos/$REPO/actions/runners/remove-token" --jq .token)")
fi

cat <<'NEXT'

Done. The runner starts at every boot as ci, with nobody logged in to
"CI Runner". Tell Claude, who will verify.
NEXT
