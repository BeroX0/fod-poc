#!/usr/bin/env bash
set -u

# Full Live FOD pipeline:
# 1) live_detect_record_run.py (record MP4 + events.json)
# 2) stage input symlinks for Evidence Builder
# 3) batch_evidence.py  (snapshots + bbox overlays + clips)
# 4) make_demo_pack.py  (zip/index/checksums if your EB script produces them)
# 5) copy EB output into per-run export dir + SHA256SUMS

set -euo pipefail

REPO="${REPO:-/home/fod/projects/fod_poc/repo/sep400-standby-fod-poc}"
VENV="/home/fod/projects/fod_poc/venv/jetson_live"
MODEL="/home/fod/projects/fod_poc/models/fod_1class_best.pt"
ROI_REL="pc_wsl/events/rois/roi_1080p_12mm_roadonly_v1.json"

BASE="/data/live_runs"
LOGS="$BASE/logs"
EVENTS_DIR="$BASE/events"
VIDEOS_DIR="$BASE/videos"

# Long duration so you can stop with q/ESC in the preview (or Ctrl+C if headless)
DURATION_S="${1:-36000}"

mkdir -p "$LOGS" "$EVENTS_DIR" "$VIDEOS_DIR"
sudo chown -R fod:fod "$BASE" || true

RUN_TAG="$(date +%Y%m%d_%H%M%S)"
LOG="$LOGS/live_fod_${RUN_TAG}.log"
EVENTS_OUT="$EVENTS_DIR/events_fod_${RUN_TAG}.json"

echo "[run] RUN_TAG=$RUN_TAG"
echo "[run] LOG=$LOG"
echo "[run] EVENTS_OUT=$EVENTS_OUT"

# Activate env
source "$VENV/bin/activate"
export PYTHONNOUSERSITE=1

# Decide if GUI is actually usable (prevents Qt/XCB crash)
HAS_GUI=0
if [[ -n "${DISPLAY:-}" ]] && command -v xset >/dev/null 2>&1; then
  if xset q >/dev/null 2>&1; then HAS_GUI=1; fi
fi

SHOW_ARGS=()
if [[ "$HAS_GUI" -eq 1 ]]; then
  echo "[ui] GUI detected (DISPLAY=$DISPLAY). Enabling --show. Press q/ESC in the preview window to stop recording."
  SHOW_ARGS+=( --show --show_every_n 1 --show_scale 0.50 --show_window_name "live_fod_${RUN_TAG}" )
else
  echo "[ui] No usable GUI detected. Running headless (no --show)."
  echo "[ui] If you want preview: run this from Jetson desktop terminal (or ensure DISPLAY works for this shell)."
fi

# Run live record+detect
set +e
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
  "${SHOW_ARGS[@]}" \
  2>&1 | tee "$LOG"
LIVE_RC="${PIPESTATUS[0]}"
set -e

echo "[run] live_detect exit_code=$LIVE_RC"

# Extract MP4 path from log (most reliable)
MP4="$(grep -m1 '^\[out\] mp4 = ' "$LOG" | sed 's/^\[out\] mp4 = //')"
if [[ -z "${MP4:-}" ]]; then
  echo "[warn] Could not parse mp4 path from log. Falling back to newest mp4 in $VIDEOS_DIR"
  MP4="$(ls -1t "$VIDEOS_DIR"/live_run_*.mp4 2>/dev/null | head -n 1 || true)"
fi

if [[ -z "${MP4:-}" ]] || [[ ! -f "$MP4" ]]; then
  echo "[error] MP4 missing. Aborting EB. MP4='$MP4'"
  exit 2
fi

if [[ ! -f "$EVENTS_OUT" ]]; then
  echo "[error] EVENTS_OUT missing. Aborting EB. EVENTS_OUT='$EVENTS_OUT'"
  exit 3
fi

MP4_BASENAME="$(basename "$MP4")"
VIDSTAMP="$(echo "$MP4_BASENAME" | sed -n 's/^live_run_\([0-9]\{8\}_[0-9]\{6\}\).*/\1/p')"

EXPORT="$BASE/export_live_fod_${RUN_TAG}"
mkdir -p "$EXPORT/overlays"

# Copy “frozen inputs” to export
cp -f "$MP4" "$EXPORT/$MP4_BASENAME"
cp -f "$EVENTS_OUT" "$EXPORT/events.json"
cp -f "$REPO/$ROI_REL" "$EXPORT/roi.json"
cp -f "$MODEL" "$EXPORT/$(basename "$MODEL")"
cp -f "$LOG" "$EXPORT/run.log"

# Copy overlays that match this video timestamp (if any)
if [[ -n "${VIDSTAMP:-}" ]]; then
  cp -f "$LOGS"/live_rec_detect_overlay_"$VIDSTAMP"_*.jpg "$EXPORT/overlays/" 2>/dev/null || true
fi

# Stage EB input/output in repo (EB scripts default to REPO/input + REPO/output)
mkdir -p "$REPO/input" "$REPO/output"
rm -rf "$REPO/output"/*
mkdir -p "$REPO/output/snapshots" "$REPO/output/clips"

# Ensure input points to this run
rm -f "$REPO/input/events.json"
ln -sf "$EXPORT/events.json" "$REPO/input/events.json"
rm -f "$REPO/input/$MP4_BASENAME"
ln -sf "$EXPORT/$MP4_BASENAME" "$REPO/input/$MP4_BASENAME"

echo "[eb] input/events.json -> $EXPORT/events.json"
echo "[eb] input/$MP4_BASENAME -> $EXPORT/$MP4_BASENAME"

# Run Evidence Builder
echo "[eb] step 1: batch_evidence.py"
python3 "$REPO/pc_wsl/evidence_builder/batch_evidence.py" | tee "$EXPORT/eb_batch.log"

echo "[eb] step 2: make_demo_pack.py"
python3 "$REPO/pc_wsl/evidence_builder/make_demo_pack.py" | tee "$EXPORT/eb_pack.log"


# Copy demo_pack (zip + checksums) into the export folder too
if [[ -d "$REPO/demo_pack" ]]; then
  mkdir -p "$EXPORT/demo_pack"
  rsync -a --delete "$REPO/demo_pack/" "$EXPORT/demo_pack/"
fi

# (optional safety) if a top-level demo_pack.zip ever exists, capture it too
if [[ -f "$REPO/demo_pack.zip" ]]; then
  cp -f "$REPO/demo_pack.zip" "$EXPORT/" || true
fi


# Copy EB outputs into export dir (per-run, no mixing)
mkdir -p "$EXPORT/eb_output"
rsync -a --delete "$REPO/output/" "$EXPORT/eb_output/"

# Write manifest
GIT_HEAD="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo unknown)"
cat > "$EXPORT/MANIFEST.txt" <<EOF
RUN_TAG=$RUN_TAG
GIT_HEAD=$GIT_HEAD
MP4=$MP4_BASENAME
EVENTS=events.json
ROI=$(basename "$ROI_REL")
MODEL=$(basename "$MODEL")
EXPORT_DIR=$EXPORT
EOF

# SHA256 for everything in export dir (deterministic order)
(
  cd "$EXPORT"
  tmp="$(mktemp)"
  find . -type f ! -name "SHA256SUMS.txt" -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > "$tmp"
  mv "$tmp" SHA256SUMS.txt
)

echo
echo "[done] Export folder:"
echo "  $EXPORT"
echo
echo "[done] Quick outputs:"
ls -lh "$EXPORT" | sed -n '1,120p' || true
echo
echo "[done] Snapshots (bbox overlays) example:"
ls -1 "$EXPORT/eb_output/snapshots"/*_bbox.jpg 2>/dev/null | head -n 5 || true
