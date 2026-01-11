#!/usr/bin/env python3
from pathlib import Path
import datetime
import sys

TARGET_DEFAULT = "jetson/live_detection/live_detect_record_run.py"

def find_line_index(lines, contains):
    for i, line in enumerate(lines):
        if contains in line:
            return i
    return None

def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(TARGET_DEFAULT)
    if not target.exists():
        print(f"ERROR: file not found: {target}")
        return 1

    src = target.read_text()

    # Already patched?
    if "--show_every_n" in src or 'add_argument("--show"' in src:
        print("[ok] --show already present. No patch needed.")
        return 0

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = target.with_suffix(f".py.bak_showfix_{ts}")
    bak.write_text(src)
    print("[bak]", bak)

    lines = src.splitlines(True)  # keep newlines

    # 1) Insert argparse options after cooldown_s line
    cool_i = find_line_index(lines, 'add_argument("--cooldown_s"')
    if cool_i is None:
        print('ERROR: Could not find line containing add_argument("--cooldown_s"')
        return 1

    indent = lines[cool_i].split("add_argument")[0]  # leading whitespace
    insert_args = [
        indent + 'ap.add_argument("--show", action="store_true", help="Show live preview window with overlay (ROI + bbox)")\n',
        indent + 'ap.add_argument("--show_every_n", type=int, default=2, help="Update preview every N frames (reduce load)")\n',
        indent + 'ap.add_argument("--show_scale", type=float, default=0.75, help="Scale factor for preview window")\n',
        indent + 'ap.add_argument("--show_window_name", default="live_fod", help="Window title for preview")\n',
    ]
    lines[cool_i+1:cool_i+1] = insert_args
    src2 = "".join(lines)

    # 2) Insert preview block before "Periodic debug overlay"
    marker_i = src2.find("# Periodic debug overlay")
    if marker_i == -1:
        print('ERROR: Could not find marker "# Periodic debug overlay"')
        return 1

    marker_line_start = src2.rfind("\n", 0, marker_i) + 1
    marker_line_end = src2.find("\n", marker_i)
    if marker_line_end == -1:
        marker_line_end = len(src2)
    marker_line = src2[marker_line_start:marker_line_end]
    loop_indent = marker_line[:len(marker_line) - len(marker_line.lstrip())]  # leading whitespace of marker line

    pb = []
    pb.append(loop_indent + "# Live preview window (NanoOWL-style): ROI polygon + best bbox + label\n")
    pb.append(loop_indent + "if args.show and (frames % max(1, args.show_every_n) == 0):\n")
    pb.append(loop_indent + "    overlay_show = frame.copy()\n")
    pb.append(loop_indent + "    cv2.polylines(overlay_show, [roi_poly.reshape((-1, 1, 2))], isClosed=True, color=(255, 0, 0), thickness=2)\n")
    pb.append(loop_indent + "    if best is not None:\n")
    pb.append(loop_indent + "        c, name, bbox = best\n")
    pb.append(loop_indent + "        x1, y1, x2, y2 = map(int, map(round, bbox))\n")
    pb.append(loop_indent + "        cv2.rectangle(overlay_show, (x1, y1), (x2, y2), (0, 255, 0), 2)\n")
    pb.append(loop_indent + "        cv2.putText(overlay_show, f\"{name} {c:.2f}\", (x1, max(0, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)\n")
    pb.append(loop_indent + "\n")
    pb.append(loop_indent + "    if args.show_scale and args.show_scale != 1.0:\n")
    pb.append(loop_indent + "        h, w = overlay_show.shape[:2]\n")
    pb.append(loop_indent + "        overlay_show = cv2.resize(overlay_show, (int(w * args.show_scale), int(h * args.show_scale)))\n")
    pb.append(loop_indent + "\n")
    pb.append(loop_indent + "    cv2.imshow(args.show_window_name, overlay_show)\n")
    pb.append(loop_indent + "    k = cv2.waitKey(1) & 0xFF\n")
    pb.append(loop_indent + "    if k in (27, ord('q')):\n")
    pb.append(loop_indent + "        print('[ui] quit requested (ESC/q)')\n")
    pb.append(loop_indent + "        break\n")
    pb.append(loop_indent + "\n")

    preview_block = "".join(pb)
    src3 = src2[:marker_line_start] + preview_block + src2[marker_line_start:]

    # 3) Ensure cv2.destroyAllWindows() exists in finally
    if "cv2.destroyAllWindows()" not in src3:
        fin_i = src3.find("\n    finally:\n")
        if fin_i != -1:
            pipe_i = src3.find("pipeline.set_state(Gst.State.NULL)", fin_i)
            if pipe_i != -1:
                pipe_line_start = src3.rfind("\n", 0, pipe_i) + 1
                destroy = (
                    "        try:\n"
                    "            cv2.destroyAllWindows()\n"
                    "        except Exception:\n"
                    "            pass\n\n"
                )
                src3 = src3[:pipe_line_start] + destroy + src3[pipe_line_start:]

    target.write_text(src3)
    print("[patched]", target)

    out = target.read_text()
    print("[check] has --show:", "--show" in out)
    print("[check] has preview marker:", "Live preview window" in out)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
