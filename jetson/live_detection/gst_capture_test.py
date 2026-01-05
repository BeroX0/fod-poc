#!/usr/bin/env python3
import time
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst

Gst.init(None)

PIPE = (
    "nvarguscamerasrc sensor-mode=2 ! "
    "video/x-raw(memory:NVMM),width=1920,height=1080,framerate=30/1,format=NV12 ! "
    "nvvidconv ! video/x-raw,format=BGRx,width=1920,height=1080 ! "
    "appsink name=sink emit-signals=false sync=false max-buffers=1 drop=true"
)

def main():
    pipeline = Gst.parse_launch(PIPE)
    sink = pipeline.get_by_name("sink")
    if sink is None:
        raise RuntimeError("appsink not found")

    bus = pipeline.get_bus()
    ret = pipeline.set_state(Gst.State.PLAYING)
    if ret == Gst.StateChangeReturn.FAILURE:
        raise RuntimeError("Failed to set pipeline to PLAYING")

    print("[capture] Pipeline:", PIPE)

    t0 = time.monotonic()
    frames = 0

    try:
        while time.monotonic() - t0 < 10.0:
            # Check for async errors/EOS
            msg = bus.pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.EOS)
            if msg:
                if msg.type == Gst.MessageType.ERROR:
                    err, dbg = msg.parse_error()
                    raise RuntimeError(f"GstError: {err} dbg={dbg}")
                if msg.type == Gst.MessageType.EOS:
                    print("[capture] EOS")
                    break

            # Use appsink action signal (works even when try_pull_sample method is missing)
            sample = sink.emit("try-pull-sample", 200 * Gst.MSECOND)
            if sample is None:
                continue

            caps = sample.get_caps()
            s = caps.get_structure(0)
            frames += 1
            if frames == 1 or frames % 30 == 0:
                print(f"[capture] frames={frames} size={s.get_value('width')}x{s.get_value('height')} format={s.get_value('format')}")

        elapsed = time.monotonic() - t0
        print(f"[capture] Done. frames={frames} elapsed_s={elapsed:.3f} avg_fps={frames/elapsed:.2f}")

    finally:
        pipeline.set_state(Gst.State.NULL)

if __name__ == "__main__":
    main()
