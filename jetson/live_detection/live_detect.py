#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Make local imports work whether you run from repo root or from this folder
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from roi_utils import load_roi, point_in_polygon  # noqa: E402
from bbox_utils import BBox, bbox_center, clamp_bbox_xyxy  # noqa: E402

# ============================================================
# Evidence Builder schema lock (preferred keys)
# Source: docs/evidence_builder.md "events.json schema (exact, as implemented)"
#
# Required (preferred):
# - event_id
# - video_filename
# - start_time_s, end_time_s   (fallback: time_s / trigger_time_s)
# - representative_bbox        (fallback: bbox)
#
# Optional (preferred):
# - class_name (fallback: label)
# - roi_id (fallback: roi)
# - rep_frame (fallback: trigger_frame)
# ============================================================

EB_REQUIRED_EVENT_KEYS = [
    "event_id",
    "video_filename",
    "start_time_s",
    "end_time_s",
    "representative_bbox",
]


@dataclass
class Event:
    event_id: str
    video_filename: str
    class_name: str
    roi_id: str
    start_time_s: float
    end_time_s: float
    representative_bbox: Tuple[float, float, float, float]
    frame_w: int = 1920  # not required by EB, but useful upstream
    frame_h: int = 1080  # not required by EB, but useful upstream

    def to_eb_dict(self) -> Dict[str, Any]:
        """
        Emits EB-preferred keys. EB tolerates aliases, but we standardize on preferred.
        BBox is written as pixel xyxy in 1920x1080 full-frame coordinate space.
        """
        return {
            "event_id": self.event_id,
            "video_filename": self.video_filename,
            "class_name": self.class_name,
            "roi_id": self.roi_id,
            "start_time_s": float(self.start_time_s),
            "end_time_s": float(self.end_time_s),
            "representative_bbox": [float(x) for x in self.representative_bbox],
            "frame_w": int(self.frame_w),
            "frame_h": int(self.frame_h),
        }


def validate_event_dict(e: Dict[str, Any]) -> None:
    missing = [k for k in EB_REQUIRED_EVENT_KEYS if k not in e]
    if missing:
        raise ValueError(f"Event missing required EB keys: {missing}")

    b = e.get("representative_bbox")
    if not (isinstance(b, (list, tuple)) and len(b) == 4):
        raise ValueError("representative_bbox must be a 4-list/tuple [x1,y1,x2,y2].")

    # Timing sanity
    st = float(e["start_time_s"])
    en = float(e["end_time_s"])
    if en < st:
        raise ValueError(f"end_time_s ({en}) must be >= start_time_s ({st}).")

    # Coordinate sanity (EB interprets in 1920x1080 full-frame space for snapshots)
    fw = int(e.get("frame_w", 1920))
    fh = int(e.get("frame_h", 1080))
    x1, y1, x2, y2 = [float(v) for v in b]

    # Allow a small tolerance; later phases will clamp strictly.
    tol = 5.0
    if x2 < x1 or y2 < y1:
        raise ValueError("representative_bbox must be xyxy (x2>=x1 and y2>=y1).")
    if (x1 < -tol or y1 < -tol or x2 > fw - 1 + tol or y2 > fh - 1 + tol):
        # Do not fail in Phase 0; EB will fail fast if it is far outside.
        pass


def write_events_json(path: Path, events: List[Dict[str, Any]]) -> None:
    for e in events:
        validate_event_dict(e)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(events, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Jetson Live Detection (MVP) -> events.json compatible with Evidence Builder"
    )
    p.add_argument("--roi-id", required=True, help="ROI id (must match a JSON file in the ROIs folder)")
    p.add_argument("--rois-dir", default="~/projects/fod_poc/assets/rois", help="Flattened ROIs folder")
    p.add_argument("--runtime-dir", default="/data/live_runs", help="Runtime root on Jetson")
    p.add_argument("--debug", action="store_true", help="Verbose debug output")
    p.add_argument("--phase0-generate-dummy", action="store_true",
                   help="Phase 0 helper: generate a dummy EB-compatible events.json (no camera).")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    runtime_dir = Path(args.runtime_dir)
    events_path = runtime_dir / "events" / "events.json"

    roi = load_roi(args.rois_dir, args.roi_id)
    if args.debug:
        print(f"[phase0] Loaded ROI {roi.roi_id} with {len(roi.polygon)} points.")

    if args.phase0_generate_dummy:
        dummy_bbox: BBox = clamp_bbox_xyxy((900, 500, 1020, 650), 1920, 1080)
        cx, cy = bbox_center(dummy_bbox)
        inside = point_in_polygon(cx, cy, roi.polygon)

        if args.debug:
            print(f"[phase0] Dummy bbox center=({cx:.1f},{cy:.1f}) inside_roi={inside}")

        ev = Event(
            event_id="live_ev_0001",
            video_filename="LIVE_DUMMY.mp4",  # placeholder; becomes real in Phase 5+
            class_name="cup",
            roi_id=args.roi_id,
            start_time_s=0.0,
            end_time_s=6.0,
            representative_bbox=dummy_bbox,
            frame_w=1920,
            frame_h=1080,
        )

        write_events_json(events_path, [ev.to_eb_dict()])
        print(f"[phase0] Wrote EB-compatible events.json: {events_path}")
        return 0

    print("[phase0] Scaffolding complete. Use --phase0-generate-dummy to write an EB-compatible events.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
