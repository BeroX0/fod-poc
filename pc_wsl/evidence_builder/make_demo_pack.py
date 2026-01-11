#!/usr/bin/env python3
import csv
import json
import hashlib
import shutil
import subprocess
import os
import zipfile
from pathlib import Path

def _eb_root() -> Path:
    """Resolve Evidence Builder runtime root.
    Preference: $EVIDENCE_DIR (if set), else current working directory.
    """
    env = os.environ.get("EVIDENCE_DIR")
    if env:
        return Path(env).expanduser()
    return Path.cwd()

EB_ROOT = _eb_root()
HOME = Path.home()  # kept for backward compatibility
EB = EB_ROOT
EVENTS_JSON = EB / "input" / "events.json"
OUT = EB / "demo_pack"
OUT_EVENTS = OUT / "events"
ZIP_PATH = EB / "demo_pack.zip"

OUTPUT_DIR = EB / "output"
CLIPS_DIR = OUTPUT_DIR / "clips"
SNAPS_DIR = OUTPUT_DIR / "snapshots"

# PoC constants
FRAME_W = 1920
FRAME_H = 1080

# Determinism: fixed timestamp + fixed mtime for all generated files
FIXED_TIMESTAMP_UTC = "2026-01-04T00:00:00Z"
FIXED_MTIME_EPOCH = 1700000000  # constant

def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def load_events() -> list[dict]:
    events = json.load(open(EVENTS_JSON, "r", encoding="utf-8"))
    if isinstance(events, list):
        return events
    if isinstance(events, dict):
        for v in events.values():
            if isinstance(v, list):
                return v
    raise ValueError("events.json must be a list (or dict containing a list).")

def dedupe_by_event_id(events: list[dict]) -> list[dict]:
    out = []
    seen = set()
    for ev in events:
        eid = ev.get("event_id") or ev.get("id")
        if not eid:
            continue
        eid = str(eid)
        if eid in seen:
            continue
        seen.add(eid)
        out.append(ev)
    return out

def find_artifacts_for_event(eid: str) -> tuple[Path, Path]:
    clips = sorted(CLIPS_DIR.glob(f"{eid}_*_clip.mp4"))
    snaps = sorted([p for p in SNAPS_DIR.glob(f"{eid}_*.jpg") if not p.name.endswith("_bbox.jpg")])

    if len(clips) != 1:
        raise FileNotFoundError(f"{eid}: expected exactly 1 clip in {CLIPS_DIR}, found {len(clips)}: {[c.name for c in clips]}")
    if len(snaps) != 1:
        raise FileNotFoundError(f"{eid}: expected exactly 1 snapshot in {SNAPS_DIR}, found {len(snaps)}: {[s.name for s in snaps]}")

    return clips[0], snaps[0]

def ffprobe_wh(image_path: Path) -> tuple[int, int]:
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height",
         "-of", "csv=p=0", str(image_path)],
        capture_output=True, text=True, check=True
    )
    w_str, h_str = res.stdout.strip().split(",")
    return int(w_str), int(h_str)

def to_xyxy_pixels_fullframe(raw_bbox: list[float], frame_w: int, frame_h: int) -> tuple[tuple[float,float,float,float], str]:
    a, b, c, d = [float(x) for x in raw_bbox]
    is_norm = all(0.0 <= v <= 1.5 for v in (a, b, c, d))

    if is_norm:
        x1, y1, x2, y2 = a*frame_w, b*frame_h, c*frame_w, d*frame_h
        space = "norm_xyxy_fullframe"
    else:
        x1, y1, x2, y2 = a, b, c, d
        space = "pixel_xyxy_fullframe"

    # If looks like xywh, convert to xyxy
    if (x2 <= x1) or (y2 <= y1):
        x, y, w, h = x1, y1, x2, y2
        x1, y1, x2, y2 = x, y, x + w, y + h
        space = space.replace("xyxy", "xywh_then_to_xyxy")

    return (x1, y1, x2, y2), space

def sanitize_bbox_xyxy(x1: float, y1: float, x2: float, y2: float, frame_w: int, frame_h: int, eid: str, raw_bbox):
    """
    Fail fast for truly invalid bboxes, but allow small subpixel spillover (e.g. 1079.03) by clamping.
    """
    tol = 2.0  # pixels tolerance
    if (x1 < -tol) or (y1 < -tol) or (x2 > frame_w + tol) or (y2 > frame_h + tol):
        raise SystemExit(
            f"[BBOX_ASSERT_FAIL] {eid} raw_bbox={raw_bbox} "
            f"interpreted_xyxy=({x1:.2f},{y1:.2f},{x2:.2f},{y2:.2f}) frame=({frame_w},{frame_h})"
        )

    x1c = max(0.0, min(x1, frame_w - 1.0))
    y1c = max(0.0, min(y1, frame_h - 1.0))
    x2c = max(0.0, min(x2, frame_w - 1.0))
    y2c = max(0.0, min(y2, frame_h - 1.0))

    # Ensure proper ordering after clamp
    if not (x1c < x2c and y1c < y2c):
        raise SystemExit(
            f"[BBOX_ORDER_FAIL] {eid} raw_bbox={raw_bbox} "
            f"clamped_xyxy=({x1c:.2f},{y1c:.2f},{x2c:.2f},{y2c:.2f}) frame=({frame_w},{frame_h})"
        )

    was_clamped = (abs(x1c - x1) > 1e-6) or (abs(y1c - y1) > 1e-6) or (abs(x2c - x2) > 1e-6) or (abs(y2c - y2) > 1e-6)
    return (x1c, y1c, x2c, y2c, was_clamped)

def draw_bbox_ffmpeg(snapshot_path: Path, out_path: Path, x1: float, y1: float, x2: float, y2: float, label: str) -> None:
    x = int(round(x1))
    y = int(round(y1))
    w = max(1, int(round(x2 - x1)))
    h = max(1, int(round(y2 - y1)))

    vf = (
        f"drawbox=x={x}:y={y}:w={w}:h={h}:color=red@0.9:thickness=6,"
        f"drawtext=text='{label}':x={x}:y={max(0, y-40)}:fontsize=36:fontcolor=red"
    )

    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(snapshot_path), "-vf", vf, "-frames:v", "1", "-update", "1", str(out_path)],
        check=True
    )

def force_fixed_mtime(root: Path, epoch: int) -> None:
    for p in sorted(root.rglob("*")):
        if p.is_file():
            os.utime(p, (epoch, epoch))

def zip_deterministic(src_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()

    files = [p for p in src_dir.rglob("*") if p.is_file()]
    files.sort(key=lambda p: str(p.relative_to(src_dir)))

    fixed_dt = (2026, 1, 4, 0, 0, 0)

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            rel = str(p.relative_to(src_dir))
            zi = zipfile.ZipInfo(rel, date_time=fixed_dt)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zi, p.read_bytes())

def main() -> None:
    if not EVENTS_JSON.exists():
        raise FileNotFoundError(f"Missing: {EVENTS_JSON}")
    if not CLIPS_DIR.exists() or not SNAPS_DIR.exists():
        raise FileNotFoundError(f"Missing output dirs: {CLIPS_DIR} and/or {SNAPS_DIR}. Run batch_evidence.py first.")

    events = dedupe_by_event_id(load_events())
    if not events:
        raise SystemExit("No events found in events.json after dedupe.")

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT_EVENTS.mkdir(parents=True, exist_ok=True)

    (OUT / "README.txt").write_text(
        "Standby FOD PoC — Demo Pack (Deterministic)\n"
        "Structure:\n"
        "  demo_pack/\n"
        "    README.txt\n"
        "    index.csv\n"
        "    events/\n"
        "      event_0001/\n"
        "        clip.mp4\n"
        "        snapshot.jpg\n"
        "        snapshot_bbox.jpg\n"
        "        bbox_debug.json\n"
        "        alarm.json\n",
        encoding="utf-8"
    )

    def eid_key(ev: dict):
        eid = str(ev.get("event_id") or ev.get("id"))
        try:
            return int(eid.split("_")[-1])
        except Exception:
            return eid

    events_sorted = sorted(events, key=eid_key)

    index_rows = []

    for idx, ev in enumerate(events_sorted, start=1):
        eid = str(ev.get("event_id") or ev.get("id"))
        ev_dir = OUT_EVENTS / f"event_{idx:04d}"
        ev_dir.mkdir(parents=True, exist_ok=True)

        clip_src, snap_src = find_artifacts_for_event(eid)

        clip_dst = ev_dir / "clip.mp4"
        snap_dst = ev_dir / "snapshot.jpg"
        shutil.copy2(clip_src, clip_dst)
        shutil.copy2(snap_src, snap_dst)

        w, h = ffprobe_wh(snap_dst)
        if (w, h) != (FRAME_W, FRAME_H):
            raise SystemExit(f"[FRAME_ASSERT_FAIL] {eid} snapshot dims {(w,h)} expected {(FRAME_W,FRAME_H)}")

        raw_bbox = ev.get("representative_bbox") or ev.get("bbox")
        raw_field = "representative_bbox" if ev.get("representative_bbox") is not None else ("bbox" if ev.get("bbox") is not None else None)

        bbox_debug = {
            "event_id": eid,
            "roi_id": ev.get("roi_id") or ev.get("roi"),
            "frame_w": FRAME_W,
            "frame_h": FRAME_H,
            "raw_bbox": raw_bbox,
            "raw_bbox_field": raw_field,
            "coord_space": None,
            "interpreted_bbox_xyxy_pixels": None,
            "clamped_bbox_xyxy_pixels": None,
            "was_clamped": None
        }

        bbox_dst_path = ""
        bbox_dst = ev_dir / "snapshot_bbox.jpg"

        if raw_bbox and isinstance(raw_bbox, list) and len(raw_bbox) == 4:
            (x1, y1, x2, y2), space = to_xyxy_pixels_fullframe(raw_bbox, FRAME_W, FRAME_H)
            bbox_debug["coord_space"] = space
            bbox_debug["interpreted_bbox_xyxy_pixels"] = [float(x1), float(y1), float(x2), float(y2)]

            x1c, y1c, x2c, y2c, was_clamped = sanitize_bbox_xyxy(x1, y1, x2, y2, FRAME_W, FRAME_H, eid, raw_bbox)
            bbox_debug["clamped_bbox_xyxy_pixels"] = [float(x1c), float(y1c), float(x2c), float(y2c)]
            bbox_debug["was_clamped"] = bool(was_clamped)

            label = f"{(ev.get('class_name') or ev.get('class') or 'obj')} ({eid})"
            draw_bbox_ffmpeg(snap_dst, bbox_dst, x1c, y1c, x2c, y2c, label)
            bbox_dst_path = str(bbox_dst.relative_to(OUT))

        (ev_dir / "bbox_debug.json").write_text(json.dumps(bbox_debug, indent=2), encoding="utf-8")

        alarm = {
            "timestamp_utc": FIXED_TIMESTAMP_UTC,
            "event_id": eid,
            "class": ev.get("class_name") or ev.get("class"),
            "roi_id": ev.get("roi_id") or ev.get("roi"),
            "video_filename": ev.get("video_filename"),
            "time_window_s": {
                "start": float(ev.get("start_time_s")) if ev.get("start_time_s") is not None else None,
                "end": float(ev.get("end_time_s")) if ev.get("end_time_s") is not None else None,
            },
            "confidence_summary": {
                "avg": None,
                "min": None,
                "max": float(ev.get("max_confidence")) if ev.get("max_confidence") is not None else None,
            },
            "evidence": {
                "clip": str(clip_dst.relative_to(OUT)),
                "snapshot": str(snap_dst.relative_to(OUT)),
                "snapshot_bbox": bbox_dst_path or None,
            },
            "integrity": {
                "clip_sha256": sha256(clip_dst),
                "snapshot_sha256": sha256(snap_dst),
                "snapshot_bbox_sha256": sha256(OUT / bbox_dst_path) if bbox_dst_path else None,
            },
            "action": "ALARM_TRIGGERED (PoC)",
            "notes": "Deterministic alarm artifact for PoC verification."
        }
        (ev_dir / "alarm.json").write_text(json.dumps(alarm, indent=2), encoding="utf-8")

        index_rows.append({
            "event_id": eid,
            "video": ev.get("video_filename"),
            "class": ev.get("class_name") or ev.get("class"),
            "roi_id": ev.get("roi_id") or ev.get("roi"),
            "start_time_s": f"{float(ev.get('start_time_s')):.6f}" if ev.get("start_time_s") is not None else "",
            "end_time_s": f"{float(ev.get('end_time_s')):.6f}" if ev.get("end_time_s") is not None else "",
            "clip_path": str(clip_dst.relative_to(OUT)),
            "snapshot_path": str(snap_dst.relative_to(OUT)),
            "snapshot_bbox_path": bbox_dst_path,
        })

    index_path = OUT / "index.csv"
    with index_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "event_id","video","class","roi_id","start_time_s","end_time_s",
            "clip_path","snapshot_path","snapshot_bbox_path"
        ])
        w.writeheader()
        for r in index_rows:
            w.writerow(r)

    # Index integrity validation (mandatory)
    rows = list(csv.DictReader(index_path.open("r", encoding="utf-8", newline="")))
    missing = []
    for r in rows:
        for k in ("clip_path","snapshot_path","snapshot_bbox_path"):
            if r.get(k) and r[k].strip():
                p = OUT / r[k]
                if not p.exists():
                    missing.append(f"{r['event_id']} missing {k}: {r[k]}")
    if missing:
        print("[INDEX_VALIDATION_FAIL]")
        for m in missing:
            print(" -", m)
        raise SystemExit(2)
    print(f"index validation PASS: {len(rows)}/{len(rows)} rows resolved")

    force_fixed_mtime(OUT, FIXED_MTIME_EPOCH)
    zip_deterministic(OUT, ZIP_PATH)

    print(f"Demo pack created: {OUT}")
    print(f"Events processed: {len(index_rows)}")
    print(f"demo_pack.zip sha256: {sha256(ZIP_PATH)}")

if __name__ == "__main__":
    main()
