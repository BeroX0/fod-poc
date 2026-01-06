# Jetson Live Detection Environment (jetson_live)

## Purpose
This document records the reproducible Python environment on Jetson used for the Live Detection workstream:
- CUDA-enabled PyTorch (JetPack/NVIDIA wheel)
- torchvision built from source to match torch (compiled ops available, incl. NMS)
- ultralytics (YOLO) running on GPU (device=0)

## Canonical paths
- Repo: /home/fod/projects/fod_poc/repo/sep400-standby-fod-poc
- Venv: /home/fod/projects/fod_poc/venv/jetson_live
- Models: /home/fod/projects/fod_poc/models (e.g. yolov8n.pt)
- Runtime outputs (do NOT commit): /data/live_runs/{logs,events,videos}

## Mandatory run guard (prevents ~/.local contamination)
Always run:
```bash
source /home/fod/projects/fod_poc/venv/jetson_live/bin/activate
export PYTHONNOUSERSITE=1
“Do not break it again” rules
Inside jetson_live:

NEVER: pip install torch or pip install torchvision unless intentionally rebuilding the full stack.

When installing other packages: prefer pip install --no-deps <pkg> to avoid dependency resolution replacing torch/torchvision.

When validating torchvision after a source build: do NOT test imports while inside the torchvision source directory. Always cd ~ first.

Torch wheel (concept)
Torch must be a JetPack/NVIDIA CUDA-enabled build compatible with the installed JetPack/L4T stack.
The exact installed versions are recorded in:

docs/jetson_live_requirements.freeze.txt

torchvision build method (source build)
Working pattern:

Checkout torchvision matching the torch ABI

Force CUDA build and target Orin architecture (8.7)

Install without build isolation and without pulling dependencies

Representative environment variables:

bash
Kopiera kod
export FORCE_CUDA=1
export CUDA_HOME=/usr/local/cuda
export TORCH_CUDA_ARCH_LIST="8.7"
export MAX_JOBS=2
Representative install command from within the torchvision source directory:

bash
Kopiera kod
pip install --no-deps --no-build-isolation -v .
Validation commands (expected GREEN)
bash
Kopiera kod
python3 -c "import torch; print(torch.__version__, torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
python3 -c "import torchvision; import torchvision.ops; print(torchvision.__version__); print(hasattr(torchvision.ops,'nms'))"
python3 -c "from ultralytics import YOLO; print('ultralytics ok')"
