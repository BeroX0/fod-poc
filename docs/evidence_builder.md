# Evidence Builder (EB) — Demo Pack Generator

## Purpose and scope
Evidence Builder converts an `events.json` file plus the referenced MP4 videos into **human-reviewable evidence artifacts** and a **deterministic demo pack**:

- short clips around each event
- one snapshot frame per event
- a snapshot with bbox overlay
- indices (`output/index.csv` and `demo_pack/index.csv`)
- a single deliverable: `demo_pack.zip`

This is a **PoC** workflow. Object classes may be **proxy labels** (e.g., COCO classes) and may not match the physical object. The objective is **integration + deterministic evidence generation + auditable outputs**, not model accuracy.

---

## Source of truth (GitHub gate)
Canonical EB scripts are in the repo:

- `pc_wsl/evidence_builder/`

The runner:

- `pc_wsl/evidence_builder/run_demo_pack_wsl.sh`

**copies repo scripts into the runtime folder** (`$HOME/evidence_builder`) before running. This prevents stale local runtime scripts from diverging from GitHub.

---

## Prerequisites
Validated on WSL2 Ubuntu (or Linux).

Required tools:
- `python3` (tested with Python 3.12.x)
- `ffmpeg`
- `ffprobe`

Quick check:
```bash
command -v ffmpeg && ffmpeg -version | head -n 2
command -v ffprobe && ffprobe -version | head -n 2
python3 -V
```

---

## Runtime directory

Default runtime workspace:

* `EVIDENCE_DIR=${EVIDENCE_DIR:-$HOME/evidence_builder}`

Required inputs:

* `$HOME/evidence_builder/input/events.json`
* `$HOME/evidence_builder/input/<video_filename>.mp4`

Generated outputs:

* `$HOME/evidence_builder/output/` (runtime artifacts + index)
* `$HOME/evidence_builder/demo_pack/` (pack layout)
* `$HOME/evidence_builder/demo_pack.zip` (deterministic zip)

---

## Input contract (exact)

### events.json path

EB requires:

* `$HOME/evidence_builder/input/events.json`

Accepted JSON shapes:

* a list of event objects, OR
* a dict containing a list (EB uses the first list-like value)

### video resolution rules

EB resolves each event’s video filename and searches:

1. `$HOME/evidence_builder/input/<video_filename>` (primary)
2. `/data/recordings/<video_filename>` (secondary fallback)

If missing in both → FAIL.

---

## events.json schema (exact, as implemented)

EB tolerates multiple key aliases. Supported fields:

### identity

* `event_id` (preferred) or `id` (fallback)

If missing, EB may generate `ev_0001`, `ev_0002`, … (runtime index uses this ID).

### video filename (required)

One of:

* `video_filename` (preferred)
* `video`
* `source_video`

### class label (optional)

One of:

* `class_name` (preferred)
* `label`
* else: `"unknown"` (runtime)

### roi id (optional)

One of:

* `roi_id` (preferred)
* `roi`
* else: `"unknown_roi"`

### timing (required with fallback)

Preferred:

* `start_time_s` (float seconds)
* `end_time_s` (float seconds)

Fallback:

* `time_s` or `trigger_time_s` (treated as start=end)

### representative frame for snapshot (optional)

One of:

* `rep_frame` (preferred)
* `trigger_frame` (fallback)

If absent, EB snapshots at the event midpoint time.

### bbox fields (critical)

EB reads bbox from:

* `representative_bbox` (preferred) OR
* `bbox` (fallback)

BBox must be a list of 4 numbers. EB supports:

1. **pixel xyxy full-frame** (preferred)
   `[x1, y1, x2, y2]` in pixels

2. **normalized xyxy full-frame**
   `[x1, y1, x2, y2]` where values are roughly in `[0..1]`
   EB interprets as normalized and multiplies by frame size.

If input appears to be **xywh** (heuristic):

* if `(x2 <= x1) or (y2 <= y1)`, EB treats it as `[x, y, w, h]` and converts to xyxy.

#### bbox coordinate space (explicit)

Demo pack enforces snapshots are **1920×1080**, so bbox coordinates are interpreted in **1920×1080 full-frame space**.

EB clamps small subpixel spillover but fails fast if bbox is far outside the frame.

---

## Output contract (exact)

### Runtime outputs (`$HOME/evidence_builder/output/`)

Produced by `batch_evidence.py`:

* `output/index.csv`
* `output/clips/`
* `output/snapshots/`

Runtime index columns:

* `event_id, video, class, roi_id, start_time_s, end_time_s, clip_path, snapshot_path, snapshot_bbox_path`

Path base:

* `clip_path`, `snapshot_path`, `snapshot_bbox_path` are relative to `$HOME/evidence_builder/output/`.

Naming:

* clip: `output/clips/<event_id>_<video_stem>_clip.mp4`
* snapshot: `output/snapshots/<event_id>_<video_stem>.jpg`
* bbox snapshot: `output/snapshots/<event_id>_<video_stem>_bbox.jpg`

### Demo pack outputs (`$HOME/evidence_builder/demo_pack/`)

Produced by `make_demo_pack.py`:

* `demo_pack/README.txt`
* `demo_pack/index.csv`
* `demo_pack/events/event_0001/`

  * `clip.mp4`
  * `snapshot.jpg`
  * `snapshot_bbox.jpg` (if bbox exists)
  * `bbox_debug.json`
  * `alarm.json`

Zip output:

* `$HOME/evidence_builder/demo_pack.zip`

Demo pack index columns (schema matches runtime index):

* `event_id, video, class, roi_id, start_time_s, end_time_s, clip_path, snapshot_path, snapshot_bbox_path`

Path base:

* `clip_path`, `snapshot_path`, `snapshot_bbox_path` are relative to `demo_pack/`.

---

## One-command reproducible run

From repo root:

```bash
cd ~/projects/sep400-standby-fod-poc
bash pc_wsl/evidence_builder/run_demo_pack_wsl.sh
```

Runner behavior:

* validates input exists
* copies repo scripts into `$HOME/evidence_builder/`
* wipes previous artifacts
* runs `python3 batch_evidence.py` then `python3 make_demo_pack.py`
* prints `sha256sum demo_pack.zip`

---

## Determinism guarantee

Determinism here means:

* same `events.json` + identical MP4 bytes → same filenames, same pack structure, and stable `demo_pack.zip` SHA-256
* demo pack zip is generated deterministically (fixed timestamps/mtimes)

---

## Troubleshooting & known warnings

### FFmpeg single-frame warnings

Warnings about image sequence patterns can appear during single-frame extraction; if the snapshot output exists and is correct, these warnings are usually benign.

### ROI 2048×1152 vs 1920×1080 mismatch

ROI coordinates are defined in **1920×1080**, while some reference PNGs are **2048×1152**. If you visualize ROIs on 2048×1152 without scaling, they can look offset. This is a visualization mismatch, not an EB bug.

### bbox overlay looks wrong

Most common causes:

* upstream bbox is not in full-frame 1920×1080 space
* upstream bbox is normalized but treated as pixels (or vice versa)
* upstream produced xywh while you assumed xyxy

Use `demo_pack/events/event_XXXX/bbox_debug.json` to see how EB interpreted the bbox.

