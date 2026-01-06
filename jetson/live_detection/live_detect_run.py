#!/usr/bin/env python3
import os
import time
import json
import argparse
from pathlib import Path
from dataclasses import dataclass

import numpy as np
import cv2

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

from ultralytics import YOLO  # noqa: E402


def build_pipeline(sensor_mode: int, width: int, height: int, fps_num: int, fps_den: int) -> str:
    return (
        f"nvarguscamerasrc sensor-mode={sensor_mode} ! "
        f"video/x-raw(memory:NVMM),width={width},height={height},framerate={fps_num}/{fps_den},format=NV12 ! "
        f"nvvidconv ! "
        f"video/x-raw,format=BGRx,width={width},height={height} ! "
        f"appsink name=sink emit-signals=false sync=false max-buffers=1 drop=true"
    )


def appsink_pull_frame(pipeline: Gst.Pipeline, appsink: Gst.Element, width: int, height: int) -> np.ndarray | None:
    sample = appsink.emit("pull-sample")
    if sample is None:
        return None

    buf = sample.get_buffer()
    ok, mapinfo = buf.map(Gst.MapFlags.READ)
    if not ok:
        return None

    try:
        arr = np.frombuffer(mapinfo.data, dtype=np.uint8)
        expected = width * height * 4  # BGRx
        if arr.size != expected:
            return None
        frame_bgrx = arr.reshape((height, width, 4))
        return frame_bgrx[:, :, :3].copy()
    finally:
        buf.unmap(mapinfo)


def load_roi_polygon(roi_path: Path) -> tuple[str, np.ndarray]:
    with open(roi_path, "r", encoding="utf-8") as f:
        roi = json.load(f)
    roi_id = roi["roi_id"]
    poly = np.array(roi["polygon"], dtype=np.int32)  # Nx2
    return roi_id, poly


def point_in_polygon(cx: float, cy: float, poly: np.ndarray) -> bool:
    # OpenCV expects shape (N,1,2) for pointPolygonTest
    poly_cv = poly.reshape((-1, 1, 2))
    # returns +1,0,-1 (inside, on edge, outside)
    v = cv2.pointPolygonTest(poly_cv, (float(cx), float(cy)), False)
    return v >= 0


@dataclass
class LiveEventState:
    active: bool = False
    start_t: float = 0.0
    last_seen_t: float = 0.0
    representative_bbox: list[float] | None = None
    class_name: str = ""
    confidence: float = 0.0
    frames_confirmed: int = 0
    missing_streak: int = 0


def ensure_events_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("[]", encoding="utf-8")


def append_event(path: Path, event_obj: dict) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    data.append(event_obj)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Live detect -> ROI filter -> temporal event logic -> EB-compatible events.json")
    ap.add_argument("--model", default="/home/fod/projects/fod_poc/models/yolov8n.pt")
    ap.add_argument("--roi", default="/home/fod/projects/fod_poc/assets/rois/roi_1080p_12mm_roadonly_v1.json")
    ap.add_argument("--out_events", default="/data/live_runs/events/events.json")
    ap.add_argument("--out_dir", default="/data/live_runs/logs")
    ap.add_argument("--duration_s", type=float, default=60.0)
    ap.add_argument("--save_every_n", type=int, default=60, help="Save overlay every N frames")
    ap.add_argument("--sensor_mode", type=int, default=2)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--fps_num", type=int, default=30)
    ap.add_argument("--fps_den", type=int, default=1)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--imgsz", type=int, default=640)

    # Temporal logic params (simple defaults)
    ap.add_argument("--confirm_n", type=int, default=3, help="need N consecutive qualified frames to start an event")
    ap.add_argument("--end_miss_m", type=int, default=10, help="end event after M consecutive misses")
    ap.add_argument("--min_event_dur_s", type=float, default=0.25, help="Clamp event duration to avoid zero-length clips")

    # Noise gates
    ap.add_argument("--min_area", type=float, default=3000.0, help="min bbox area in px^2")

    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    events_path = Path(args.out_events)
    ensure_events_file(events_path)

    roi_path = Path(args.roi)
    roi_id, roi_poly = load_roi_polygon(roi_path)

    print("[env] PYTHONNOUSERSITE =", os.environ.get("PYTHONNOUSERSITE"))
    print("[roi] roi_id =", roi_id, "roi_path =", str(roi_path))
    print("[run] duration_s =", args.duration_s, "confirm_n =", args.confirm_n, "end_miss_m =", args.end_miss_m)
    print("[gate] conf >=", args.conf, "min_area >=", args.min_area)
    print("[out] events =", str(events_path))
    print("[out] overlays_dir =", str(out_dir))

    Gst.init(None)
    pipeline_str = build_pipeline(args.sensor_mode, args.width, args.height, args.fps_num, args.fps_den)
    print("[capture] Pipeline:", pipeline_str)

    pipeline = Gst.parse_launch(pipeline_str)
    appsink = pipeline.get_by_name("sink")
    if appsink is None:
        raise RuntimeError("appsink element not found (name=sink).")

    ret = pipeline.set_state(Gst.State.PLAYING)
    if ret == Gst.StateChangeReturn.FAILURE:
        raise RuntimeError("Failed to set pipeline to PLAYING")

    model = YOLO(args.model)
    names_map = model.model.names
    print("[yolo] model loaded:", args.model)
    print("[yolo] running on device=0 (GPU)")

    start = time.time()
    frames = 0
    saved = 0

    state = LiveEventState()
    event_counter = 0

    try:
        while True:
            now = time.time()
            if now - start >= args.duration_s:
                break

            frame = appsink_pull_frame(pipeline, appsink, args.width, args.height)
            if frame is None:
                continue

            frames += 1
            t_rel = now - start

            results = model.predict(
                source=frame,
                device=0,
                imgsz=args.imgsz,
                conf=args.conf,
                verbose=False
            )
            r = results[0]

            best = None  # (conf, cls_name, xyxy)
            if r.boxes is not None and len(r.boxes) > 0:
                xyxy = r.boxes.xyxy.cpu().numpy()
                confs = r.boxes.conf.cpu().numpy()
                clses = r.boxes.cls.cpu().numpy().astype(int)

                for i in range(len(xyxy)):
                    x1, y1, x2, y2 = xyxy[i].tolist()
                    area = max(0.0, (x2 - x1)) * max(0.0, (y2 - y1))
                    if area < args.min_area:
                        continue

                    cx = 0.5 * (x1 + x2)
                    cy = 0.5 * (y1 + y2)
                    if not point_in_polygon(cx, cy, roi_poly):
                        continue

                    c = float(confs[i])
                    name = names_map.get(int(clses[i]), str(int(clses[i])))
                    if best is None or c > best[0]:
                        best = (c, name, [float(x1), float(y1), float(x2), float(y2)])

            qualified = best is not None

            if qualified:
                conf_best, cls_name, bbox = best

                state.last_seen_t = t_rel
                state.missing_streak = 0

                if not state.active:
                    state.frames_confirmed += 1
                    # keep a representative bbox from the confirm window (use latest)
                    state.representative_bbox = bbox
                    state.class_name = cls_name
                    state.confidence = conf_best

                    if state.frames_confirmed >= args.confirm_n:
                        state.active = True
                        state.start_t = t_rel
                        print(f"[event] START t={state.start_t:.3f} cls={state.class_name} conf={state.confidence:.2f} bbox={state.representative_bbox}")
                else:
                    # active: update representative bbox if higher conf
                    if conf_best >= state.confidence:
                        state.confidence = conf_best
                        state.representative_bbox = bbox
                        state.class_name = cls_name

            else:
                if not state.active:
                    # reset confirmation streak if we don't have consecutive frames
                    state.frames_confirmed = 0
                else:
                    state.missing_streak += 1
                    if state.missing_streak >= args.end_miss_m:
                        # end event
                        end_t = max(state.last_seen_t, state.start_t + args.min_event_dur_s)
                        event_counter += 1
                        event_id = f"live_{event_counter:04d}"

                        evt = {
                            "event_id": event_id,
                            "video_filename": "LIVE_CAMERA",
                            "start_time_s": float(state.start_t),
                            "end_time_s": float(end_t),
                            "representative_bbox": state.representative_bbox,
                            "class_name": state.class_name,
                            "confidence": float(state.confidence),
                            "roi_id": roi_id,
                            "frame_w": int(args.width),
                            "frame_h": int(args.height),
                            "source": "jetson_live_camera",
                        }
                        append_event(events_path, evt)
                        print(f"[event] END event_id={event_id} start={state.start_t:.3f} end={end_t:.3f} wrote={events_path}")

                        # reset state
                        state = LiveEventState()

            # Periodic overlay for debugging: draw ROI + bbox if qualified
            if frames % args.save_every_n == 0:
                overlay = frame.copy()
                cv2.polylines(overlay, [roi_poly.reshape((-1, 1, 2))], isClosed=True, color=(255, 0, 0), thickness=2)
                if qualified:
                    _, cls_name, bbox = best
                    x1, y1, x2, y2 = map(int, map(round, bbox))
                    cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(overlay, f"{cls_name} {best[0]:.2f}", (x1, max(0, y1 - 8)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                out_path = out_dir / f"live_detect_overlay_{saved:04d}.jpg"
                cv2.imwrite(str(out_path), overlay)
                saved += 1

        # If event still active at shutdown, close it
        if state.active:
            end_t = max(state.last_seen_t, state.start_t + args.min_event_dur_s)
            event_counter += 1
            event_id = f"live_{event_counter:04d}"
            evt = {
                "event_id": event_id,
                "video_filename": "LIVE_CAMERA",
                "start_time_s": float(state.start_t),
                "end_time_s": float(end_t),
                "representative_bbox": state.representative_bbox,
                "class_name": state.class_name,
                "confidence": float(state.confidence),
                "roi_id": roi_id,
                "frame_w": int(args.width),
                "frame_h": int(args.height),
                "source": "jetson_live_camera",
            }
            append_event(events_path, evt)
            print(f"[event] END_AT_EXIT event_id={event_id} start={state.start_t:.3f} end={end_t:.3f} wrote={events_path}")

        elapsed = time.time() - start
        fps = frames / elapsed if elapsed > 0 else 0.0
        print(f"[done] frames={frames} elapsed_s={elapsed:.2f} avg_fps={fps:.2f} overlays={saved}")
        return 0

    finally:
        pipeline.set_state(Gst.State.NULL)


if __name__ == "__main__":
    raise SystemExit(main())
