#!/usr/bin/env python3
import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from ultralytics import YOLO

# -----------------------------
# Geometry helpers
# -----------------------------

def point_in_poly(x: float, y: float, poly: List[Tuple[float, float]]) -> bool:
    inside = False
    n = len(poly)
    if n < 3:
        return True
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        intersect = ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi)
        if intersect:
            inside = not inside
        j = i
    return inside

# -----------------------------
# Video IO (ffprobe/ffmpeg)
# -----------------------------

@dataclass
class VideoInfo:
    width: int
    height: int
    duration_s: float

def ffprobe_info(video_path: Path) -> VideoInfo:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height:format=duration",
        "-of", "json",
        str(video_path),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, check=True)
    info = json.loads(p.stdout)
    s = info["streams"][0]
    dur = float(info.get("format", {}).get("duration", 0.0) or 0.0)
    return VideoInfo(width=int(s["width"]), height=int(s["height"]), duration_s=dur)

def ffprobe_frame_times(video_path: Path) -> List[float]:
    """
    Per-frame best_effort_timestamp_time (PTS in seconds).
    This aligns event times with ffmpeg -ss seeking (used by Evidence Builder).
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time",
        "-of", "csv=p=0",
        str(video_path),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, check=True)
    times: List[float] = []
    for line in p.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            times.append(float(line))
        except ValueError:
            continue
    if not times:
        raise RuntimeError("ffprobe_frame_times: got 0 timestamps")
    return times

def ffmpeg_frames_rgb(video_path: Path, width: int, height: int):
    """
    Yield decoded RGB frames as numpy uint8 (H,W,3).

    Note: We suppress ffmpeg stderr to avoid "Broken pipe" noise when we terminate early
    (this is harmless and happens when the reader stops before ffmpeg finishes writing).
    """
    cmd = [
        "ffmpeg", "-nostdin", "-loglevel", "error",
        "-i", str(video_path),
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-"
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**8)
    frame_bytes = width * height * 3
    idx = 0
    try:
        while True:
            raw = proc.stdout.read(frame_bytes)  # type: ignore
            if not raw or len(raw) < frame_bytes:
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 3))
            yield idx, frame
            idx += 1
    finally:
        try:
            if proc.stdout:
                proc.stdout.close()
        except Exception:
            pass
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            pass

def extract_jpg_at_time(video_path: Path, t_s: float, out_path: Path) -> None:
    """
    Accurate seek: -ss AFTER -i (same approach as EB's accurate seek).
    MUST either create out_path (non-zero) or raise with stderr.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-y",
        "-i", str(video_path),
        "-ss", f"{t_s:.6f}",
        "-frames:v", "1",
        "-q:v", "2",
        str(out_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"ffmpeg snapshot extract failed rc={r.returncode}\n"
            f"CMD: {' '.join(cmd)}\nSTDERR:\n{r.stderr}"
        )
    if (not out_path.exists()) or out_path.stat().st_size == 0:
        raise RuntimeError(
            f"ffmpeg snapshot extract produced no file: {out_path} (t={t_s:.6f})\n"
            f"CMD: {' '.join(cmd)}\nSTDERR:\n{r.stderr}"
        )

# -----------------------------
# ROI loading
# -----------------------------

def load_roi_polygon(path: Optional[str], W: int, H: int) -> Tuple[List[Tuple[float, float]], str]:
    if not path:
        return ([(0.0, 0.0), (float(W), 0.0), (float(W), float(H)), (0.0, float(H))], "fullframe")
    p = Path(path)
    data = json.loads(p.read_text())

    pts = None
    if isinstance(data, dict):
        if "polygon" in data:
            pts = data["polygon"]
        elif "points" in data:
            pts = data["points"]
        elif "roi" in data and isinstance(data["roi"], dict) and "polygon" in data["roi"]:
            pts = data["roi"]["polygon"]

    poly: List[Tuple[float, float]] = []
    if isinstance(pts, list):
        for pt in pts:
            if isinstance(pt, dict) and "x" in pt and "y" in pt:
                poly.append((float(pt["x"]), float(pt["y"])))
            elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
                poly.append((float(pt[0]), float(pt[1])))

    if len(poly) < 3:
        poly = [(0.0, 0.0), (float(W), 0.0), (float(W), float(H)), (0.0, float(H))]
    return poly, p.stem

# -----------------------------
# Representative bbox refinement on EB snapshot frame
# -----------------------------

def best_bbox_on_snapshot(
    model: YOLO,
    snapshot_path: Path,
    imgsz: int,
    conf: float,
    roi_poly: List[Tuple[float, float]],
    min_area: float,
) -> Optional[Tuple[List[float], float, int]]:
    r = model.predict(source=str(snapshot_path), imgsz=imgsz, conf=conf, verbose=False)[0]
    if r.boxes is None or len(r.boxes) == 0:
        return None
    xyxy = r.boxes.xyxy.cpu().numpy()
    confs = r.boxes.conf.cpu().numpy()
    clses = r.boxes.cls.cpu().numpy()

    best: Optional[Tuple[List[float], float, int]] = None
    for b, c, k in zip(xyxy, confs, clses):
        x1, y1, x2, y2 = map(float, b.tolist())
        area = (x2 - x1) * (y2 - y1)
        if area < min_area:
            continue
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        if not point_in_poly(cx, cy, roi_poly):
            continue
        cand = ([x1, y1, x2, y2], float(c), int(k))
        if best is None or cand[1] > best[1]:
            best = cand
    return best

# -----------------------------
# Main
# -----------------------------

def atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2))
    tmp.replace(path)

def main():
    ap = argparse.ArgumentParser(description="Offline MP4 -> events.json (EB compatible, PTS-aligned, COCO-labeled, snapshot-refined bbox)")
    ap.add_argument("--video", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--roi", default=None)
    ap.add_argument("--events_out", required=True)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--conf", type=float, default=0.35, help="Detection confidence used to OPEN/MAINTAIN events")
    ap.add_argument("--rep_conf", type=float, default=0.25, help="Confidence used to pick representative bbox on snapshot frame (mid_s)")
    ap.add_argument("--min_area", type=float, default=5000.0)
    ap.add_argument("--confirm_n", type=int, default=3)
    ap.add_argument("--end_miss_m", type=int, default=10)
    ap.add_argument("--min_event_dur_s", type=float, default=0.30)
    ap.add_argument("--cooldown_s", type=float, default=1.0)
    ap.add_argument("--max_frames", type=int, default=0)
    args = ap.parse_args()

    video_path = Path(args.video)
    if not video_path.exists():
        raise FileNotFoundError(video_path)

    vi = ffprobe_info(video_path)
    W, H, DUR = vi.width, vi.height, vi.duration_s
    times = ffprobe_frame_times(video_path)
    roi_poly, roi_id = load_roi_polygon(args.roi, W, H)

    model = YOLO(args.model)

    events: List[Dict[str, Any]] = []

    in_event = False
    first_seen_t = 0.0
    last_seen_t = 0.0
    miss = 0
    seen = 0
    next_allowed_start = 0.0
    ev_idx = 1

    tmp_dir = Path("/tmp/offline_rep_frames")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    def close_event(end_t: float):
        nonlocal in_event, first_seen_t, last_seen_t, miss, seen, next_allowed_start, ev_idx

        if not in_event:
            return

        dur = float(end_t - first_seen_t)
        if not (seen >= args.confirm_n and dur >= args.min_event_dur_s):
            in_event = False
            miss = 0
            seen = 0
            return

        start_t = float(first_seen_t)
        stop_t = float(end_t)
        mid_t = 0.5 * (start_t + stop_t)

        # Clamp mid_t inside video duration to avoid “no frame” edge cases.
        if DUR and DUR > 0.1:
            mid_t = max(0.0, min(mid_t, DUR - 0.050))

        tmp = tmp_dir / f"offline_rep_{video_path.stem}_{ev_idx:04d}.jpg"

        try:
            extract_jpg_at_time(video_path, mid_t, tmp)
            best = best_bbox_on_snapshot(
                model=model,
                snapshot_path=tmp,
                imgsz=args.imgsz,
                conf=args.rep_conf,
                roi_poly=roi_poly,
                min_area=args.min_area,
            )
        except Exception as e:
            print(f"WARN: {video_path.name} ev_{ev_idx:04d}: snapshot-refine failed, dropping event. Reason: {e}")
            best = None
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

        if best is None:
            in_event = False
            miss = 0
            seen = 0
            return

        rep_bbox, rep_conf, rep_cls = best
        label = str(model.names.get(rep_cls, rep_cls))

        events.append({
            "event_id": f"ev_{ev_idx:04d}",
            "video_filename": video_path.name,
            "start_time_s": start_t,
            "end_time_s": stop_t,
            "representative_bbox": [float(v) for v in rep_bbox],
            "class_name": label,
            "label": label,
            "roi_id": roi_id,
            # debug fields (ignored by EB)
            "rep_time_s": float(mid_t),
            "rep_conf": float(rep_conf),
            "rep_source": "snapshot_refine_mid",
        })

        ev_idx += 1
        next_allowed_start = stop_t + float(args.cooldown_s)

        in_event = False
        miss = 0
        seen = 0

    # Stream frames for event timing only (open/close events)
    for frame_idx, frame_rgb in ffmpeg_frames_rgb(video_path, W, H):
        if args.max_frames and frame_idx >= args.max_frames:
            break
        if frame_idx >= len(times):
            break
        t = times[frame_idx]

        r = model.predict(source=frame_rgb, imgsz=args.imgsz, conf=args.conf, verbose=False)[0]

        hit = False
        if r.boxes is not None and len(r.boxes) > 0:
            xyxy = r.boxes.xyxy.cpu().numpy()
            confs = r.boxes.conf.cpu().numpy()
            for b, c in zip(xyxy, confs):
                x1, y1, x2, y2 = map(float, b.tolist())
                area = (x2 - x1) * (y2 - y1)
                if area < args.min_area:
                    continue
                cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                if not point_in_poly(cx, cy, roi_poly):
                    continue
                hit = True
                break

        if hit:
            if (not in_event) and (t >= next_allowed_start):
                in_event = True
                first_seen_t = t
                last_seen_t = t
                miss = 0
                seen = 0

            if in_event:
                seen += 1
                miss = 0
                last_seen_t = t
        else:
            if in_event:
                miss += 1
                if miss >= args.end_miss_m:
                    close_event(last_seen_t)

    if in_event:
        close_event(last_seen_t)

    out_path = Path(args.events_out)
    atomic_write_json(out_path, events)
    print(f"WROTE events: {len(events)} -> {out_path}")

if __name__ == "__main__":
    main()
