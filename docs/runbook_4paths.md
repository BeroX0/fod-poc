# SEP400 × Standby — FOD Camera Pack PoC Runbook (4 Paths) — Engineering Reference

**Canonical demo-day docs (single source of truth):**
- Offline demo runbook: `docs/offline_demo_runbook.md`
- Demo day checklist: `docs/demo_day_checklist.md`

**Canonical operator entrypoints (preferred):**
- `tools/verify_offline_fod_pack.sh` — deterministic offline verify → EB → ZIP checksum
- `tools/run_demo_offline_from_bundles.sh` — reproduce demo packs from two frozen bundles
- (Optional) `tools/make_source_zip.sh` — create submission source ZIP via `git archive`

> If this document conflicts with `README.md`, **README wins**. This file is an engineering reference for the “4 paths” concept and legacy/manual commands.

---

## Verification status (truth claims)
This table is intentionally conservative. Update evidence locations when you freeze/verify.

| Path | Status | Evidence | Notes |
|---|---|---|---|
| Offline + FOD | Verified / Golden (frozen bundles) | `workspace/freeze_bundles/golden_offline_*` (outside git) | Use canonical tools scripts. |
| Offline + COCO | Implemented / optional verification | See commands below | Not required for the golden offline demo unless explicitly needed. |
| Live + FOD | Implemented; verify separately | `/data/live_runs/...` (Jetson) + EB output (PC) | Not part of the offline golden demo. |
| Live + COCO | Implemented; verify separately | `/data/live_runs/...` (Jetson) + EB output (PC) | Not part of the offline golden demo. |

---

## 0) Canonical locations

### PC/WSL (user: `beros`)
Repo:
- `/home/beros/projects/fod_poc/repo/sep400-standby-fod-poc`

Evidence Builder runtime workspace (NOT tracked in git):
- `/home/beros/projects/fod_poc/workspace/evidence_builder`

Compatibility alias (optional symlink):
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

## 1) Evidence Builder (EB) usage (PC)

EB inputs:
- MP4 must exist under: `$EVIDENCE_DIR/input/`
- Events file must exist at: `$EVIDENCE_DIR/input/events.json`

Run EB (from repo root):

```bash
export EVIDENCE_DIR="/home/beros/projects/fod_poc/workspace/evidence_builder"
mkdir -p "$EVIDENCE_DIR/input"

bash pc_wsl/evidence_builder/run_demo_pack_wsl.sh
Expected outputs:

$EVIDENCE_DIR/demo_pack.zip

$EVIDENCE_DIR/demo_pack.zip.sha256

$EVIDENCE_DIR/output/index.csv

$EVIDENCE_DIR/output/snapshots/*_bbox.jpg

PASS criteria:

EB prints: index validation PASS: N/N

Visual check: bbox snapshots align to the object.

2) Canonical demo-day offline entrypoints (preferred)
2.1 Reproduce the golden offline demo (two frozen bundles)
Use:

docs/offline_demo_runbook.md

docs/demo_day_checklist.md

Primary runner:

bash tools/run_demo_offline_from_bundles.sh \
  --bundle103 /path/to/offline_fod_run_103012 \
  --bundle106 /path/to/offline_fod_run_106012 \
  --out /tmp/fod_demo_run
2.2 Verify a single offline run deterministically (FOD)
Primary verifier:

bash tools/verify_offline_fod_pack.sh \
  --video /path/to/run_103012.mp4 \
  --model /path/to/fod_1class_best.pt \
  --roi   pc_wsl/events/rois/roi_1080p_12mm_roadonly_v1.json \
  --work  /tmp/verify_one
3) Profiles (4 paths) — engineering reference / manual commands
These are manual paths. Prefer the canonical tools above for demo-day reproducibility.

Profile 1 — OFFLINE + COCO (PC/WSL) (manual)
cd /home/beros/projects/fod_poc/repo/sep400-standby-fod-poc
source /home/beros/projects/fod_poc/venv/pc_train/bin/activate
export PYTHONNOUSERSITE=1

export EVIDENCE_DIR="/home/beros/projects/fod_poc/workspace/evidence_builder"
mkdir -p "$EVIDENCE_DIR/input"

python3 pc_wsl/offline/offline_detect_run_coco.py \
  --video "$EVIDENCE_DIR/input/run_106012.mp4" \
  --model /home/beros/projects/fod_poc/models/yolov8n.pt \
  --roi pc_wsl/events/rois/roi_1080p_12mm_roadonly_v1.json \
  --events_out "$EVIDENCE_DIR/input/events.json" \
  --imgsz 1280 --conf 0.25 --rep_conf 0.25 \
  --min_area 2000 --confirm_n 2 --end_miss_m 10 \
  --min_event_dur_s 0.25 --cooldown_s 0.5

bash pc_wsl/evidence_builder/run_demo_pack_wsl.sh
PASS criteria:

index validation PASS: N/N

bbox snapshots align.

Profile 2 — OFFLINE + FOD 1-CLASS (PC/WSL) (manual)
cd /home/beros/projects/fod_poc/repo/sep400-standby-fod-poc
source /home/beros/projects/fod_poc/venv/pc_train/bin/activate
export PYTHONNOUSERSITE=1

export EVIDENCE_DIR="/home/beros/projects/fod_poc/workspace/evidence_builder"
mkdir -p "$EVIDENCE_DIR/input"

python3 pc_wsl/offline/offline_detect_run.py \
  --video "$EVIDENCE_DIR/input/run_103012.mp4" \
  --model /home/beros/projects/fod_poc/models/fod_1class_best.pt \
  --roi pc_wsl/events/rois/roi_1080p_12mm_roadonly_v1.json \
  --events_out "$EVIDENCE_DIR/input/events.json" \
  --imgsz 1280 --conf 0.25 --rep_conf 0.25 \
  --min_area 2000 --confirm_n 2 --end_miss_m 10 \
  --min_event_dur_s 0.25 --cooldown_s 0.5

bash pc_wsl/evidence_builder/run_demo_pack_wsl.sh
Profile 3 — LIVE + COCO (Jetson) (manual)
cd /home/fod/projects/fod_poc/repo/sep400-standby-fod-poc
source /home/fod/projects/fod_poc/venv/jetson_live/bin/activate
export PYTHONNOUSERSITE=1

sudo mkdir -p /data/live_runs/{videos,events,logs}
sudo chown -R fod:fod /data/live_runs

RUN_TAG=$(date +%Y%m%d_%H%M%S)

python3 jetson/live_detection/live_detect_record_run.py \
  --duration_s 60 \
  --model /home/fod/projects/fod_poc/models/yolov8n.pt \
  --roi pc_wsl/events/rois/roi_1080p_12mm_v1.json \
  --events_out /data/live_runs/events/events_coco_${RUN_TAG}.json \
  --logs_dir /data/live_runs/logs \
  --videos_dir /data/live_runs/videos \
  --conf 0.25 --min_area 2000 --confirm_n 2 --end_miss_m 10 \
  --min_event_dur_s 0.25 --cooldown_s 1.0 --save_every_n 120
Export and run EB on PC:

Copy MP4 + events.json to $EVIDENCE_DIR/input/

Run bash pc_wsl/evidence_builder/run_demo_pack_wsl.sh

Profile 4 — LIVE + FOD 1-CLASS (Jetson) (manual)
Same as Profile 3, but swap the model + ROI, and output name:

RUN_TAG=$(date +%Y%m%d_%H%M%S)

python3 jetson/live_detection/live_detect_record_run.py \
  --duration_s 60 \
  --model /home/fod/projects/fod_poc/models/fod_1class_best.pt \
  --roi pc_wsl/events/rois/roi_1080p_12mm_roadonly_v1.json \
  --events_out /data/live_runs/events/events_fod_${RUN_TAG}.json \
  --logs_dir /data/live_runs/logs \
  --videos_dir /data/live_runs/videos \
  --conf 0.25 --min_area 2000 --confirm_n 2 --end_miss_m 10 \
  --min_event_dur_s 0.25 --cooldown_s 1.0 --save_every_n 120
4) Non-negotiable correctness (all paths)
event timing aligns to MP4 timebase (PTS-aligned)

representative_bbox uses full-frame pixels (e.g., 1920×1080)

Evidence Builder resolves all rows: index validation PASS: N/N
