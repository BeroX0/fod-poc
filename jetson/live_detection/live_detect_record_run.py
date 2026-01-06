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


def load_roi_polygon(roi_path: Path) -> tuple[str, np.ndarray]:
    roi = json.loads(roi_path.read_text(encoding="utf-8"))
    roi_id = roi["roi_id"]
    poly = np.array(roi["polygon"], dtype=np.int32)  # Nx2 px coords
    return roi_id, poly


def point_in_polygon(cx: float, cy: float, poly: np.ndarray) -> bool:
    poly_cv = poly.reshape((-1, 1, 2))
    v = cv2.pointPolygonTest(poly_cv, (float(cx), float(cy)), False)
    return v >= 0  # inside or on edge


def ensure_events_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("[]", encoding="utf-8")


def append_event(path: Path, event_obj: dict) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    data.append(event_obj)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


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
    cooldown_until_t: float = 0.0


def build_pipeline(
    *,
    tuned: bool,
    sensor_mode: int,
    width: int,
    height: int,
    fps_num: int,
    fps_den: int,
    flip_method: int,
    contrast: float,
    brightness: float,
    saturation: float,
    x264_preset: str,
    x264_bitrate_kbps: int,
    key_int_max: int,
    out_mp4_path: str,
) -> str:
    # Shared camera source -> tee
    if tuned:
        src = (
            "nvarguscamerasrc sensor-id=0 wbmode=6 "
            "exposuretimerange=\"1000000 8000000\" gainrange=\"1.0 8.0\" "
            "ispdigitalgainrange=\"1.0 2.0\" aeantibanding=2 "
            "tnr-mode=2 tnr-strength=0.20 ee-mode=2 ee-strength=0.40"
        )
    else:
        src = f"nvarguscamerasrc sensor-mode={sensor_mode}"

    caps_nvmm = f"video/x-raw(memory:NVMM),width={width},height={height},framerate={fps_num}/{fps_den},format=NV12"

    # Branch A (inference): NVMM -> nvvidconv -> BGRx -> appsink
    branch_infer = (
        f"t. ! queue max-size-buffers=1 leaky=downstream ! "
        f"nvvidconv ! video/x-raw,format=BGRx,width={width},height={height} ! "
        f"appsink name=sink emit-signals=false sync=false max-buffers=1 drop=true"
    )

    # Branch B (record): NVMM -> nvvidconv -> I420 -> videobalance -> x264enc -> qtmux -> filesink
    branch_rec = (
        f"t. ! queue ! "
        f"nvvidconv flip-method={flip_method} ! video/x-raw,format=I420,width={width},height={height} ! "
        f"videobalance contrast={contrast:.2f} brightness={brightness:.2f} saturation={saturation:.2f} ! "
        f"x264enc tune=zerolatency speed-preset={x264_preset} bitrate={x264_bitrate_kbps} key-int-max={key_int_max} ! "
        f"h264parse ! qtmux ! filesink location={out_mp4_path}"
    )

    pipe = f"{src} ! {caps_nvmm} ! tee name=t {branch_infer} {branch_rec}"
    return pipe


def appsink_pull_frame(appsink: Gst.Element, width: int, height: int) -> np.ndarray | None:
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Live: record MP4 + detect (GPU) + ROI + EB events referencing MP4")
    ap.add_argument("--model", default="/home/fod/projects/fod_poc/models/yolov8n.pt")
    ap.add_argument("--roi", default="/home/fod/projects/fod_poc/assets/rois/roi_1080p_12mm_roadonly_v1.json")
    ap.add_argument("--events_out", default="/data/live_runs/events/events.json")
    ap.add_argument("--logs_dir", default="/data/live_runs/logs")
    ap.add_argument("--videos_dir", default="/data/live_runs/videos")
    ap.add_argument("--duration_s", type=float, default=60.0)
    ap.add_argument("--save_every_n", type=int, default=90)

    # Camera / format
    ap.add_argument("--tuned_camera", action="store_true", help="Use the tuned Argus settings (wb/exposure/gain/tnr/ee)")
    ap.add_argument("--sensor_mode", type=int, default=2)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--fps_num", type=int, default=30)
    ap.add_argument("--fps_den", type=int, default=1)
    ap.add_argument("--flip_method", type=int, default=0)

    # Record tuning (match your known-good recording chain)
    ap.add_argument("--contrast", type=float, default=1.20)
    ap.add_argument("--brightness", type=float, default=-0.05)
    ap.add_argument("--saturation", type=float, default=1.30)
    ap.add_argument("--x264_preset", default="superfast")
    ap.add_argument("--x264_bitrate_kbps", type=int, default=6000)
    ap.add_argument("--key_int_max", type=int, default=60)

    # YOLO
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--imgsz", type=int, default=640)

    # ROI/event gates
    ap.add_argument("--min_area", type=float, default=3000.0)
    ap.add_argument("--confirm_n", type=int, default=3)
    ap.add_argument("--end_miss_m", type=int, default=10)
    ap.add_argument("--min_event_dur_s", type=float, default=0.25)
    ap.add_argument("--cooldown_s", type=float, default=1.0)

    args = ap.parse_args()

    logs_dir = Path(args.logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)

    videos_dir = Path(args.videos_dir)
    videos_dir.mkdir(parents=True, exist_ok=True)

    events_path = Path(args.events_out)
    ensure_events_file(events_path)

    roi_id, roi_poly = load_roi_polygon(Path(args.roi))

    run_id = time.strftime("%Y%m%d_%H%M%S")
    mp4_path = videos_dir / f"live_run_{run_id}_{args.width}x{args.height}_{args.fps_num}fps.mp4"
    video_filename = mp4_path.name

    print("[env] PYTHONNOUSERSITE =", os.environ.get("PYTHONNOUSERSITE"))
    print("[roi] roi_id =", roi_id)
    print("[out] mp4 =", str(mp4_path))
    print("[out] events =", str(events_path))
    print("[run] duration_s =", args.duration_s, "save_every_n =", args.save_every_n)
    print("[gate] conf >=", args.conf, "min_area >=", args.min_area, "confirm_n =", args.confirm_n, "end_miss_m =", args.end_miss_m)
    print("[gate] min_event_dur_s =", args.min_event_dur_s, "cooldown_s =", args.cooldown_s)

    Gst.init(None)
    pipeline_str = build_pipeline(
        tuned=args.tuned_camera,
        sensor_mode=args.sensor_mode,
        width=args.width,
        height=args.height,
        fps_num=args.fps_num,
        fps_den=args.fps_den,
        flip_method=args.flip_method,
        contrast=args.contrast,
        brightness=args.brightness,
        saturation=args.saturation,
        x264_preset=args.x264_preset,
        x264_bitrate_kbps=args.x264_bitrate_kbps,
        key_int_max=args.key_int_max,
        out_mp4_path=str(mp4_path),
    )
    print("[gst] Pipeline:", pipeline_str)

    pipeline = Gst.parse_launch(pipeline_str)
    appsink = pipeline.get_by_name("sink")
    if appsink is None:
        raise RuntimeError("appsink element not found (name=sink).")

    bus = pipeline.get_bus()

    # Start pipeline (recording + appsink)
    ret = pipeline.set_state(Gst.State.PLAYING)
    if ret == Gst.StateChangeReturn.FAILURE:
        raise RuntimeError("Failed to set pipeline to PLAYING")

    # Load model
    model = YOLO(args.model)
    names_map = model.model.names
    print("[yolo] model loaded:", args.model)
    print("[yolo] running on device=0 (GPU)")

    # Align t0 to first successfully pulled frame (reduces timestamp skew)
    t0 = None
    frames = 0
    saved = 0
    state = LiveEventState()
    event_counter = 0

    def close_event(end_t_run: float) -> None:
        nonlocal state, event_counter
        if not state.active:
            return

        end_t_run = max(end_t_run, state.start_t + args.min_event_dur_s)

        event_counter += 1
        event_id = f"{run_id}_live_{event_counter:04d}"
        evt = {
            "event_id": event_id,
            "video_filename": video_filename,
            "start_time_s": float(state.start_t),
            "end_time_s": float(end_t_run),
            "representative_bbox": state.representative_bbox,
            "class_name": state.class_name,
            "confidence": float(state.confidence),
            "roi_id": roi_id,
            "frame_w": int(args.width),
            "frame_h": int(args.height),
            "source": "jetson_live_camera_record",
            "run_id": run_id,
        }
        append_event(events_path, evt)
        print(f"[event] END event_id={event_id} start={state.start_t:.3f} end={end_t_run:.3f} video={video_filename}")

        # cooldown to reduce spam
        cooldown_until = end_t_run + args.cooldown_s
        state = LiveEventState(cooldown_until_t=cooldown_until)

    try:
        start_wall = time.time()

        while True:
            now_wall = time.time()
            if now_wall - start_wall >= args.duration_s:
                break

            # Pull a frame
            frame = appsink_pull_frame(appsink, args.width, args.height)
            if frame is None:
                # Drain bus messages quickly (avoid stalling)
                bus.timed_pop_filtered(0, Gst.MessageType.ERROR | Gst.MessageType.EOS)
                continue

            frames += 1

            if t0 is None:
                t0 = time.time()
                print("[time] t0 aligned on first frame")
            t_run = time.time() - t0  # seconds from file start approximately

            # Run YOLO (GPU)
            results = model.predict(
                source=frame,
                device=0,
                imgsz=args.imgsz,
                conf=args.conf,
                verbose=False,
            )
            r = results[0]

            best = None  # (conf, cls_name, bbox_xyxy)
            if r.boxes is not None and len(r.boxes) > 0:
                xyxy = r.boxes.xyxy.cpu().numpy()
                confs = r.boxes.conf.cpu().numpy()
                clses = r.boxes.cls.cpu().numpy().astype(int)

                for i in range(len(xyxy)):
                    x1, y1, x2, y2 = map(float, xyxy[i].tolist())
                    area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
                    if area < args.min_area:
                        continue

                    cx = 0.5 * (x1 + x2)
                    cy = 0.5 * (y1 + y2)
                    if not point_in_polygon(cx, cy, roi_poly):
                        continue

                    c = float(confs[i])
                    name = names_map.get(int(clses[i]), str(int(clses[i])))
                    if best is None or c > best[0]:
                        best = (c, name, [x1, y1, x2, y2])

            qualified = best is not None

            if qualified:
                conf_best, cls_name, bbox = best

                # ignore new events while cooling down
                if not state.active and t_run < state.cooldown_until_t:
                    qualified = False
                else:
                    state.last_seen_t = t_run
                    state.missing_streak = 0

                    if not state.active:
                        state.frames_confirmed += 1
                        state.representative_bbox = bbox
                        state.class_name = cls_name
                        state.confidence = conf_best

                        if state.frames_confirmed >= args.confirm_n:
                            state.active = True
                            state.start_t = t_run
                            print(f"[event] START t={state.start_t:.3f} cls={state.class_name} conf={state.confidence:.2f} video={video_filename}")
                    else:
                        # active: update representative bbox if stronger
                        if conf_best >= state.confidence:
                            state.confidence = conf_best
                            state.representative_bbox = bbox
                            state.class_name = cls_name

            if not qualified:
                if not state.active:
                    state.frames_confirmed = 0
                else:
                    state.missing_streak += 1
                    if state.missing_streak >= args.end_miss_m:
                        close_event(state.last_seen_t)

            # Periodic debug overlay (ROI + bbox if present)
            if frames % args.save_every_n == 0:
                overlay = frame.copy()
                cv2.polylines(overlay, [roi_poly.reshape((-1, 1, 2))], isClosed=True, color=(255, 0, 0), thickness=2)
                if best is not None:
                    c, name, bbox = best
                    x1, y1, x2, y2 = map(int, map(round, bbox))
                    cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(overlay, f"{name} {c:.2f}", (x1, max(0, y1 - 8)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                out_path = logs_dir / f"live_rec_detect_overlay_{run_id}_{saved:04d}.jpg"
                cv2.imwrite(str(out_path), overlay)
                saved += 1

        # Close active event at exit
        if state.active:
            close_event(state.last_seen_t)

        # Send EOS so qtmux finalizes MP4 cleanly
        pipeline.send_event(Gst.Event.new_eos())

        # Wait for EOS (or error) briefly
        msg = bus.timed_pop_filtered(
            5 * Gst.SECOND,
            Gst.MessageType.EOS | Gst.MessageType.ERROR
        )
        if msg is not None and msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            print("[gst] ERROR:", err, dbg)

        elapsed = (time.time() - start_wall)
        fps = frames / elapsed if elapsed > 0 else 0.0
        print(f"[done] frames={frames} elapsed_s={elapsed:.2f} avg_fps={fps:.2f} overlays={saved}")
        print("[done] mp4 =", str(mp4_path))
        print("[done] events =", str(events_path))
        return 0

    finally:
        pipeline.set_state(Gst.State.NULL)


if __name__ == "__main__":
    raise SystemExit(main())
