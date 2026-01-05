from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

BBox = Tuple[float, float, float, float]  # x1,y1,x2,y2


def clamp_bbox_xyxy(b: BBox, w: int, h: int) -> BBox:
    x1, y1, x2, y2 = b
    x1 = max(0.0, min(float(w - 1), x1))
    y1 = max(0.0, min(float(h - 1), y1))
    x2 = max(0.0, min(float(w - 1), x2))
    y2 = max(0.0, min(float(h - 1), y2))
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return (x1, y1, x2, y2)


def bbox_center(b: BBox) -> Tuple[float, float]:
    x1, y1, x2, y2 = b
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def bbox_area(b: BBox) -> float:
    x1, y1, x2, y2 = b
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


@dataclass(frozen=True)
class LetterboxParams:
    src_w: int
    src_h: int
    dst_w: int
    dst_h: int
    scale: float
    pad_x: float
    pad_y: float


def compute_letterbox_params(src_w: int, src_h: int, dst_w: int, dst_h: int) -> LetterboxParams:
    scale = min(dst_w / src_w, dst_h / src_h)
    new_w = src_w * scale
    new_h = src_h * scale
    pad_x = (dst_w - new_w) / 2.0
    pad_y = (dst_h - new_h) / 2.0
    return LetterboxParams(src_w, src_h, dst_w, dst_h, scale, pad_x, pad_y)


def reverse_letterbox_bbox_xyxy(b: BBox, params: LetterboxParams) -> BBox:
    """
    Convert bbox from letterboxed dst-space back to src-space.
    """
    x1, y1, x2, y2 = b
    x1 = (x1 - params.pad_x) / (params.scale + 1e-12)
    x2 = (x2 - params.pad_x) / (params.scale + 1e-12)
    y1 = (y1 - params.pad_y) / (params.scale + 1e-12)
    y2 = (y2 - params.pad_y) / (params.scale + 1e-12)
    return (x1, y1, x2, y2)
