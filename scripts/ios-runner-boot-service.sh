#!/usr/bin/env bash
# Start the self-hosted iOS runner at boot, with nobody logged in as "CI Runner"
# (steps in docs/runbooks/SELF_HOSTED_RUNNER_ISOLATION.md).
#
# Two launchd jobs, both defined in root-owned files:
#   - the runner job runs runsvc.sh as ci in ci's own launchd user domain, the
#     context where the iOS Simulator works without a login session;
#   - a boot daemon only loads that job into ci's domain at startup.
# Root runs nothing but /bin/sh and launchctl on root-owned paths. CI jobs run
# untrusted code as ci, so nothing ci can write may ever run as root.
#
# Run from Tim's account: bash scripts/ios-runner-boot-service.sh
# Undo (back to CI Runner's login service): bash scripts/ios-runner-boot-service.sh --undo
# Either way it asks for the admin password once.
set -euo pipefail

CI_USER=ci
CI_UID="$(id -u "$CI_USER")"
RUNNER_DIR="/Users/$CI_USER/actions-runner"
LABEL=actions.runner.dungbeetlephoenix-boulder-roller.boulder-ios-ci
JOB_DIR="/Library/Application Support/BoulderRoller"
JOB="$JOB_DIR/$LABEL.plist"
BOOT_LABEL="$LABEL.boot"
BOOT="/Library/LaunchDaemons/$BOOT_LABEL.plist"
AGENT="/Users/$CI_USER/Library/LaunchAgents/$LABEL.plist"
# The first version of this script ran the runner from a root daemon here.
OLD_DAEMON="/Library/LaunchDaemons/$LABEL.plist"

job_plist() {
    cat <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$RUNNER_DIR/runsvc.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$RUNNER_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>ACTIONS_RUNNER_SVC</key>
    <string>1</string>
  </dict>
  <key>LimitLoadToSessionType</key>
  <string>Background</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>ProcessType</key>
  <string>Interactive</string>
  <key>SessionCreate</key>
  <true/>
</dict>
</plist>
PLIST
}

boot_plist() {
    cat <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$BOOT_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>-c</string>
    <string>/bin/launchctl print user/$CI_UID/$LABEL &gt; /dev/null 2&gt;&amp;1 || /bin/launchctl bootstrap user/$CI_UID '$JOB'</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
</dict>
</plist>
PLIST
}

if [ "${1:-}" = "--print" ]; then job_plist; boot_plist; exit 0; fi
sudo test -f "$RUNNER_DIR/.runner" \
    || { echo "No configured runner in $RUNNER_DIR; run scripts/isolate-ios-runner.sh first."; exit 1; }

if [ "${1:-}" = "--undo" ]; then
    sudo launchctl bootout "system/$BOOT_LABEL" 2>/dev/null || true
    sudo launchctl bootout "user/$CI_UID/$LABEL" 2>/dev/null || true
    sudo rm -f "$BOOT" "$JOB"
    if sudo test -f "$AGENT.off"; then sudo mv "$AGENT.off" "$AGENT"; fi
    echo "Back to CI Runner's login service: log in to CI Runner once to start the runner."
    exit 0
fi

# svc.sh install creates runsvc.sh next to the runner; do the same if it hasn't run.
if ! sudo test -x "$RUNNER_DIR/runsvc.sh"; then
    sudo -u "$CI_USER" -H bash -c 'cd ~/actions-runner && cp ./bin/runsvc.sh ./runsvc.sh && chmod u+x ./runsvc.sh'
fi
# An install made before isolate-ios-runner.sh set its own PATH recorded this
# account's PATH for every job; ci can't read those folders.
if sudo grep -q "/Users/$(id -un)/" "$RUNNER_DIR/.path" 2>/dev/null; then
    sudo -u "$CI_USER" -H bash -c 'printf "%s\n" "/opt/homebrew/bin:$HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" > ~/actions-runner/.path'
fi

echo "Retiring CI Runner's login service and any earlier boot daemon..."
# The login agent would start a second runner whenever CI Runner logs in.
if sudo test -f "$AGENT"; then sudo mv "$AGENT" "$AGENT.off"; fi
sudo launchctl bootout "gui/$CI_UID/$LABEL" 2>/dev/null || true
sudo launchctl bootout "system/$LABEL" 2>/dev/null || true
sudo rm -f "$OLD_DAEMON"

echo "Installing the boot-time service..."
sudo mkdir -p "$JOB_DIR"
sudo chown root:wheel "$JOB_DIR"
sudo chmod 755 "$JOB_DIR"
job_plist | sudo tee "$JOB" > /dev/null
boot_plist | sudo tee "$BOOT" > /dev/null
sudo chown root:wheel "$JOB" "$BOOT"
sudo chmod 644 "$JOB" "$BOOT"
sudo launchctl bootout "system/$BOOT_LABEL" 2>/dev/null || true
sudo launchctl bootout "user/$CI_UID/$LABEL" 2>/dev/null || true
sudo launchctl bootstrap system "$BOOT"

for _ in $(seq 1 30); do
    if pgrep -u "$CI_USER" -f Runner.Listener > /dev/null; then
        echo "Done. The runner starts at boot as $CI_USER; nobody needs to log in to CI Runner."
        exit 0
    fi
    sleep 2
done
echo "The runner didn't start within a minute. Check: sudo launchctl print user/$CI_UID/$LABEL. Undo: bash $0 --undo"
exit 1
