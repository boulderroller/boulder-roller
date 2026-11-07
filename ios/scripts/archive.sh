#!/bin/bash
# Release archive lane (bead boulderroller-v2-odmi6.14, LIST THREE item 2).
#
#   bash ios/scripts/archive.sh
#
# Produces ios/build/BoulderRoller.xcarchive with dSYMs, stamps the build
# number from git, and preserves the dSYMs under the documented local path:
#
#   ~/BoulderRoller-dSYMs/<marketing>-<build>-<shortsha>/
#
# dSYMs are NEVER committed to git. For droplet-side preservation, rsync the
# folder to root@$DROPLET_IP:/root/boulderroller-dsyms/ (see
# docs/runbooks/IOS_CRASH_SYMBOLICATION.md).
#
# Signing (the key boundary): without the founder's Apple Developer team
# this script still runs — it produces an UNSIGNED archive that compiles,
# links, and carries symbols, and says so truthfully. Device-installable
# and uploadable archives additionally need ios/.release-config.env
# (gitignored) with:
#
#   DEVELOPMENT_TEAM=XXXXXXXXXX        # founder's team id
#
# and, for the upload lane, the App Store Connect API key entries
# (see upload_testflight.sh).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IOS_DIR="$(dirname "$SCRIPT_DIR")"
REPO_DIR="$(dirname "$IOS_DIR")"
BUILD_DIR="$IOS_DIR/build"
ARCHIVE_PATH="$BUILD_DIR/BoulderRoller.xcarchive"
CONFIG_FILE="$IOS_DIR/.release-config.env"

cd "$REPO_DIR"

BUILD_NUMBER="$(bash "$SCRIPT_DIR/build_number.sh")"
SHORT_SHA="$(git rev-parse --short HEAD)"
MARKETING_VERSION="$(grep -E '^\s+MARKETING_VERSION:' "$IOS_DIR/project.yml" | awk '{print $2}')"

echo "=== Boulder Roller archive ==="
echo "version $MARKETING_VERSION ($BUILD_NUMBER) @ $SHORT_SHA"

# Parser framework must be staged before generation.
if [ ! -d "$IOS_DIR/Packages/WorkoutParse/Artifacts" ]; then
    echo "Staging parser framework..."
    bash "$IOS_DIR/scripts/build_parser.sh"
fi

cd "$IOS_DIR"
xcodegen generate

SIGNING_ARGS=(CODE_SIGNING_ALLOWED=NO)
SIGNED=false
if [ -f "$CONFIG_FILE" ]; then
    # shellcheck disable=SC1090
    source "$CONFIG_FILE"
    if [ -n "${DEVELOPMENT_TEAM:-}" ]; then
        SIGNING_ARGS=(
            CODE_SIGNING_ALLOWED=YES
            CODE_SIGN_STYLE=Automatic
            "DEVELOPMENT_TEAM=$DEVELOPMENT_TEAM"
            -allowProvisioningUpdates
        )
        SIGNED=true
    fi
fi

rm -rf "$ARCHIVE_PATH"
xcodebuild archive \
    -project BoulderRoller.xcodeproj \
    -scheme BoulderRoller \
    -destination 'generic/platform=iOS' \
    -archivePath "$ARCHIVE_PATH" \
    CURRENT_PROJECT_VERSION="$BUILD_NUMBER" \
    "${SIGNING_ARGS[@]}"

# Preserve dSYMs per build id — the crash pipeline's symbolication source.
DSYM_DEST="$HOME/BoulderRoller-dSYMs/$MARKETING_VERSION-$BUILD_NUMBER-$SHORT_SHA"
mkdir -p "$DSYM_DEST"
if [ -d "$ARCHIVE_PATH/dSYMs" ] && [ -n "$(ls -A "$ARCHIVE_PATH/dSYMs" 2>/dev/null)" ]; then
    cp -R "$ARCHIVE_PATH/dSYMs/." "$DSYM_DEST/"
    echo "dSYMs preserved: $DSYM_DEST"
    ls "$DSYM_DEST"
else
    echo "ERROR: archive produced no dSYMs — check DEBUG_INFORMATION_FORMAT" >&2
    exit 1
fi

echo ""
if [ "$SIGNED" = true ]; then
    echo "Archive ready (signed, team $DEVELOPMENT_TEAM): $ARCHIVE_PATH"
    echo "Next: bash ios/scripts/upload_testflight.sh"
else
    echo "Archive ready (UNSIGNED): $ARCHIVE_PATH"
    echo "This archive compiles and carries symbols but cannot install on"
    echo "devices or upload to TestFlight. Unlock: founder's Apple Developer"
    echo "team in ios/.release-config.env (DEVELOPMENT_TEAM=...)."
fi
