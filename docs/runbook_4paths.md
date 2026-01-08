# SEP400 × Standby — FOD Camera Pack PoC Runbook (4 Paths)

This PoC proves an end-to-end, reproducible chain:

Video (recorded or live) → YOLO detect → ROI gate → event logic → `events.json` → Evidence Builder → `demo_pack.zip`

Non-negotiable correctness:
- event timing must align to the MP4 timebase (PTS-aligned)
- `representative_bbox` must be **full-frame pixels** (e.g., 1920×1080)
- Evidence Builder must resolve all rows (`index validation PASS: N/N`)

---

## 0) Canonical locations

### PC/WSL (user: `beros`)
Repo:
- `/home/beros/projects/fod_poc/repo/sep400-standby-fod-poc`

Evidence Builder runtime workspace (NOT tracked in git):
- `/home/beros/projects/fod_poc/workspace/evidence_builder`

Compatibility alias (recommended symlink):
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
- MP4(s) must exist in: `/home/beros/evidence_builder/input/`
- Events file must exist at: `/home/beros/evidence_builder/input/events.json`

Run EB (from repo root):
```bash
bash pc_wsl/evidence_builder/run_demo_pack_wsl.sh
Expected outputs:

/home/beros/evidence_builder/demo_pack.zip

/home/beros/evidence_builder/demo_pack.zip.sha256

/home/beros/evidence_builder/output/index.csv

/home/beros/evidence_builder/output/snapshots/*_bbox.jpg

2) Profile 1 — OFFLINE + COCO (PC/WSL)
Run (PC/WSL)
bash
Kopiera kod
cd /home/beros/projects/fod_poc/repo/sep400-standby-fod-poc
source /home/beros/projects/fod_poc/venv/pc_train/bin/activate
export PYTHONNOUSERSITE=1

python3 pc_wsl/offline/offline_detect_run_coco.py \
  --video /home/beros/evidence_builder/input/run_106012.mp4 \
  --model /home/beros/projects/fod_poc/models/yolov8n.pt \
  --roi pc_wsl/events/rois/roi_1080p_12mm_roadonly_v1.json \
  --events_out /home/beros/evidence_builder/input/events.json \
  --imgsz 1280 \
  --conf 0.25 \
  --rep_conf 0.25 \
  --min_area 2000 \
  --confirm_n 2 \
  --end_miss_m 10 \
  --min_event_dur_s 0.25 \
  --cooldown_s 0.5

bash pc_wsl/evidence_builder/run_demo_pack_wsl.sh
PASS criteria:

EB prints index validation PASS: N/N

Visual check: output/snapshots/*_bbox.jpg aligns to object

3) Profile 2 — OFFLINE + FOD 1-CLASS (PC/WSL)
Quality mode (default / stable)
bash
Kopiera kod
cd /home/beros/projects/fod_poc/repo/sep400-standby-fod-poc
source /home/beros/projects/fod_poc/venv/pc_train/bin/activate
export PYTHONNOUSERSITE=1

python3 pc_wsl/offline/offline_detect_run.py \
  --video /home/beros/evidence_builder/input/run_103012.mp4 \
  --model /home/beros/projects/fod_poc/models/fod_1class_best.pt \
  --roi pc_wsl/events/rois/roi_1080p_12mm_roadonly_v1.json \
  --events_out /home/beros/evidence_builder/input/events.json \
  --imgsz 1280 \
  --conf 0.25 \
  --rep_conf 0.25 \
  --min_area 2000 \
  --confirm_n 2 \
  --end_miss_m 10 \
  --min_event_dur_s 0.25 \
  --cooldown_s 0.5

bash pc_wsl/evidence_builder/run_demo_pack_wsl.sh
Coverage mode (optional; more events, more false positives possible)
bash
Kopiera kod
cd /home/beros/projects/fod_poc/repo/sep400-standby-fod-poc
source /home/beros/projects/fod_poc/venv/pc_train/bin/activate
export PYTHONNOUSERSITE=1

python3 pc_wsl/offline/offline_detect_run.py \
  --video /home/beros/evidence_builder/input/run_103012.mp4 \
  --model /home/beros/projects/fod_poc/models/fod_1class_best.pt \
  --events_out /home/beros/evidence_builder/input/events.json \
  --imgsz 1280 \
  --conf 0.10 \
  --rep_conf 0.25 \
  --min_area 2000 \
  --confirm_n 1 \
  --end_miss_m 2 \
  --min_event_dur_s 0.10 \
  --cooldown_s 0

bash pc_wsl/evidence_builder/run_demo_pack_wsl.sh
4) Profile 3 — LIVE + COCO (Jetson)
Run (Jetson)
bash
Kopiera kod
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
  --conf 0.25 \
  --min_area 2000 \
  --confirm_n 2 \
  --end_miss_m 10 \
  --min_event_dur_s 0.25 \
  --cooldown_s 1.0 \
  --save_every_n 120
Export bundle (Jetson → PC)
bash
Kopiera kod
EXPORT=/data/live_runs/export_${RUN_TAG}
mkdir -p "$EXPORT"

MP4=$(ls -t /data/live_runs/videos/live_run_*.mp4 | head -n 1)
EVENTS=/data/live_runs/events/events_coco_${RUN_TAG}.json

cp -v "$MP4" "$EXPORT/"
cp -v "$EVENTS" "$EXPORT/events.json"
sha256sum "$EXPORT"/* > "$EXPORT/SHA256SUMS.txt"

echo "EXPORT READY: $EXPORT"
ls -la "$EXPORT"
Copy to PC and place:

MP4 → /home/beros/evidence_builder/input/

events.json → /home/beros/evidence_builder/input/events.json

Then run EB on PC:

bash
Kopiera kod
bash pc_wsl/evidence_builder/run_demo_pack_wsl.sh
5) Profile 4 — LIVE + FOD 1-CLASS (Jetson)
Same as Profile 3 but swap model + ROI and tune gates.

bash
Kopiera kod
cd /home/fod/projects/fod_poc/repo/sep400-standby-fod-poc
source /home/fod/projects/fod_poc/venv/jetson_live/bin/activate
export PYTHONNOUSERSITE=1

RUN_TAG=$(date +%Y%m%d_%H%M%S)

python3 jetson/live_detection/live_detect_record_run.py \
  --duration_s 60 \
  --model /home/fod/projects/fod_poc/models/fod_1class_best.pt \
  --roi pc_wsl/events/rois/roi_1080p_12mm_roadonly_v1.json \
  --events_out /data/live_runs/events/events_fod_${RUN_TAG}.json \
  --logs_dir /data/live_runs/logs \
  --videos_dir /data/live_runs/videos \
  --conf 0.25 \
  --min_area 2000 \
  --confirm_n 2 \
  --end_miss_m 10 \
  --min_event_dur_s 0.25 \
  --cooldown_s 1.0 \
  --save_every_n 120
Export exactly as Profile 3 (swap events_fod_${RUN_TAG}.json), copy to PC, run EB.

6) PASS criteria (all profiles)
After running EB on PC:

/home/beros/evidence_builder/demo_pack.zip exists

EB prints: index validation PASS: N/N

Visual check: output/snapshots/*_bbox.jpg aligns with the object
