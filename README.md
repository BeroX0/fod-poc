# SEP400 × Standby — FOD Camera Pack PoC

This repository packages a reproducible Proof-of-Concept (PoC) pipeline for detecting FOD-like objects in a runway-like scenario using a car-mounted Jetson camera pack.

Pipeline:
1) Jetson records 1080p road videos (GStreamer, H.264, splitmuxsink)
2) PC/WSL runs offline inference (Ultralytics YOLO baseline)
3) ROI + events runner produces deterministic alarm/event outputs (CSV/JSON + metrics)

This repo contains code, ROI definitions, and documentation.
It intentionally does not include MP4 datasets or large generated outputs.

## Repository contents
- jetson/ — recording helpers + notes for Jetson Orin Nano
- pc_wsl/ — offline inference + ROI/events runner (primary development)
- docs/ — data layout, environments, reproducibility notes
- tests/ — tiny synthetic fixtures for CI (no real videos)

## What must NOT be committed
- MP4 videos (run_*.mp4)
- Dataset exports (e.g., ~/projects/exports/...)
- Generated outputs (e.g., ~/projects/fod_outputs/...)
- Large logs (real detections.jsonl)
- Model weights (*.pt, *.engine)
- Secrets (tokens, credentials, invite links, IPs)

## Quickstart (PC/WSL)

### 0) Set local paths (outside git)
Set these to match your machine:

```bash
export FOD_EXPORT_ROOT="$HOME/projects/exports/fod_poc_2025_20251216"
export FOD_OUT_ROOT="$HOME/projects/fod_outputs"



```

Verified on your machine:
- Videos are under: `$FOD_EXPORT_ROOT/videos/run_*.mp4`
- Outputs are created under: `$FOD_OUT_ROOT/` (per-run folders)

### 1) Activate your venv
```bash
source ~/projects/.venv_fod/bin/activate
```

### 2) Offline inference
Note: scripts will be added under pc_wsl/offline_infer/ in Phase 2.

### 3) ROI + events extraction
Note: scripts will be added under pc_wsl/events/ in Phase 2.

## Jetson recording
See: jetson/recording/README.md

## Reproducibility
- Code + ROI JSONs are version-controlled in Git.
- Datasets and outputs are stored locally (outside Git) and referenced via CLI args / env vars.
- Environment fingerprints and data layout are documented in docs/.
