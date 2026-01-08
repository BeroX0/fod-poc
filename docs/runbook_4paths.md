# SEP400 × Standby — FOD Camera Pack PoC Runbook (4 Paths)

This PoC proves an end-to-end, reproducible chain:

Video (recorded or live) → YOLO detect → ROI gate → event logic → `events.json` → Evidence Builder → `demo_pack.zip`

Non-negotiable correctness:
- event timing must align to the MP4 timebase
- `representative_bbox` must be full-frame pixels (e.g., 1920×1080)
- Evidence Builder must resolve all rows (`index validation PASS: N/N`)

---

## 0) Canonical locations

### PC/WSL (user: `beros`)
Repo:
- `/home/beros/projects/fod_poc/repo/sep400-standby-fod-poc`

Evidence Builder runtime workspace (not tracked in git):
- `/home/beros/projects/fod_poc/workspace/evidence_builder`

Compatibility alias (must be symlink):
- `/home/beros/evidence_builder` → `/home/beros/projects/fod_poc/workspace/evidence_builder`

Models (PC):
- `/home/beros/projects/fod_poc/models/yolov8n.pt`
- `/home/beros/projects/fod_poc/models/fod_1class_best.pt`

ROIs (in repo):
- `pc_wsl/events/rois/*.json`

PC venv:
- `/home/beros/projects/fod_poc/venv/pc_train`

### Jetson Orin (user: `fod`)
Repo:
- `/home/fod/projects/fod_poc/repo/sep400-standby-fod-poc`

Models (Jetson):
- `/home/fod/projects/fod_poc/models/yolov8n.pt`
- `/home/fod/projects/fod_poc/models/fod_1class_best.pt`

Runtime outputs (never commit):
- `/data/live_runs/{videos,events,logs}`

Jetson venv:
- `/home/fod/projects/fod_poc/venv/jetson_live`

---

## 1) Evidence Builder usage (PC)

Evidence Builder inputs:
- MP4(s) must exist in: `/home/beros/evidence_builder/input/`
- Events file must exist at: `/home/beros/evidence_builder/input/events.json`

Run EB (from repo root):
```bash
bash pc_wsl/evidence_builder/run_demo_pack_wsl.sh

