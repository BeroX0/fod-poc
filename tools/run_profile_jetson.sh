#!/usr/bin/env bash
set -euo pipefail

# Profiles on Jetson:
#   3 = Live + COCO -> export bundle
#   4 = Live + FOD  -> export bundle
# Optional: --serve to host the export folder over HTTP.

PROFILE="${1:-}"
if [[ -z "${PROFILE}" ]]; then
  echo "USAGE: $0 <3|4> [--duration 60] [--serve] [--port 8000]"
  exit 2
fi
shift || true

DURATION="60"
SERVE="0"
PORT="8000"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --duration) DURATION="${2:-60}"; shift 2;;
    --serve) SERVE="1"; shift;;
    --port) PORT="${2:-8000}"; shift 2;;
    *) echo "ERROR: unknown arg: $1"; exit 2;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIVE="$REPO_ROOT/jetson/live_detection/live_detect_record_run.py"

MODELS_DIR="${MODELS_DIR:-$HOME/projects/fod_poc/models}"
COCO_MODEL="${COCO_MODEL:-$MODELS_DIR/yolov8n.pt}"
FOD_MODEL="${FOD_MODEL:-$MODELS_DIR/fod_1class_best.pt}"

# Default ROI: road-only v1 (exists in repo). Override via ROI=...
ROI="${ROI:-$REPO_ROOT/pc_wsl/events/rois/roi_1080p_12mm_roadonly_v1.json}"

RUN_TAG="$(date +%Y%m%d_%H%M%S)"
VIDEOS_DIR="/data/live_runs/videos"
EVENTS_DIR="/data/live_runs/events"
LOGS_DIR="/data/live_runs/logs"
EXPORT="/data/live_runs/export_${RUN_TAG}_p${PROFILE}"

echo "[jetson] PROFILE=$PROFILE RUN_TAG=$RUN_TAG duration=$DURATION serve=$SERVE port=$PORT"
echo "[jetson] REPO_ROOT=$REPO_ROOT"
echo "[jetson] ROI=$ROI"

sudo mkdir -p "$VIDEOS_DIR" "$EVENTS_DIR" "$LOGS_DIR" /data/live_runs
sudo chown -R "$(whoami)":"$(whoami)" /data/live_runs

MODEL=""
EVENTS_OUT=""
case "$PROFILE" in
  3)
    MODEL="$COCO_MODEL"
    EVENTS_OUT="$EVENTS_DIR/events_coco_${RUN_TAG}.json"
    ;;
  4)
    MODEL="$FOD_MODEL"
    EVENTS_OUT="$EVENTS_DIR/events_fod_${RUN_TAG}.json"
    ;;
  *)
    echo "ERROR: Unknown profile: $PROFILE (use 3 or 4)"
    exit 2
    ;;
esac

[[ -f "$MODEL" ]] || { echo "ERROR: missing model: $MODEL"; exit 2; }
[[ -f "$ROI" ]]   || { echo "ERROR: missing ROI: $ROI"; exit 2; }
[[ -f "$LIVE" ]]  || { echo "ERROR: missing live script: $LIVE"; exit 2; }

echo "[run] live_detect_record_run.py -> $EVENTS_OUT"
python3 "$LIVE" \
  --duration_s "$DURATION" \
  --model "$MODEL" \
  --roi "$ROI" \
  --events_out "$EVENTS_OUT" \
  --logs_dir "$LOGS_DIR" \
  --videos_dir "$VIDEOS_DIR" \
  --conf 0.25 \
  --min_area 1200 \
  --confirm_n 2 \
  --end_miss_m 5 \
  --min_event_dur_s 0.20 \
  --cooldown_s 0.75 \
  --save_every_n 30

echo "[export] building bundle: $EXPORT"
mkdir -p "$EXPORT"

MP4="$(ls -t "$VIDEOS_DIR"/live_run_*.mp4 | head -n 1)"
cp -v "$MP4" "$EXPORT/"
cp -v "$EVENTS_OUT" "$EXPORT/events.json"
( cd "$EXPORT" && sha256sum events.json "$(basename "$MP4")" > SHA256SUMS.txt )

echo "EXPORT READY: $EXPORT"
ls -la "$EXPORT"
echo "== SHA256SUMS.txt =="
cat "$EXPORT/SHA256SUMS.txt"

if [[ "$SERVE" == "1" ]]; then
  echo "[serve] Serving $EXPORT on http://0.0.0.0:${PORT}/ (Ctrl+C to stop)"
  cd "$EXPORT"
  python3 -m http.server "$PORT" --bind 0.0.0.0
fi
