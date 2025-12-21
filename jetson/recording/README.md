# Jetson — Recording

This folder documents Jetson Orin Nano recording for the SEP400 × Standby FOD PoC.

## Confirmed paths (Jetson)
- Recordings: `/data/recordings/`
- Canonical dataset root: `/data/datasets/fod_poc_2025/`
  - `videos/`, `manifests/`, `notes/`, `checksums/`

## GStreamer environment (observed)
- Ubuntu 22.04.5 LTS (Jetson)
- GStreamer 1.20.3
- `nvarguscamerasrc`: OK

## Notes
- The camera tuning app generates valid `gst-launch-1.0` commands (copy/paste).
- Do not hardcode absolute paths in scripts; keep paths configurable.
