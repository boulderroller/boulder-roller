#!/usr/bin/env bash
# Fail closed when parser semantics change without an immutable new version.
set -euo pipefail

base_ref="${1:?usage: check_parser_semantics_version.sh <base-ref>}"
if [[ "$base_ref" =~ ^0+$ ]]; then
  exit 0
fi

if ! base_commit="$(git rev-parse --verify "${base_ref}^{commit}" 2>/dev/null)"; then
  fallback_ref="${PARSER_SEMANTICS_FALLBACK_REF:-origin/main}"
  if ! fallback_commit="$(git rev-parse --verify "${fallback_ref}^{commit}" 2>/dev/null)"; then
    if git remote get-url origin >/dev/null 2>&1; then
      git fetch --no-tags origin \
        "+refs/heads/main:refs/remotes/origin/main" >/dev/null 2>&1 || true
      fallback_commit="$(git rev-parse --verify "${fallback_ref}^{commit}" 2>/dev/null || true)"
    fi
  fi
  if [[ -z "${fallback_commit:-}" || "$fallback_commit" == "$(git rev-parse HEAD)" ]]; then
    echo "cannot resolve parser semantic comparison base: $base_ref" >&2
    exit 1
  fi
  if ! base_commit="$(git merge-base HEAD "$fallback_commit")"; then
    echo "parser semantic fallback $fallback_ref has no merge base with HEAD" >&2
    exit 1
  fi
  echo "parser semantic base $base_ref unavailable; using $fallback_ref at $base_commit" >&2
fi

semantic_files=(
  workout-parse/src/lib.rs
  workout-parse/src/canonicalize.rs
  mobile/src/lib/canonicalize.ts
)

if git diff --quiet "$base_commit...HEAD" -- "${semantic_files[@]}"; then
  exit 0
fi

resolve_version() {
  local ref="$1"
  local file="$2"
  local declaration_pattern="$3"
  local constant_pattern="$4"
  local current expression

  current="$(git show "$ref:$file" | sed -nE "s/${declaration_pattern}/\\1/p" | head -n 1)"
  if [[ -z "$current" ]]; then
    echo "missing CURRENT_PARSER_VERSION in $file at $ref" >&2
    return 1
  fi
  if [[ "$current" =~ ^[0-9]+$ ]]; then
    printf '%s\n' "$current"
    return 0
  fi
  if [[ ! "$current" =~ ^PARSER_VERSION_V[0-9]+$ ]]; then
    echo "CURRENT_PARSER_VERSION in $file is not an integer or immutable Vn alias" >&2
    return 1
  fi

  expression="$(git show "$ref:$file" | sed -nE "s/${constant_pattern//NAME/$current}/\\1/p" | head -n 1)"
  if [[ ! "$expression" =~ ^[0-9]+$ ]]; then
    echo "$current in $file at $ref is not an integer immutable version constant" >&2
    return 1
  fi
  printf '%s\n' "$expression"
}

rust_file="workout-parse/src/canonicalize.rs"
ts_file="mobile/src/lib/canonicalize.ts"
base_rust="$(resolve_version "$base_commit" "$rust_file" \
  '.*CURRENT_PARSER_VERSION: u32 = ([A-Za-z0-9_]+);.*' \
  '.*pub const NAME: u32 = ([0-9]+);.*')"
head_rust="$(resolve_version HEAD "$rust_file" \
  '.*CURRENT_PARSER_VERSION: u32 = ([A-Za-z0-9_]+);.*' \
  '.*pub const NAME: u32 = ([0-9]+);.*')"
base_ts="$(resolve_version "$base_commit" "$ts_file" \
  '.*CURRENT_PARSER_VERSION = ([A-Za-z0-9_]+);.*' \
  '.*export const NAME = ([0-9]+);.*')"
head_ts="$(resolve_version HEAD "$ts_file" \
  '.*CURRENT_PARSER_VERSION = ([A-Za-z0-9_]+);.*' \
  '.*export const NAME = ([0-9]+);.*')"

if (( base_ts != base_rust )); then
  echo "base Rust and TypeScript CURRENT_PARSER_VERSION must resolve to the same integer" >&2
  exit 1
fi

verify_unchanged_semantics() {
  # Never certify uncommitted code or replace the goldens being reproduced.
  if ! git diff --quiet HEAD -- workout-parse mobile tests/fixtures tests/validation \
      backend/app/services/workout_parse_adapter.py \
      backend/tests/truths/alignment/test_ride_hash_symmetry_gate.py; then
    echo "parser semantic verification requires committed inputs" >&2
    return 1
  fi
  if ! git diff --quiet "$base_commit...HEAD" -- \
      "tests/fixtures/canonical_ride_v${head_rust}_vectors.json" \
      'tests/fixtures/canonical_cross_format_*_vectors.json' \
      workout-parse/tests/fixtures tests/fixtures/mobile_sensor_ride_fit_v1.base64; then
    echo "parser semantic exemption cannot change existing vector inputs or goldens" >&2
    return 1
  fi

  if ! git diff --quiet "$base_commit...HEAD" -- \
      workout-parse/src/lib.rs workout-parse/src/canonicalize.rs; then
    python3 tools/verify_parser_semantics.py "$head_rust" || return 1
  fi
  if ! git diff --quiet "$base_commit...HEAD" -- "$ts_file"; then
    npm --prefix mobile test -- --runInBand --watch=false \
      --runTestsByPath src/lib/__tests__/canonicalize.test.ts || return 1
  fi
}

# Git's trailer parser ignores quoted body text and unfolds an indented reason.
# Only a declaration in this comparison range can authorize verification.
declarations="$(git log "$base_commit..HEAD" \
  --format='%(trailers:key=Parser-Semantics,valueonly,unfold)')"
if (( head_rust == base_rust && head_ts == base_ts )) && \
    grep -Eq '^unchanged[[:blank:]]+[^[:blank:]]' <<< "$declarations"; then
  if verify_unchanged_semantics; then
    echo "verified unchanged parser semantics at version $head_rust"
    exit 0
  fi
  echo "parser semantic verification failed or unavailable; requiring a version bump" >&2
fi

if (( head_rust <= base_rust )); then
  echo "Rust CURRENT_PARSER_VERSION must increase for a semantic parser change" >&2
  exit 1
fi
if (( head_ts != head_rust )); then
  echo "Rust and TypeScript CURRENT_PARSER_VERSION must resolve to the same new integer" >&2
  exit 1
fi

new_version="$head_rust"
head_rust_alias="$(git show "HEAD:$rust_file" | sed -nE \
  's/.*CURRENT_PARSER_VERSION: u32 = ([A-Za-z0-9_]+);.*/\1/p' | head -n 1)"
head_ts_alias="$(git show "HEAD:$ts_file" | sed -nE \
  's/.*CURRENT_PARSER_VERSION = ([A-Za-z0-9_]+);.*/\1/p' | head -n 1)"
if [[ "$head_rust_alias" != "PARSER_VERSION_V${new_version}" ]]; then
  echo "Rust CURRENT_PARSER_VERSION must alias PARSER_VERSION_V${new_version}" >&2
  exit 1
fi
if [[ "$head_ts_alias" != "PARSER_VERSION_V${new_version}" ]]; then
  echo "TypeScript CURRENT_PARSER_VERSION must alias PARSER_VERSION_V${new_version}" >&2
  exit 1
fi
if ! git diff "$base_commit...HEAD" -- "$rust_file" | grep -Fq \
  "+pub const PARSER_VERSION_V${new_version}: u32 = ${new_version};"; then
  echo "Rust must add PARSER_VERSION_V${new_version} = ${new_version} for this semantic change" >&2
  exit 1
fi
if ! git diff "$base_commit...HEAD" -- "$ts_file" | grep -Fq \
  "+export const PARSER_VERSION_V${new_version} = ${new_version};"; then
  echo "TypeScript must add PARSER_VERSION_V${new_version} = ${new_version} for this semantic change" >&2
  exit 1
fi

vector_path="tests/fixtures/canonical_ride_v${new_version}_vectors.json"
if ! git diff --name-status "$base_commit...HEAD" -- "$vector_path" | grep -Fq $'A\t'; then
  echo "parser semantic change must add $vector_path" >&2
  exit 1
fi
if ! git show "HEAD:$vector_path" | grep -Eq \
  "\"parser_version\"[[:space:]]*:[[:space:]]*${new_version}([,}[:space:]])"; then
  echo "$vector_path must declare parser_version ${new_version}" >&2
  exit 1
fi
