# Environment Fingerprints (Phase 0)

## Jetson Orin Nano (runtime + recording)
- Kernel: Linux 5.15.148-tegra (aarch64)
- OS: Ubuntu 22.04.5 LTS (Jammy)
- NVIDIA/L4T: R36.4.7 (DATE: 2025-09-18)
- GStreamer: 1.20.3
- Camera stack: nvarguscamerasrc OK

## PC / WSL Ubuntu (offline inference + events)
- Kernel: Linux 6.6.87.2-microsoft-standard-WSL2 (x86_64)
- OS: Ubuntu 24.04.3 LTS (Noble)
- Python (system): 3.12.3

### WSL venv (~/projects/.venv_fod) package versions
- ultralytics: 8.3.239
- torch: 2.9.1+cu128
- numpy: 2.2.6
- opencv-python: 4.12.0
- pandas: 2.3.3
