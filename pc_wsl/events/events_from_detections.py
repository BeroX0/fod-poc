import subprocess
import datetime
#!/usr/bin/env python3
__version__ = "v0.3.1 (2025-12-21)"  # 2025-12-21
__repo_note__ = "events runner (ROI + persistence) - reproducibility stamp"

import argparse, csv, json, math
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

# ----------------------------
# Geometry + helpers
# ----------------------------
def point_in_polygon(x: float, y: float, poly: List[Tuple[float, float]]) -> bool:
    inside = False
    n = len(poly)
    if n < 3:
        return False
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if ((y1 > y) != (y2 > y)):
            x_int = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x_int > x:
                inside = not inside
    return inside

def bbox_center_xyxy(x1: float, y1: float, x2: float, y2: float) -> Tuple[float, float]:
    return (0.5 * (x1 + x2), 0.5 * (y1 + y2))

def dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])

def topk_insert(top: List[Dict[str, Any]], item: Dict[str, Any], k: int = 5) -> None:
    """Keep list sorted by confidence desc, capped to k."""
    top.append(item)
    top.sort(key=lambda x: float(x.get("confidence", 0.0)), reverse=True)
    if len(top) > k:
        del top[k:]

# ----------------------------
# Schema validation
# ----------------------------
REQUIRED_FRAME_KEYS = ["frame_index", "timestamp_s", "detections"]
OPTIONAL_FIRSTFRAME_KEYS = ["video_filename", "width", "height"]
FPS_KEYS_ACCEPTED = ["fps_used_for_timestamps", "fps_reported"]
RAW_KEYS_ACCEPTED = ["raw_detections_in_frame"]  # allow missing, count as 0

REQUIRED_DET_KEYS = ["class_name", "confidence", "x1", "y1", "x2", "y2"]

def schema_error(run_folder: Path, line_no: int, msg: str, obj: Optional[Dict[str, Any]] = None) -> ValueError:
    keys = list(obj.keys()) if isinstance(obj, dict) else None
    extra = f" Available keys: {keys}" if keys is not None else ""
    return ValueError(f"[SCHEMA ERROR] {run_folder} line {line_no}: {msg}.{extra}")

def validate_frame_obj(run_folder: Path, line_no: int, obj: Dict[str, Any]) -> None:
    for k in REQUIRED_FRAME_KEYS:
        if k not in obj:
            raise schema_error(run_folder, line_no, f"Missing required key '{k}' (expected {REQUIRED_FRAME_KEYS})", obj)
    if not isinstance(obj["detections"], list):
        raise schema_error(run_folder, line_no, f"'detections' must be a list, got {type(obj['detections'])}", obj)

def pick_fps(run_folder: Path, line_no: int, obj: Dict[str, Any]) -> Tuple[float, str]:
    # prefer fps_used_for_timestamps, fallback to fps_reported
    if "fps_used_for_timestamps" in obj and obj["fps_used_for_timestamps"] is not None:
        return float(obj["fps_used_for_timestamps"]), "fps_used_for_timestamps"
    if "fps_reported" in obj and obj["fps_reported"] is not None:
        return float(obj["fps_reported"]), "fps_reported"
    raise schema_error(run_folder, line_no, f"Missing FPS key (expected one of {FPS_KEYS_ACCEPTED})", obj)

def read_raw_count(obj: Dict[str, Any]) -> int:
    if "raw_detections_in_frame" in obj and obj["raw_detections_in_frame"] is not None:
        try:
            return int(obj["raw_detections_in_frame"])
        except Exception:
            return 0
    return 0

# ----------------------------
# Track object
# ----------------------------


def _git_stamp() -> dict:
    """
    Returns git metadata if available; otherwise returns None fields.
    Safe if script is copied outside repo.
    """
    import subprocess
    from pathlib import Path

    script_dir = Path(__file__).resolve().parent
    def run_git(args):
        try:
            r = subprocess.run(
                ["git", "-C", str(script_dir)] + args,
                capture_output=True, text=True, check=True
            )
            return r.stdout.strip()
        except Exception:
            return None

    commit = run_git(["rev-parse", "HEAD"])
    describe = run_git(["describe", "--tags", "--always", "--dirty"])
    is_dirty = None
    try:
        r = subprocess.run(
            ["git", "-C", str(script_dir), "status", "--porcelain"],
            capture_output=True, text=True, check=True
        )
        is_dirty = (r.stdout.strip() != "")
    except Exception:
        is_dirty = None

    return {
        "git_commit": commit,
        "git_describe": describe,
        "git_is_dirty": is_dirty
    }

class Track:
    def __init__(
        self,
        track_id: int,
        frame_index: int,
        timestamp_s: float,
        det: Dict[str, Any],
        track_mode: str,
        persist_mode: str,
        n_consec: int,
        hits_needed: int,
        window_frames: int,
    ):
        self.track_id = track_id
        self.track_mode = track_mode
        self.persist_mode = persist_mode

        self.start_frame = frame_index
        self.end_frame = frame_index
        self.start_time_s = float(timestamp_s)
        self.end_time_s = float(timestamp_s)

        self.last_frame_seen = frame_index
        self.missed = 0

        self.members: List[Dict[str, Any]] = []

        self.max_confidence = float(det["confidence"])
        self.rep_frame = frame_index
        self.rep_bbox = det["bbox_xyxy"]
        self.rep_class_name = det["class_name"]

        self.class_hist: Dict[str, int] = {}
        self._bump_class(det["class_name"])

        self.last_center = det["center_xy"]

        # persistence state
        self.hits_total = 0
        self.hits_consec = 0
        self.max_hits_consec = 0

        # window persistence
        self.hit_frames: List[int] = []
        self.confirmed_at_frame: Optional[int] = None
        self.confirmed_start_frame: Optional[int] = None

        # for diagnostics (window mode)
        self.max_hits_in_window = 1

        self.update(frame_index, timestamp_s, det, n_consec, hits_needed, window_frames)

    def _bump_class(self, cls: str):
        self.class_hist[cls] = self.class_hist.get(cls, 0) + 1

    def can_match(self, det: Dict[str, Any], dist_px: float) -> bool:
        if self.track_mode == "class":
            if det["class_name"] != self.rep_class_name:
                return False
        return dist(self.last_center, det["center_xy"]) <= dist_px

    def match_distance(self, det: Dict[str, Any]) -> float:
        return dist(self.last_center, det["center_xy"])

    def _update_max_hits_in_window(self, frame_index: int, window_frames: int) -> None:
        lo = frame_index - (window_frames - 1)
        in_window = [f for f in self.hit_frames if f >= lo]
        self.max_hits_in_window = max(self.max_hits_in_window, len(in_window))

    def update(
        self,
        frame_index: int,
        timestamp_s: float,
        det: Dict[str, Any],
        n_consec: int,
        hits_needed: int,
        window_frames: int,
    ):
        if frame_index == self.last_frame_seen + 1:
            self.hits_consec += 1
        else:
            self.hits_consec = 1
        self.max_hits_consec = max(self.max_hits_consec, self.hits_consec)

        self.hits_total += 1
        self.hit_frames.append(frame_index)

        self.end_frame = frame_index
        self.end_time_s = float(timestamp_s)
        self.last_frame_seen = frame_index
        self.missed = 0

        self.last_center = det["center_xy"]
        self._bump_class(det["class_name"])

        if float(det["confidence"]) > self.max_confidence:
            self.max_confidence = float(det["confidence"])
            self.rep_frame = frame_index
            self.rep_bbox = det["bbox_xyxy"]
            self.rep_class_name = det["class_name"]

        self.members.append({
            "frame_index": int(frame_index),
            "timestamp_s": float(timestamp_s),
            "class_name": det["class_name"],
            "confidence": float(det["confidence"]),
            "bbox_xyxy": det["bbox_xyxy"],
            "center_xy": [det["center_xy"][0], det["center_xy"][1]],
        })

        # persistence confirmation
        if self.confirmed_at_frame is None:
            if self.persist_mode == "consecutive":
                if self.hits_consec >= n_consec:
                    self.confirmed_at_frame = frame_index
                    self.confirmed_start_frame = frame_index - (n_consec - 1)

            elif self.persist_mode == "window":
                self._update_max_hits_in_window(frame_index, window_frames)
                lo = frame_index - (window_frames - 1)
                in_window = [f for f in self.hit_frames if f >= lo]
                if len(in_window) >= hits_needed:
                    self.confirmed_at_frame = frame_index
                    self.confirmed_start_frame = min(in_window)
        else:
            if self.persist_mode == "window":
                self._update_max_hits_in_window(frame_index, window_frames)

# ----------------------------
# ROI handling
# ----------------------------
def load_roi(roi_path: Path) -> Dict[str, Any]:
    roi = json.loads(roi_path.read_text(encoding="utf-8"))
    if "polygon" not in roi:
        raise ValueError("ROI file missing 'polygon'")
    # backward-compatible defaults
    roi.setdefault("roi_version", None)
    roi.setdefault("created_from_video", None)
    roi.setdefault("created_by", None)
    return roi

def resolve_out_dir(run_folder: Path, roi_id: str, out_arg: Optional[str]) -> Path:
    if out_arg is None:
        return run_folder / "events" / roi_id
    p = Path(out_arg)
    if not p.is_absolute():
        p = run_folder / p
    return p

# ----------------------------
# Main
# ----------------------------
def main():
    ap = argparse.ArgumentParser(description="Single runner: ROI + conf + tracking + persistence -> events + metrics (no re-inference).")
    ap.add_argument("--run-folder", required=True)
    ap.add_argument("--roi", required=True)
    ap.add_argument("--out", default=None)

    ap.add_argument("--conf", type=float, default=0.15)
    ap.add_argument("--dist-px", type=float, default=120.0)
    ap.add_argument("--gap-frames", type=int, default=2)

    ap.add_argument("--track-mode", choices=["class", "any"], default="class")
    ap.add_argument("--persist-mode", choices=["consecutive", "window"], default="consecutive")
    ap.add_argument("--n-consec", type=int, default=3)

    ap.add_argument("--hits", type=int, default=2)
    ap.add_argument("--window", type=int, default=10)

    ap.add_argument("--include-members", action="store_true")
    args = ap.parse_args()

    run_folder = Path(args.run_folder).expanduser().resolve()
    roi_path = Path(args.roi).expanduser().resolve()
    jsonl_path = run_folder / "detections.jsonl"

    if not run_folder.exists():
        raise SystemExit(f"Missing run folder: {run_folder}")
    if not jsonl_path.exists():
        raise SystemExit(f"Missing detections.jsonl: {jsonl_path}")
    if not roi_path.exists():
        raise SystemExit(f"Missing ROI file: {roi_path}")

    roi = load_roi(roi_path)
    roi_id = roi.get("roi_id", "roi_unknown")
    poly = [(float(x), float(y)) for x, y in roi["polygon"]]

    out_dir = resolve_out_dir(run_folder, roi_id, args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Copy ROI used into output for reproducibility
    (out_dir / roi_path.name).write_text(json.dumps(roi, indent=2), encoding="utf-8")

    # Metrics counters
    fps_used: Optional[float] = None
    fps_source: Optional[str] = None
    timestamp_source: Optional[str] = "timestamp_s"  # we always use jsonl timestamp_s

    video_filename = None
    width = None
    height = None

    total_frames = 0
    total_raw = 0
    total_whitelist = 0
    total_roi_pass = 0
    total_roi_conf_pass = 0
    discarded_by_roi = 0
    discarded_by_conf = 0

    # Diagnostics
    top_roi_conf_dets: List[Dict[str, Any]] = []  # top by confidence (ROI+CONF passing)
    roi_conf_by_class: Dict[str, int] = {}

    # Tracking state
    active: List[Track] = []
    finished: List[Track] = []
    next_track_id = 1

    # Process frames
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise schema_error(run_folder, line_no, f"Invalid JSON: {e}")

            if not isinstance(obj, dict):
                raise schema_error(run_folder, line_no, "Top-level JSON object must be a dict", obj if isinstance(obj, dict) else None)

            validate_frame_obj(run_folder, line_no, obj)

            total_frames += 1

            # fps + metadata (from first frame that has them)
            if fps_used is None:
                fps_used, fps_source = pick_fps(run_folder, line_no, obj)

            if video_filename is None:
                if "video_filename" in obj and obj["video_filename"] is not None:
                    video_filename = obj["video_filename"]
                else:
                    raise schema_error(run_folder, line_no, f"Missing 'video_filename' (expected at least on first frames)", obj)

            if width is None:
                if "width" in obj and obj["width"] is not None:
                    width = int(obj["width"])
                else:
                    raise schema_error(run_folder, line_no, f"Missing 'width' (expected at least on first frames)", obj)

            if height is None:
                if "height" in obj and obj["height"] is not None:
                    height = int(obj["height"])
                else:
                    raise schema_error(run_folder, line_no, f"Missing 'height' (expected at least on first frames)", obj)

            frame_index = int(obj["frame_index"])
            timestamp_s = float(obj["timestamp_s"])

            total_raw += read_raw_count(obj)

            dets = obj["detections"]
            total_whitelist += len(dets)

            # Build candidates after ROI+CONF
            candidates: List[Dict[str, Any]] = []
            for di, d in enumerate(dets):
                if not isinstance(d, dict):
                    raise schema_error(run_folder, line_no, f"Detection entry at index {di} must be a dict", obj)
                for k in REQUIRED_DET_KEYS:
                    if k not in d:
                        raise schema_error(run_folder, line_no, f"Detection missing key '{k}' (expected {REQUIRED_DET_KEYS})", obj)

                cls = str(d.get("class_name", "unknown"))
                conf = float(d.get("confidence", 0.0))
                x1 = float(d["x1"]); y1 = float(d["y1"]); x2 = float(d["x2"]); y2 = float(d["y2"])
                cx, cy = bbox_center_xyxy(x1, y1, x2, y2)

                if not point_in_polygon(cx, cy, poly):
                    discarded_by_roi += 1
                    continue
                total_roi_pass += 1

                if conf < float(args.conf):
                    discarded_by_conf += 1
                    continue

                total_roi_conf_pass += 1

                det_obj = {
                    "class_name": cls,
                    "confidence": conf,
                    "bbox_xyxy": [x1, y1, x2, y2],
                    "center_xy": (cx, cy),
                    "frame_index": frame_index,
                    "timestamp_s": timestamp_s
                }
                candidates.append(det_obj)

                roi_conf_by_class[cls] = roi_conf_by_class.get(cls, 0) + 1
                topk_insert(top_roi_conf_dets, {
                    "frame_index": frame_index,
                    "timestamp_s": timestamp_s,
                    "class_name": cls,
                    "confidence": conf,
                    "bbox_xyxy": [x1, y1, x2, y2],
                    "center_xy": [cx, cy]
                }, k=5)

            # Greedy matching
            matched_track_ids = set()
            for det in candidates:
                best_t = None
                best_d = None
                for t in active:
                    if not t.can_match(det, float(args.dist_px)):
                        continue
                    dval = t.match_distance(det)
                    if best_d is None or dval < best_d:
                        best_d = dval
                        best_t = t

                if best_t is None:
                    t = Track(
                        track_id=next_track_id,
                        frame_index=frame_index,
                        timestamp_s=timestamp_s,
                        det=det,
                        track_mode=args.track_mode,
                        persist_mode=args.persist_mode,
                        n_consec=int(args.n_consec),
                        hits_needed=int(args.hits),
                        window_frames=int(args.window),
                    )
                    next_track_id += 1
                    active.append(t)
                    matched_track_ids.add(t.track_id)
                else:
                    best_t.update(
                        frame_index=frame_index,
                        timestamp_s=timestamp_s,
                        det=det,
                        n_consec=int(args.n_consec),
                        hits_needed=int(args.hits),
                        window_frames=int(args.window),
                    )
                    matched_track_ids.add(best_t.track_id)

            # Missed handling / close tracks
            still_active = []
            for t in active:
                if t.track_id not in matched_track_ids:
                    t.missed += 1
                if t.missed > int(args.gap_frames):
                    finished.append(t)
                else:
                    still_active.append(t)
            active = still_active

    finished.extend(active)

    # Convert confirmed tracks -> events (but do not assign event_id until after sorting)
    def member_map(track: Track) -> Dict[int, Dict[str, Any]]:
        return {int(m["frame_index"]): m for m in track.members}

    raw_events: List[Dict[str, Any]] = []
    for t in finished:
        if t.confirmed_at_frame is None or t.confirmed_start_frame is None:
            continue

        start_frame = int(t.confirmed_start_frame)
        end_frame = int(t.end_frame)

        mb = member_map(t)
        start_time_s = float(mb.get(start_frame, {"timestamp_s": t.start_time_s})["timestamp_s"])
        end_time_s = float(mb.get(end_frame, {"timestamp_s": t.end_time_s})["timestamp_s"])
        duration_s = max(0.0, end_time_s - start_time_s)

        ev_class = t.rep_class_name

        ev = {
            "video_filename": video_filename,
            "class_name": ev_class,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "start_time_s": start_time_s,
            "end_time_s": end_time_s,
            "duration_s": duration_s,
            "max_confidence": float(t.max_confidence),
            "representative_bbox": t.rep_bbox,
            "rep_frame": int(t.rep_frame),
            "roi_id": roi_id,
            "roi_version": roi.get("roi_version"),
            "trigger_frame": int(t.confirmed_at_frame),
            "track_mode": args.track_mode,
            "persist_mode": args.persist_mode,
            "class_histogram": t.class_hist if args.track_mode == "any" else None,
            "parameters": {
                "CONF_EVENT": float(args.conf),
                "DIST_PX": float(args.dist_px),
                "GAP_FRAMES": int(args.gap_frames),
                "TRACK_MODE": args.track_mode,
                "PERSIST_MODE": args.persist_mode,
                "N_CONSEC": int(args.n_consec) if args.persist_mode == "consecutive" else None,
                "HITS": int(args.hits) if args.persist_mode == "window" else None,
                "WINDOW_FRAMES": int(args.window) if args.persist_mode == "window" else None,
            },
        }
        if args.include_members:
            ev["members"] = t.members
        raw_events.append(ev)

    # Deterministic ordering + deterministic IDs
    raw_events.sort(key=lambda e: (int(e["start_frame"]), str(e["class_name"]), int(e["end_frame"]), int(e["rep_frame"])))
    events: List[Dict[str, Any]] = []
    for i, ev in enumerate(raw_events, start=1):
        ev2 = dict(ev)
        ev2["event_id"] = f"ev_{i:04d}"
        events.append(ev2)

    # Write events.csv (stable order)
    csv_path = out_dir / "events.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fcsv:
        w = csv.writer(fcsv)
        w.writerow([
            "video_filename","event_id","class_name",
            "start_frame","end_frame","start_time_s","end_time_s","duration_s",
            "max_confidence","representative_bbox","rep_frame","roi_id","parameters_used"
        ])
        for ev in events:
            bbox = ev["representative_bbox"]
            bbox_str = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
            params = ev["parameters"]
            if args.persist_mode == "consecutive":
                persist_str = f"N_CONSEC={params['N_CONSEC']}"
            else:
                persist_str = f"HITS={params['HITS']};WINDOW_FRAMES={params['WINDOW_FRAMES']}"
            params_used = (
                f"CONF_EVENT={params['CONF_EVENT']};{persist_str};"
                f"DIST_PX={params['DIST_PX']};GAP_FRAMES={params['GAP_FRAMES']};"
                f"TRACK_MODE={params['TRACK_MODE']};PERSIST_MODE={params['PERSIST_MODE']};"
                f"roi_id={roi_id}"
            )
            w.writerow([
                ev["video_filename"], ev["event_id"], ev["class_name"],
                ev["start_frame"], ev["end_frame"],
                f"{ev['start_time_s']:.6f}", f"{ev['end_time_s']:.6f}", f"{ev['duration_s']:.6f}",
                f"{ev['max_confidence']:.6f}",
                bbox_str,
                ev["rep_frame"],
                ev["roi_id"],
                params_used
            ])

    # Write events.json (stable order)
    (out_dir / "events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")

    # Metrics (self-contained config + diagnostics)
    duration_total_s = (float(total_frames) / float(fps_used)) if fps_used else None
    proxy_events_per_minute = (len(events) / (duration_total_s / 60.0)) if duration_total_s and duration_total_s > 0 else None

    tracks_total = len(finished)
    tracks_confirmed = sum(1 for t in finished if t.confirmed_at_frame is not None)

    # No-event diagnostics
    max_hits_consec_all = max((t.max_hits_consec for t in finished), default=0)
    max_hits_in_window_all = max((t.max_hits_in_window for t in finished), default=0)

    no_event_diag = None
    if len(events) == 0:
        no_event_diag = {
            "total_roi_conf_pass_detections": total_roi_conf_pass,
            "max_hits_consec_over_tracks": max_hits_consec_all,
            "max_hits_in_window_over_tracks": max_hits_in_window_all if args.persist_mode == "window" else None,
            "top_roi_conf_detections_by_confidence": top_roi_conf_dets,
            "roi_conf_pass_by_class": roi_conf_by_class,
            "note": "0 events is expected if persistence threshold is not met (e.g., only 1 hit total for a run)."
        }

    metrics = {

      "tool": {

        "name": "events_from_detections.py",

        "version": __version__,

        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z"),

        **_git_stamp()

      },
        # core run stats
        "video_filename": video_filename,
        "run_folder": str(run_folder),
        "detections_jsonl": str(jsonl_path),
        "frame_size": [width, height],
        "total_frames": total_frames,
        "duration_s": duration_total_s,

        # timestamping
        "timestamping": {
            "timestamp_source": timestamp_source,   # always jsonl timestamp_s
            "fps_used_for_timestamps": fps_used,
            "fps_source_key": fps_source,
            "fps_source_field_in_jsonl": obj.get("fps_source", None) if isinstance(locals().get("obj", None), dict) else None,
        },

        # counts
        "total_raw_detections": total_raw,
        "total_whitelist_detections": total_whitelist,
        "total_roi_pass_detections": total_roi_pass,
        "total_roi_conf_pass_detections": total_roi_conf_pass,
        "discarded_by_roi": discarded_by_roi,
        "discarded_by_conf": discarded_by_conf,

        # tracking/event summary
        "tracking": {
            "tracks_total": tracks_total,
            "tracks_confirmed": tracks_confirmed
        },
        "total_events": len(events),

        # renamed to prevent misinterpretation
        "proxy_events_per_minute": proxy_events_per_minute,

        # self-contained config object (reproducible without shell history)
        "config": {
            "input_run_folder": str(run_folder),
            "roi": {
                "roi_path": str(roi_path),
                "roi_id": roi_id,
                "roi_version": roi.get("roi_version"),
                "created_from_video": roi.get("created_from_video"),
                "created_by": roi.get("created_by"),
                "polygon": roi.get("polygon"),
                "frame_size": roi.get("frame_size", [width, height]),
                "lens_mm": roi.get("lens_mm", None),
            },
            "thresholds": {
                "CONF_EVENT": float(args.conf),
                "DIST_PX": float(args.dist_px),
                "GAP_FRAMES": int(args.gap_frames),
            },
            "modes": {
                "TRACK_MODE": args.track_mode,
                "PERSIST_MODE": args.persist_mode,
                "N_CONSEC": int(args.n_consec) if args.persist_mode == "consecutive" else None,
                "HITS": int(args.hits) if args.persist_mode == "window" else None,
                "WINDOW_FRAMES": int(args.window) if args.persist_mode == "window" else None,
            },
            "output": {
                "out_dir": str(out_dir),
                "events_csv": str(csv_path),
                "events_json": str(out_dir / "events.json"),
                "metrics_json": str(out_dir / "metrics.json"),
            }
        },

        # explicit schema expectations for easier debugging
        "schema_expectations": {
            "required_frame_keys": REQUIRED_FRAME_KEYS,
            "fps_keys_accepted": FPS_KEYS_ACCEPTED,
            "required_detection_keys": REQUIRED_DET_KEYS,
            "notes": "If a run fails schema validation, error points to run folder + line number + missing keys."
        },

        # conditional diagnostics for 0-event runs
        "no_event_diagnostics": no_event_diag,
    }

    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print("Wrote:", csv_path)
    print("Wrote:", out_dir / "events.json")
    print("Wrote:", out_dir / "metrics.json")
    print("Events:", len(events), "| proxy_events_per_minute:", proxy_events_per_minute)

if __name__ == "__main__":
    main()
