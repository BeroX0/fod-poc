#!/usr/bin/env python3
import csv
import json
import subprocess
import os
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

import argparse

# ----------------------------
# Config
# ----------------------------
INPUT_DIR = EB_ROOT / "input"
OUTPUT_DIR = EB_ROOT / "output"
CLIPS_DIR = OUTPUT_DIR / "clips"
SNAPS_DIR = OUTPUT_DIR / "snapshots"
INDEX_PATH = OUTPUT_DIR / "index.csv"
EVENTS_PATH = INPUT_DIR / "events.json"

# Evidence policy
PAD_BEFORE_S = 3.0   # seconds before event start
PAD_AFTER_S = 3.0    # seconds after event end
CRF = "18"
PRESET = "fast"

# ----------------------------
# Helpers
# ----------------------------
def run(cmd: list[str]) -> None:
    print("RUN:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def ensure_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    SNAPS_DIR.mkdir(parents=True, exist_ok=True)


def load_events() -> list[dict]:
    with open(EVENTS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        # find first list-like value
        for v in data.values():
            if isinstance(v, list):
                return v

    raise ValueError("Unsupported events.json format. Expected list or dict containing a list.")


def ffprobe_duration(video_path: Path) -> float | None:
    """
    Returns duration in seconds or None if probe fails.
    """
    try:
        res = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            check=True
        )
        return float(res.stdout.strip())
    except Exception:
        return None


def clamp_clip_window(start_s: float, end_s: float, duration_s: float | None) -> tuple[float, float]:
    clip_start = max(0.0, start_s - PAD_BEFORE_S)
    clip_end = end_s + PAD_AFTER_S

    if duration_s is not None:
        clip_end = min(duration_s, clip_end)

    clip_len = max(0.01, clip_end - clip_start)  # avoid 0 length
    return clip_start, clip_len


def get_event_times(ev: dict) -> tuple[float, float, float]:
    """
    Returns (start_s, end_s, mid_s)
    """
    start = ev.get("start_time_s")
    end = ev.get("end_time_s")

    if start is None or end is None:
        # fallback
        t = ev.get("time_s") or ev.get("trigger_time_s")
        if t is None:
            raise ValueError("Event missing start_time_s/end_time_s and no fallback time_s/trigger_time_s.")
        start = float(t)
        end = float(t)

    start = float(start)
    end = float(end)
    mid = (start + end) / 2.0
    return start, end, mid


def find_video(video_filename: str) -> Path:
    """
    Finds the mp4. Primary: ~/evidence_builder/input/<video>
    Secondary: /data/recordings/<video> (useful if you copied directly from Jetson path)
    """
    p1 = INPUT_DIR / video_filename
    if p1.exists():
        return p1

    p2 = Path("/data/recordings") / video_filename
    if p2.exists():
        return p2

    raise FileNotFoundError(f"Video not found: {video_filename} (checked {p1} and {p2})")


def bbox_to_drawbox(bbox: list[float]) -> tuple[int, int, int, int]:
    """
    bbox = [x1,y1,x2,y2] -> (x,y,w,h) ints
    """
    x1, y1, x2, y2 = bbox
    w = max(1, int(round(x2 - x1)))
    h = max(1, int(round(y2 - y1)))
    return int(round(x1)), int(round(y1)), w, h


def init_index_writer(append_index: bool) -> tuple[csv.writer, object]:
    """
    Deterministic by default:
      - overwrite index.csv each run unless --append-index is set.
    """
    mode = "a" if append_index else "w"
    f = open(INDEX_PATH, mode, newline="", encoding="utf-8")
    w = csv.writer(f)

    if mode == "w":
        w.writerow([
            "event_id", "video", "class", "roi_id",
            "start_time_s", "end_time_s",
            "clip_path", "snapshot_path", "snapshot_bbox_path"
        ])

    return w, f


def safe_event_id(ev: dict, i: int) -> str:
    eid = ev.get("event_id") or ev.get("id")
    if eid:
        return str(eid)
    return f"ev_{i:04d}"


def extract_snapshot_frame_accurate(video_path: Path, frame_idx: int, out_path: Path) -> None:
    """
    Frame-accurate extraction using select=eq(n\\,frame).
    """
    run([
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", f"select='eq(n\\,{frame_idx})'",
        "-vsync", "0",
        "-frames:v", "1",
        "-q:v", "2",
        str(out_path),
    ])


def extract_snapshot_time_accurate(video_path: Path, t_s: float, out_path: Path) -> None:
    """
    More accurate time seek by placing -ss after -i (slower but closer to exact).
    """
    run([
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-ss", f"{t_s:.3f}",
        "-frames:v", "1",
        "-q:v", "2",
        str(out_path),
    ])


# ----------------------------
# Main
# ----------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--append-index", action="store_true", help="Append to existing index.csv (NOT recommended).")
    args = ap.parse_args()

    ensure_dirs()

    if not EVENTS_PATH.exists():
        raise FileNotFoundError(f"Missing events.json at: {EVENTS_PATH}")

    events = load_events()
    print(f"Loaded {len(events)} events from {EVENTS_PATH}")

    writer, fh = init_index_writer(append_index=args.append_index)
    if args.append_index:
        print(f"Appending to existing index: {INDEX_PATH}")
    else:
        print(f"Overwriting index (deterministic): {INDEX_PATH}")

    try:
        for i, ev in enumerate(events, start=1):
            event_id = safe_event_id(ev, i)
            video_filename = ev.get("video_filename") or ev.get("video") or ev.get("source_video")
            if not video_filename:
                raise ValueError(f"{event_id}: missing video_filename")

            class_name = ev.get("class_name") or ev.get("label") or "unknown"
            roi_id = ev.get("roi_id") or ev.get("roi") or "unknown_roi"

            start_s, end_s, mid_s = get_event_times(ev)
            video_path = find_video(video_filename)
            dur_s = ffprobe_duration(video_path)

            clip_start, clip_len = clamp_clip_window(start_s, end_s, dur_s)

            base = f"{event_id}_{Path(video_filename).stem}"
            clip_out = CLIPS_DIR / f"{base}_clip.mp4"
            snap_out = SNAPS_DIR / f"{base}.jpg"
            snap_bbox_out = SNAPS_DIR / f"{base}_bbox.jpg"

            # 1) Clip
            if not clip_out.exists():
                run([
                    "ffmpeg", "-y",
                    "-ss", f"{clip_start:.3f}",
                    "-i", str(video_path),
                    "-t", f"{clip_len:.3f}",
                    "-c:v", "libx264",
                    "-preset", PRESET,
                    "-crf", CRF,
                    "-an",
                    str(clip_out),
                ])
            else:
                print("SKIP clip exists:", clip_out)

            # 2) Snapshot (frame-accurate if rep_frame/trigger_frame exists)
            if not snap_out.exists():
                rep = ev.get("rep_frame")
                if rep is None:
                    rep = ev.get("trigger_frame")

                wrote = False
                if rep is not None:
                    try:
                        rep_i = int(rep)
                        extract_snapshot_frame_accurate(video_path, rep_i, snap_out)
                        wrote = True
                    except Exception as e:
                        print(f"WARN: {event_id}: frame-accurate snapshot failed for rep_frame={rep}: {e}")

                if not wrote:
                    extract_snapshot_time_accurate(video_path, mid_s, snap_out)
            else:
                print("SKIP snapshot exists:", snap_out)

            # 3) BBox overlay (optional)
            bbox = ev.get("representative_bbox") or ev.get("bbox")
            bbox_written = ""
            if bbox and isinstance(bbox, list) and len(bbox) == 4:
                x, y, wbox, hbox = bbox_to_drawbox(bbox)
                label = f"{class_name} ({event_id})"
                vf = (
                    f"drawbox=x={x}:y={y}:w={wbox}:h={hbox}:color=red@0.9:thickness=6,"
                    f"drawtext=text='{label}':x={x}:y={max(0, y-40)}:fontsize=36:fontcolor=red"
                )

                if not snap_bbox_out.exists():
                    run([
                        "ffmpeg", "-y",
                        "-i", str(snap_out),
                        "-vf", vf,
                        str(snap_bbox_out),
                    ])
                else:
                    print("SKIP bbox snapshot exists:", snap_bbox_out)

                bbox_written = f"snapshots/{snap_bbox_out.name}"
            else:
                print(f"{event_id}: No bbox available. Skipping bbox overlay.")

            # 4) Index row (relative paths)
            writer.writerow([
                event_id,
                video_filename,
                class_name,
                roi_id,
                f"{start_s:.6f}",
                f"{end_s:.6f}",
                f"clips/{clip_out.name}",
                f"snapshots/{snap_out.name}",
                bbox_written,
            ])
            fh.flush()

        print("\nDONE ✅ Batch evidence complete.")
        print("Index:", INDEX_PATH)
        print("Clips:", CLIPS_DIR)
        print("Snapshots:", SNAPS_DIR)

    finally:
        fh.close()


if __name__ == "__main__":
    main()
