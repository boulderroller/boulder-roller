#!/bin/bash
# Monotonic build number from git history (bead boulderroller-v2-odmi6.14).
# One number per commit, strictly increasing along the branch — App Store
# Connect requires CFBundleVersion to grow between uploads.
set -euo pipefail
cd "$(dirname "$0")/../.."
git rev-list --count HEAD
