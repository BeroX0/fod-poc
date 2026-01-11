#!/usr/bin/env bash
set -euo pipefail

[[ -n "${BASH_VERSION:-}" ]] || { echo "ERROR: Run with bash: bash tools/make_source_zip.sh ..."; exit 2; }

usage() {
  cat <<'USAGE'
Usage:
  bash tools/make_source_zip.sh [--out /path/to/source.zip]

Creates the submission source-code zip using ONLY:
  git archive

This avoids leaking ignored artifacts (models/videos/demo packs) that could be included by 'zip -r'.

Examples:
  bash tools/make_source_zip.sh
  bash tools/make_source_zip.sh --out /tmp/sep400_fod_poc_source.zip
USAGE
}

OUT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="${2:-}"; shift 2;;
    --help|-h) usage; exit 0;;
    *) echo "ERROR: Unknown arg: $1"; usage; exit 2;;
  esac
done

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[[ -n "$REPO_ROOT" ]] || { echo "ERROR: Not inside a git repo."; exit 2; }

if [[ -z "$OUT" ]]; then
  OUT="/tmp/sep400_fod_poc_source_$(date +%Y%m%d_%H%M%S).zip"
fi

echo "REPO_ROOT=$REPO_ROOT"
echo "OUT=$OUT"

git -C "$REPO_ROOT" archive -o "$OUT" HEAD
ls -lah "$OUT"

# Optional quick sanity listing (non-fatal if unzip missing)
if command -v unzip >/dev/null 2>&1; then
  echo "== ZIP CONTENTS (first 80 lines) =="
  unzip -l "$OUT" | sed -n '1,80p'
fi

echo "OK: source zip created via git archive"
