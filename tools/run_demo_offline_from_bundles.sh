#!/usr/bin/env bash
set -euo pipefail

[[ -n "${BASH_VERSION:-}" ]] || { echo "ERROR: run with bash"; exit 2; }

# Runs the repo's verification tool against TWO extracted bundle directories.
#
# Example:
#   bash tools/run_demo_offline_from_bundles.sh \
#     --bundle103 /path/to/offline_fod_run_103012 \
#     --bundle106 /path/to/offline_fod_run_106012 \
#     --out /tmp/demo_run
#
# Output:
#   <out>/work_run_103012/demo_pack.zip
#   <out>/work_run_106012/demo_pack.zip

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

B103=""
B106=""
OUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bundle103) B103="$2"; shift 2;;
    --bundle106) B106="$2"; shift 2;;
    --out)       OUT="$2"; shift 2;;
    --help|-h)
      cat <<'USAGE'
Usage:
  bash tools/run_demo_offline_from_bundles.sh \
    --bundle103 /path/to/offline_fod_run_103012 \
    --bundle106 /path/to/offline_fod_run_106012 \
    --out /tmp/demo_run

Output:
  <out>/work_run_103012/demo_pack.zip
  <out>/work_run_106012/demo_pack.zip
USAGE
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 2;;
  esac
done

[[ -n "$B103" && -n "$B106" && -n "$OUT" ]] || { echo "ERROR: missing args. Use --help." >&2; exit 2; }
[[ -d "$B103" ]] || { echo "Missing bundle103 dir: $B103" >&2; exit 2; }
[[ -d "$B106" ]] || { echo "Missing bundle106 dir: $B106" >&2; exit 2; }

run_one () {
  local B="$1"
  local NAME="$2"
  local WORK="$OUT/$NAME"
  mkdir -p "$WORK"

  local VIDEO MODEL ROI
  VIDEO="$(ls -1 "$B"/run_*.mp4 2>/dev/null | head -n 1 || true)"
  MODEL="$B/fod_1class_best.pt"
  ROI="$(ls -1 "$B"/roi_*.json 2>/dev/null | head -n 1 || true)"

  [[ -f "$VIDEO" ]] || { echo "ERROR: bundle missing run_*.mp4: $B" >&2; exit 2; }
  [[ -f "$MODEL" ]] || { echo "ERROR: bundle missing fod_1class_best.pt: $B" >&2; exit 2; }
  [[ -f "$ROI"   ]] || { echo "ERROR: bundle missing roi_*.json: $B" >&2; exit 2; }

  echo "== RUN $NAME =="
  echo "BUNDLE: $B"
  echo "VIDEO:  $VIDEO"
  echo "MODEL:  $MODEL"
  echo "ROI:    $ROI"
  echo "WORK:   $WORK"
  echo

  bash "$REPO_ROOT/tools/verify_offline_fod_pack.sh" \
    --video "$VIDEO" \
    --model "$MODEL" \
    --roi   "$ROI" \
    --work  "$WORK"

  echo
  echo "== RESULT $NAME =="
  ls -lah "$WORK/demo_pack.zip" "$WORK/demo_pack.zip.sha256" "$WORK/verification/verify_log.txt"
  ( cd "$WORK" && sha256sum -c demo_pack.zip.sha256 )
  echo
}

mkdir -p "$OUT"
run_one "$B103" "work_run_103012"
run_one "$B106" "work_run_106012"

echo "DONE: $OUT"
