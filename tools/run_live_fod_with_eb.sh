#!/usr/bin/env bash
set -euo pipefail

REPO="/home/fod/projects/fod_poc/repo/sep400-standby-fod-poc"
VENV="/home/fod/projects/fod_poc/venv/jetson_live/bin/activate"

MODEL="/home/fod/projects/fod_poc/models/fod_1class_best.pt"
ROI_REL="pc_wsl/events/rois/roi_1080p_12mm_roadonly_v1.json"

DURATION_S="${1:-90}"

OUT_ROOT="/data/live_runs"
LOGS="$OUT_ROOT/logs"
EVENTS_DIR="$OUT_ROOT/events"
VIDEOS_DIR="$OUT_ROOT/videos"
EB_WORK_ROOT="$OUT_ROOT/eb_work"

mkdir -p "$LOGS" "$EVENTS_DIR" "$VIDEOS_DIR" "$EB_WORK_ROOT"
# optional (keeps perms clean if you run as fod)
sudo chown -R fod:fod "$OUT_ROOT" >/dev/null 2>&1 || true

source "$VENV"
export PYTHONNOUSERSITE=1

RUN_TAG="$(date +%Y%m%d_%H%M%S)"
export RUN_TAG
LOG="$LOGS/live_fod_${RUN_TAG}.log"
EVENTS_OUT="$EVENTS_DIR/events_fod_${RUN_TAG}.json"

echo "[run] RUN_TAG=$RUN_TAG"
echo "[run] LOG=$LOG"
echo "[run] EVENTS_OUT=$EVENTS_OUT"

# --- LIVE RUN (record + detect) ---
python3 -u "$REPO/jetson/live_detection/live_detect_record_run.py" \
  --duration_s "$DURATION_S" \
  --model "$MODEL" \
  --roi "$REPO/$ROI_REL" \
  --events_out "$EVENTS_OUT" \
  --logs_dir "$LOGS" \
  --videos_dir "$VIDEOS_DIR" \
  --conf 0.25 --imgsz 416 \
  --min_area 2000 --confirm_n 2 --end_miss_m 10 \
  --min_event_dur_s 0.25 --cooldown_s 1.0 \
  --width 1920 --height 1080 --fps_num 30 --fps_den 1 --tuned_camera \
  --show --show_every_n 1 --show_scale 0.50 \
  2>&1 | tee "$LOG"

# --- PARSE OUTPUTS (authoritative) ---
MP4="$(grep -m1 '^\[done\] mp4 = ' "$LOG" | sed 's/^\[done\] mp4 = //')"
EVT="$(grep -m1 '^\[done\] events = ' "$LOG" | sed 's/^\[done\] events = //')"

# fallback if needed
if [[ -z "${MP4:-}" ]]; then
  MP4="$(grep -m1 '^\[out\] mp4 = ' "$LOG" | sed 's/^\[out\] mp4 = //')"
fi
if [[ -z "${EVT:-}" ]]; then
  EVT="$(grep -m1 '^\[out\] events = ' "$LOG" | sed 's/^\[out\] events = //')"
fi

echo "[post] MP4=$MP4"
echo "[post] EVT=$EVT"

if [[ ! -f "$MP4" ]]; then
  echo "ERROR: MP4 not found: $MP4" >&2
  exit 2
fi
if [[ ! -f "$EVT" ]]; then
  echo "ERROR: events.json not found: $EVT" >&2
  exit 3
fi

# --- EVIDENCE BUILDER (run in isolated workdir, no repo pollution) ---
WORK="$EB_WORK_ROOT/live_fod_${RUN_TAG}"
mkdir -p "$WORK/input"
ln -sf "$EVT" "$WORK/input/events.json"
ln -sf "$MP4" "$WORK/input/$(basename "$MP4")"
ln -sf "$REPO/$ROI_REL" "$WORK/input/roi.json"

echo "[eb] workdir=$WORK"
echo "[eb] running make_demo_pack.py ..."
( cd "$WORK" && python3 "$REPO/pc_wsl/evidence_builder/make_demo_pack.py" ) 2>&1 | tee "$WORK/eb.log"

echo "[eb] copy demo_pack -> export"
if [[ -d "$REPO/demo_pack" ]]; then
  rsync -a --delete "$REPO/demo_pack/" "$EXPORT/demo_pack/"
else
  echo "[eb] WARNING: $REPO/demo_pack not found (make_demo_pack may have failed)"
fi


echo
echo "=== Evidence outputs (newest) ==="
find "$WORK" -type f \( -iname "*.jpg" -o -iname "*.png" -o -iname "*.mp4" -o -iname "*.zip" -o -iname "*.csv" -o -iname "*.json" \) \
  -printf "%T@ %p\n" | sort -n | tail -n 40 | sed 's/^[0-9.]* //'

echo
echo "[done] EB workdir: $WORK"
echo "[hint] If you want to view snapshots from PC:"
echo "       ssh fod@100.119.10.42 'cd $WORK && python3 -m http.server 8011 --bind 0.0.0.0'"
echo "       then open: http://100.119.10.42:8011/"
