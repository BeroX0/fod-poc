# Jetson Live Detection (MVP) — SEP400 × Standby FOD PoC

This folder implements the minimum viable **Jetson-side live detection loop** that outputs an
**Evidence Builder (EB) compatible** `events.json` and references recorded MP4 segments.

## Non-negotiable contracts

- Repo is authoritative: code must live here and be committed.
- Runtime artifacts MUST NOT be committed.
- ROI + bbox coordinates written to `events.json` must be interpretable as **full-frame 1920×1080 pixels**.
- If inference uses letterbox/resize, bbox MUST be mapped back to 1920×1080 before writing events.

## Canonical workspace paths

- Repo root: `~/projects/fod_poc/repo/sep400-standby-fod-poc`
- ROI folder (flattened): `~/projects/fod_poc/assets/rois/`
- Evidence Builder runtime workspace: `~/projects/fod_poc/workspace/evidence_builder/` (symlink: `~/evidence_builder`)

## Jetson runtime directory

Default runtime root:
- `/data/live_runs/`
  - `videos/` recorded clips/segments (Phase 5)
  - `events/events.json`
  - `logs/` debug artifacts

## Phase 0 (scaffolding)

Phase 0 does NOT run camera or YOLO. It verifies:
- ROI file can be loaded by `roi_id`
- `events.json` writer exists (schema will be locked to EB in Step 0.7)

### Create a dummy events.json (no camera)

```bash
cd ~/projects/fod_poc/repo/sep400-standby-fod-poc/jetson/live_detection
python3 live_detect.py --roi-id <ROI_ID> --debug --phase0-generate-dummy

