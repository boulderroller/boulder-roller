#!/bin/bash
# TestFlight upload lane (bead boulderroller-v2-odmi6.14, LIST THREE item 2).
#
#   bash ios/scripts/archive.sh          # first
#   bash ios/scripts/upload_testflight.sh
#
# Reads the App Store Connect API key from the documented local config,
# ios/.release-config.env (gitignored — secrets never in git):
#
#   DEVELOPMENT_TEAM=XXXXXXXXXX
#   ASC_KEY_ID=ABC123DEFG
#   ASC_ISSUER_ID=12345678-aaaa-bbbb-cccc-1234567890ab
#   ASC_KEY_PATH=$HOME/.appstoreconnect/private_keys/AuthKey_ABC123DEFG.p8
#
# Fails with a truthful list of exactly what is missing. When everything is
# present, xcodebuild exports the archive and uploads it to App Store
# Connect (TestFlight processing follows in the ASC UI).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IOS_DIR="$(dirname "$SCRIPT_DIR")"
ARCHIVE_PATH="$IOS_DIR/build/BoulderRoller.xcarchive"
CONFIG_FILE="$IOS_DIR/.release-config.env"
EXPORT_DIR="$IOS_DIR/build/export"

missing=()

if [ -f "$CONFIG_FILE" ]; then
    # shellcheck disable=SC1090
    source "$CONFIG_FILE"
else
    missing+=("ios/.release-config.env (gitignored config file)")
fi
[ -n "${DEVELOPMENT_TEAM:-}" ] || missing+=("DEVELOPMENT_TEAM (founder's Apple Developer team id)")
[ -n "${ASC_KEY_ID:-}" ] || missing+=("ASC_KEY_ID (App Store Connect API key id)")
[ -n "${ASC_ISSUER_ID:-}" ] || missing+=("ASC_ISSUER_ID (App Store Connect issuer id)")
if [ -n "${ASC_KEY_PATH:-}" ]; then
    [ -f "$ASC_KEY_PATH" ] || missing+=("the .p8 file at ASC_KEY_PATH ($ASC_KEY_PATH)")
else
    missing+=("ASC_KEY_PATH (path to the AuthKey_*.p8 file)")
fi
[ -d "$ARCHIVE_PATH" ] || missing+=("the archive (run: bash ios/scripts/archive.sh)")

if [ ${#missing[@]} -gt 0 ]; then
    echo "Cannot upload to TestFlight yet. Missing:"
    for item in "${missing[@]}"; do
        echo "  - $item"
    done
    echo ""
    echo "These come from the founder's Apple Developer account (one-time"
    echo "setup steps in ios/RELEASE.md). Nothing else is missing: the"
    echo "archive lane, build numbering, dSYM preservation, and this upload"
    echo "lane are ready."
    exit 2
fi

echo "=== Uploading to App Store Connect (TestFlight) ==="
rm -rf "$EXPORT_DIR"
xcodebuild -exportArchive \
    -archivePath "$ARCHIVE_PATH" \
    -exportOptionsPlist "$SCRIPT_DIR/ExportOptions.plist" \
    -exportPath "$EXPORT_DIR" \
    -allowProvisioningUpdates \
    -authenticationKeyPath "$ASC_KEY_PATH" \
    -authenticationKeyID "$ASC_KEY_ID" \
    -authenticationKeyIssuerID "$ASC_ISSUER_ID"

echo ""
echo "Upload submitted. TestFlight processing continues in App Store"
echo "Connect; invite internal testers there (ios/RELEASE.md step 4)."
