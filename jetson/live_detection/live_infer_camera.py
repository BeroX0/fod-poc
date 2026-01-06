#!/usr/bin/env python3
import os
import time
import json
import argparse
from pathlib import Path

import numpy as np
import cv2

# GStreamer / appsink
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

from ultralytics import YOLO  # noqa: E402


def build_pipeline(sensor_mode: int, width: int, height: int, fps_num: int, fps_den: int) -> str:
    # Keep identical to gst_capture_test approach: NVMM -> nvvidconv -> BGRx -> appsink
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
        data = mapinfo.data  # bytes-like
        # Expect BGRx: 4 bytes per pixel
        arr = np.frombuffer(data, dtype=np.uint8)
        expected = width * height * 4
        if arr.size != expected:
            return None
        frame_bgrx = arr.reshape((height, width, 4))
        frame_bgr = frame_bgrx[:, :, :3].copy()  # drop alpha channel; copy to own memory
        return frame_bgr
    finally:
        buf.unmap(mapinfo)


def draw_boxes(img_bgr: np.ndarray, boxes_xyxy: np.ndarray, confs: np.ndarray, cls_names: list[str]) -> np.ndarray:
    out = img_bgr.copy()
    h, w = out.shape[:2]
    for i in range(len(boxes_xyxy)):
        x1, y1, x2, y2 = boxes_xyxy[i].tolist()
        x1 = int(max(0, min(w - 1, round(x1))))
        y1 = int(max(0, min(h - 1, round(y1))))
        x2 = int(max(0, min(w - 1, round(x2))))
        y2 = int(max(0, min(h - 1, round(y2))))
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)

        label = f"{cls_names[i]} {confs[i]:.2f}"
        cv2.putText(out, label, (x1, max(0, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Live camera -> YOLO GPU inference -> periodic overlay frames")
    ap.add_argument("--model", default="/home/fod/projects/fod_poc/models/yolov8n.pt", help="Path to YOLO model")
    ap.add_argument("--out_dir", default="/data/live_runs/logs", help="Where overlay images will be written")
    ap.add_argument("--duration_s", type=float, default=30.0, help="How long to run")
    ap.add_argument("--save_every_n", type=int, default=60, help="Save overlay every N frames")
    ap.add_argument("--sensor_mode", type=int, default=2, help="Argus sensor-mode")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--fps_num", type=int, default=30)
    ap.add_argument("--fps_den", type=int, default=1)
    ap.add_argument("--conf", type=float, default=0.25, help="YOLO confidence threshold")
    ap.add_argument("--imgsz", type=int, default=640, help="YOLO inference size (ultralytics will scale outputs back)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[env] PYTHONNOUSERSITE =", os.environ.get("PYTHONNOUSERSITE"))
    print("[run] out_dir =", str(out_dir))
    print("[run] duration_s =", args.duration_s, "save_every_n =", args.save_every_n)
    print("[cam] w,h =", args.width, args.height, "sensor_mode =", args.sensor_mode, "fps =", f"{args.fps_num}/{args.fps_den}")

    Gst.init(None)
    pipeline_str = build_pipeline(args.sensor_mode, args.width, args.height, args.fps_num, args.fps_den)
    print("[capture] Pipeline:", pipeline_str)

    pipeline = Gst.parse_launch(pipeline_str)
    appsink = pipeline.get_by_name("sink")
    if appsink is None:
        raise RuntimeError("appsink element not found (name=sink). Pipeline creation failed?")

    # Start streaming
    ret = pipeline.set_state(Gst.State.PLAYING)
    if ret == Gst.StateChangeReturn.FAILURE:
        raise RuntimeError("Failed to set pipeline to PLAYING")

    # Load model
    model = YOLO(args.model)
    names_map = model.model.names  # dict: class_id -> name
    print("[yolo] model loaded:", args.model)
    print("[yolo] names count:", len(names_map))
    print("[yolo] running on device=0 (GPU)")

    start = time.time()
    frames = 0
    saved = 0
    last_save_path = None

    try:
        while True:
            now = time.time()
            if now - start >= args.duration_s:
                break

            frame = appsink_pull_frame(pipeline, appsink, args.width, args.height)
            if frame is None:
                continue

            frames += 1

            # Ultralytics returns boxes already scaled to original frame size.
            results = model.predict(
                source=frame,
                device=0,
                imgsz=args.imgsz,
                conf=args.conf,
                verbose=False
            )
            r = results[0]
            if r.boxes is None or len(r.boxes) == 0:
                if frames % args.save_every_n == 0:
                    # Save "no detections" overlay anyway (helps prove loop is running)
                    out_path = out_dir / f"overlay_{saved:04d}_nodet.jpg"
                    cv2.imwrite(str(out_path), frame)
                    last_save_path = str(out_path)
                    saved += 1
                continue

            xyxy = r.boxes.xyxy.cpu().numpy()
            confs = r.boxes.conf.cpu().numpy()
            clses = r.boxes.cls.cpu().numpy().astype(int)

            cls_names = [names_map.get(int(c), str(int(c))) for c in clses]

            if frames % args.save_every_n == 0:
                overlay = draw_boxes(frame, xyxy, confs, cls_names)
                out_path = out_dir / f"overlay_{saved:04d}.jpg"
                cv2.imwrite(str(out_path), overlay)
                last_save_path = str(out_path)
                saved += 1

                # Print one representative bbox to prove full-frame coordinates
                x1, y1, x2, y2 = xyxy[0].tolist()
                print(f"[det] frame={frames} saved={out_path.name} "
                      f"bbox0_xyxy=({x1:.1f},{y1:.1f},{x2:.1f},{y2:.1f}) conf={confs[0]:.2f} cls={cls_names[0]} "
                      f"frame_wh=({args.width},{args.height})")

        elapsed = time.time() - start
        fps = frames / elapsed if elapsed > 0 else 0.0
        print(f"[done] frames={frames} elapsed_s={elapsed:.2f} avg_fps={fps:.2f} saved_overlays={saved}")
        if last_save_path:
            print("[done] last_overlay =", last_save_path)

        # Write a tiny run metadata file (useful for audit; stays in runtime dir)
        meta = {
            "ts_start": start,
            "duration_s": args.duration_s,
            "frames": frames,
            "avg_fps": fps,
            "saved_overlays": saved,
            "pipeline": pipeline_str,
            "model": args.model,
            "imgsz": args.imgsz,
            "conf": args.conf,
            "width": args.width,
            "height": args.height,
        }
        meta_path = out_dir / "live_infer_run_meta.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        print("[meta] wrote", str(meta_path))

        return 0

    finally:
        pipeline.set_state(Gst.State.NULL)


if __name__ == "__main__":
    raise SystemExit(main())
