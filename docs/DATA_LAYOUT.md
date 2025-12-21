# Data Layout (Phase 0)

This document records the verified locations of dataset, exports, and outputs.

## Jetson (NVMe rootfs)
- Recordings: `/data/recordings/`
- Canonical dataset root: `/data/datasets/fod_poc_2025/`
  - `videos/` (14 run_*.mp4)
  - `manifests/`
  - `notes/`
  - `checksums/`

## USB export (from Jetson)
- Export folder example: `fod_poc_2025_20251216/`
  - `videos/`, `manifests/`, `notes/`, `checksums/`

## PC/WSL (primary development)
- Dataset export path (outside Git):
  - `~/projects/exports/fod_poc_2025_20251216/videos/run_*.mp4`
- Outputs root (outside Git):
  - `~/projects/fod_outputs/`
  - Run folder examples observed:
    - `run_106012__y8_conf025_img640/`
    - `run_106012__y11_conf025_img640/`
    - plus untagged run folders also exist
- ROI JSONs (versioned): `~/projects/rois/` (will be moved into repo in Phase 2)
