#!/usr/bin/env bash
set -euo pipefail

# Profiles on PC:
#   1 = Offline + COCO -> EB
#   2 = Offline + FOD  -> EB
#   eb = EB only (assumes input/events.json + referenced MP4 already exist)
#
# Optional tuning flags for profiles 1/2 (passed to offline runner if provided):
#   --roi <path>
#   --conf <float> --rep-conf <float>
#   --min-area <int> --confirm-n <int> --end-miss-m <int>
#   --min-event-dur-s <float> --cooldown-s <float> --max-frames <int>

PROFILE="${1:-}"
if [[ -z "${PROFILE}" ]]; then
  echo "USAGE: $0 <1|2|eb> [--video /path/to.mp4] [tuning flags...]"
  exit 2
fi
shift || true

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EB_RUNNER="$REPO_ROOT/pc_wsl/evidence_builder/run_demo_pack_wsl.sh"

EVIDENCE_DIR="${EVIDENCE_DIR:-$HOME/evidence_builder}"
INPUT_DIR="$EVIDENCE_DIR/input"
EVENTS_JSON="$INPUT_DIR/events.json"

PC_MODELS_DIR="${PC_MODELS_DIR:-$HOME/projects/fod_poc/models}"

COCO_MODEL="${COCO_MODEL:-$PC_MODELS_DIR/yolov8n.pt}"
FOD_MODEL="${FOD_MODEL:-$PC_MODELS_DIR/fod_1class_best.pt}"

DEFAULT_ROI="$REPO_ROOT/pc_wsl/events/rois/roi_1080p_12mm_roadonly_v1.json"

VIDEO=""
ROI="$DEFAULT_ROI"
CONF=""
REP_CONF=""
MIN_AREA=""
CONFIRM_N=""
END_MISS_M=""
MIN_EVENT_DUR_S=""
COOLDOWN_S=""
MAX_FRAMES=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --video) VIDEO="${2:-}"; shift 2;;
    --roi) ROI="${2:-}"; shift 2;;
    --conf) CONF="${2:-}"; shift 2;;
    --rep-conf) REP_CONF="${2:-}"; shift 2;;
    --min-area) MIN_AREA="${2:-}"; shift 2;;
    --confirm-n) CONFIRM_N="${2:-}"; shift 2;;
    --end-miss-m) END_MISS_M="${2:-}"; shift 2;;
    --min-event-dur-s) MIN_EVENT_DUR_S="${2:-}"; shift 2;;
    --cooldown-s) COOLDOWN_S="${2:-}"; shift 2;;
    --max-frames) MAX_FRAMES="${2:-}"; shift 2;;
    *) echo "WARN: ignoring unknown arg: $1"; shift;;
  esac
done

echo "[pc] REPO_ROOT=$REPO_ROOT"
echo "[pc] EVIDENCE_DIR=$EVIDENCE_DIR"
echo "[pc] PROFILE=$PROFILE"

command -v python3 >/dev/null || { echo "ERROR: python3 not found"; exit 2; }
command -v ffmpeg >/dev/null || { echo "ERROR: ffmpeg not found"; exit 2; }

[[ -d "$INPUT_DIR" ]] || { echo "ERROR: Missing $INPUT_DIR"; exit 2; }

copy_into_input() {
  local src="$1"
  local base
  base="$(basename "$src")"
  local dst="$INPUT_DIR/$base"
  if [[ ! -f "$src" ]]; then
    echo "ERROR: video not found: $src"
    exit 2
  fi
  if [[ "$src" != "$dst" ]]; then
    echo "[pc] Copying MP4 into EB input/: $src -> $dst"
    cp -f "$src" "$dst"
  else
    echo "[pc] MP4 already in EB input/: $dst"
  fi
  echo "$dst"
}

run_eb() {
  echo "[eb] Running Evidence Builder..."
  EVIDENCE_DIR="$EVIDENCE_DIR" bash "$EB_RUNNER"
  echo "[eb] DONE. demo_pack.zip:"
  ls -la "$EVIDENCE_DIR/demo_pack.zip" "$EVIDENCE_DIR/demo_pack.zip.sha256" 2>/dev/null || true
}

validate_events_video_match() {
  python3 - <<PY
import json
from pathlib import Path
p = Path("$EVENTS_JSON")
if not p.exists():
    raise SystemExit("ERROR: events.json missing: " + str(p))
d = json.loads(p.read_text())
if not isinstance(d, list):
    raise SystemExit("ERROR: events.json is not a list")
if not d:
    raise SystemExit("ERROR: events.json is empty list")
vf = d[0].get("video_filename")
if not vf:
    raise SystemExit("ERROR: video_filename missing in first event")
mp4 = Path("$INPUT_DIR") / vf
if not mp4.exists():
    raise SystemExit(f"ERROR: MP4 not found in input/: {mp4}")
print("OK: events.json references existing MP4:", mp4)
PY
}

build_tuning_args() {
  local -a a=()
  [[ -n "$ROI" ]] && a+=("--roi" "$ROI")
  [[ -n "$CONF" ]] && a+=("--conf" "$CONF")
  [[ -n "$REP_CONF" ]] && a+=("--rep_conf" "$REP_CONF")
  [[ -n "$MIN_AREA" ]] && a+=("--min_area" "$MIN_AREA")
  [[ -n "$CONFIRM_N" ]] && a+=("--confirm_n" "$CONFIRM_N")
  [[ -n "$END_MISS_M" ]] && a+=("--end_miss_m" "$END_MISS_M")
  [[ -n "$MIN_EVENT_DUR_S" ]] && a+=("--min_event_dur_s" "$MIN_EVENT_DUR_S")
  [[ -n "$COOLDOWN_S" ]] && a+=("--cooldown_s" "$COOLDOWN_S")
  [[ -n "$MAX_FRAMES" ]] && a+=("--max_frames" "$MAX_FRAMES")
  printf "%q " "${a[@]}"
}

case "$PROFILE" in
  1)
    [[ -n "$VIDEO" ]] || { echo "ERROR: Profile 1 requires --video /path/to.mp4"; exit 2; }
    [[ -f "$COCO_MODEL" ]] || { echo "ERROR: Missing COCO model: $COCO_MODEL"; exit 2; }
    [[ -f "$ROI" ]] || { echo "ERROR: Missing ROI: $ROI"; exit 2; }

    DST_VIDEO="$(copy_into_input "$VIDEO")"

    echo "[p1] Offline COCO -> events.json"
    echo "[p1] model=$COCO_MODEL"
    echo "[p1] roi=$ROI"
    echo "[p1] tuning=$(build_tuning_args)"
    python3 "$REPO_ROOT/pc_wsl/offline/offline_detect_run_coco.py" \
      --video "$DST_VIDEO" \
      --model "$COCO_MODEL" \
      --events_out "$EVENTS_JSON" \
      $(build_tuning_args)

    validate_events_video_match
    run_eb
    ;;

  2)
    [[ -n "$VIDEO" ]] || { echo "ERROR: Profile 2 requires --video /path/to.mp4"; exit 2; }
    [[ -f "$FOD_MODEL" ]] || { echo "ERROR: Missing FOD model: $FOD_MODEL"; exit 2; }
    [[ -f "$ROI" ]] || { echo "ERROR: Missing ROI: $ROI"; exit 2; }

    [[ -f "$REPO_ROOT/pc_wsl/offline/offline_detect_run.py" ]] || {
      echo "ERROR: Missing offline FOD runner: $REPO_ROOT/pc_wsl/offline/offline_detect_run.py"
      exit 2
    }

    DST_VIDEO="$(copy_into_input "$VIDEO")"

    echo "[p2] Offline FOD -> events.json"
    echo "[p2] model=$FOD_MODEL"
    echo "[p2] roi=$ROI"
    echo "[p2] tuning=$(build_tuning_args)"
    python3 "$REPO_ROOT/pc_wsl/offline/offline_detect_run.py" \
      --video "$DST_VIDEO" \
      --model "$FOD_MODEL" \
      --events_out "$EVENTS_JSON" \
      $(build_tuning_args)

    validate_events_video_match
    run_eb
    ;;

  eb)
    validate_events_video_match
    run_eb
    ;;

  *)
    echo "ERROR: Unknown profile: $PROFILE"
    exit 2
    ;;
esac
