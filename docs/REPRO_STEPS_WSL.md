# Repro Steps — PC/WSL (baseline YOLO + events)

This is the minimal reproducible path to regenerate outputs from an exported dataset.

## Preconditions
- Dataset export exists outside Git (MP4s not committed)
- Python venv is created (recommended: `~/projects/.venv_fod`)

## 1) Set paths (outside git)
```bash
export FOD_EXPORT_ROOT="$HOME/projects/exports/fod_poc_2025_20251216"
export FOD_OUT_ROOT="$HOME/projects/fod_outputs"
```

## 2) Activate venv
```bash
source ~/projects/.venv_fod/bin/activate
```

## 3) Run offline inference (one video example)
```bash
VID="$FOD_EXPORT_ROOT/videos/run_106012.mp4"

python pc_wsl/offline_infer/offline_infer.py \
  --video "$VID" \
  --outdir "$FOD_OUT_ROOT" \
  --model yolov8n.pt \
  --device 0 \
  --conf 0.25 \
  --imgsz 640 \
  --run-tag y8_conf025_img640
```

## 4) Run ROI + events
```bash
RUN_FOLDER="$FOD_OUT_ROOT/run_106012__y8_conf025_img640"
ROI_JSON="pc_wsl/events/rois/roi_1080p_12mm_roadonly_v1.json"

python pc_wsl/events/events_from_detections.py \
  --run-folder "$RUN_FOLDER" \
  --roi "$ROI_JSON" \
  --conf 0.15 \
  --dist-px 120 \
  --gap-frames 2 \
  --track-mode class \
  --persist-mode consecutive \
  --n-consec 2
```

## Outputs
- `$RUN_FOLDER/detections.csv`
- `$RUN_FOLDER/detections.jsonl`
- `$RUN_FOLDER/summary.json`
- `$RUN_FOLDER/events/<roi_id>/events.csv|events.json|metrics.json`

## Deactivate
```bash
deactivate
```
