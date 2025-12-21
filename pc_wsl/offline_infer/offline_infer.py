#!/usr/bin/env python3
__version__ = "v0.2.0"  # 2025-12-21
__repo_note__ = "offline inference runner - reproducibility stamp"

import argparse
import csv
import json
import time
from pathlib import Path

import cv2
from ultralytics import YOLO

WHITELIST = {
    "bottle", "cup", "wine glass",
    "backpack", "handbag",
    "cell phone", "remote", "book",
    "bicycle",
}

def main():
    ap = argparse.ArgumentParser(description="Offline MP4 -> YOLO detections (CSV + JSONL)")
    ap.add_argument("--video", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--model", default="yolov8n.pt")  # keep yolov8n baseline
    ap.add_argument("--device", default="0")          # 0 for GPU, or 'cpu'
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--max-frames", type=int, default=0, help="0 = all frames")
    ap.add_argument("--run-tag", default="", help="Optional tag to avoid overwriting outputs (e.g. y8_conf025)")
    args = ap.parse_args()

    video_path = Path(args.video).expanduser().resolve()
    if not video_path.exists():
        raise SystemExit(f"ERROR: video not found: {video_path}")

    out_root = Path(args.outdir).expanduser().resolve()
    run_name = video_path.stem if not args.run_tag else f"{video_path.stem}__{args.run_tag}"
    out_dir = out_root / run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "detections.csv"
    jsonl_path = out_dir / "detections.jsonl"
    summary_path = out_dir / "summary.json"

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SystemExit(f"ERROR: cannot open video: {video_path}")

    fps_reported = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    reported_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    # Timestamp FPS: use reported FPS if valid; otherwise fall back and record that fact
    if fps_reported > 0.0:
        fps_used = fps_reported
        fps_source = "CAP_PROP_FPS"
    else:
        fps_used = 30.0
        fps_source = "fallback_30"

    model = YOLO(args.model)
    names = model.names

    frames_processed = 0

    # Sanity check #2 counts
    total_detections_raw = 0          # before whitelist filtering
    total_detections_whitelisted = 0  # after whitelist filtering (== rows in CSV)
    frames_with_raw = 0
    frames_with_whitelisted = 0

    t0 = time.perf_counter()

    with open(csv_path, "w", newline="", encoding="utf-8") as fcsv, \
         open(jsonl_path, "w", encoding="utf-8") as fjsonl:

        wcsv = csv.writer(fcsv)
        wcsv.writerow([
            "video_filename", "frame_index", "timestamp_s",
            "class_name", "confidence", "x1", "y1", "x2", "y2"
        ])

        frame_index = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if args.max_frames and frames_processed >= args.max_frames:
                break

            timestamp_s = frame_index / fps_used

            r = model.predict(
                source=frame,
                device=args.device,
                imgsz=args.imgsz,
                conf=args.conf,
                verbose=False
            )[0]

            raw_count = 0
            if r.boxes is not None:
                raw_count = len(r.boxes)

            total_detections_raw += raw_count
            if raw_count > 0:
                frames_with_raw += 1

            dets = []
            if r.boxes is not None and raw_count > 0:
                for b in r.boxes:
                    cls_id = int(b.cls.item())
                    cls_name = names.get(cls_id, str(cls_id))
                    conf = float(b.conf.item())
                    x1, y1, x2, y2 = [float(v) for v in b.xyxy[0].tolist()]

                    # whitelist filter
                    if cls_name not in WHITELIST:
                        continue

                    dets.append({
                        "class_name": cls_name,
                        "confidence": conf,
                        "x1": x1, "y1": y1, "x2": x2, "y2": y2
                    })

                    wcsv.writerow([
                        video_path.name, frame_index, f"{timestamp_s:.6f}",
                        cls_name, f"{conf:.6f}",
                        f"{x1:.2f}", f"{y1:.2f}", f"{x2:.2f}", f"{y2:.2f}"
                    ])
                    total_detections_whitelisted += 1

            if dets:
                frames_with_whitelisted += 1

            # JSONL per frame
            rec = {
                "video_filename": video_path.name,
                "frame_index": frame_index,
                "timestamp_s": timestamp_s,
                "fps_reported": fps_reported,
                "fps_used_for_timestamps": fps_used,
                "fps_source": fps_source,
                "width": width,
                "height": height,
                "raw_detections_in_frame": raw_count,
                "detections": dets
            }
            fjsonl.write(json.dumps(rec) + "\n")

            frames_processed += 1
            frame_index += 1

    cap.release()

    t1 = time.perf_counter()
    elapsed = max(1e-9, t1 - t0)
    speed_fps = frames_processed / elapsed
    last_timestamp_s = (frames_processed - 1) / fps_used if frames_processed > 0 else 0.0

    summary = {
        "video": str(video_path),
        "video_filename": video_path.name,
        "output_dir": str(out_dir),

        "model": args.model,
        "device": args.device,
        "conf": args.conf,
        "imgsz": args.imgsz,
        "whitelist": sorted(list(WHITELIST)),

        "video_fps_reported": fps_reported,
        "timestamp_fps_used": fps_used,
        "timestamp_fps_source": fps_source,

        "video_width": width,
        "video_height": height,
        "video_frame_count_reported": reported_frames,

        "frames_processed": frames_processed,
        "last_timestamp_s": last_timestamp_s,

        # Sanity check #2: whitelist effect proof
        "total_detections_raw_before_whitelist": total_detections_raw,
        "total_detections_after_whitelist": total_detections_whitelisted,
        "frames_with_any_raw_detections": frames_with_raw,
        "frames_with_any_whitelisted_detections": frames_with_whitelisted,

        "processing_time_s": elapsed,
        "processing_speed_fps": speed_fps,

        "csv_path": str(csv_path),
        "jsonl_path": str(jsonl_path),
        "jsonl_mode": "per_frame"
    }

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("[OK] Completed")
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
