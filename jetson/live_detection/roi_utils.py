from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Sequence, Tuple, Union

Point = Tuple[float, float]
Polygon = List[Point]


@dataclass(frozen=True)
class Roi:
    roi_id: str
    polygon: Polygon  # FULL-FRAME pixel coords (1920x1080 contract)


def _extract_polygon(obj: Any) -> Polygon:
    """
    Flexible ROI JSON reader. Supported patterns:
      - {"points": [[x,y], ...]}
      - {"polygon": [[x,y], ...]}
      - {"roi": {"points": ...}} or {"roi": {"polygon": ...}}
    """
    if isinstance(obj, dict):
        for k in ("points", "polygon"):
            if k in obj and isinstance(obj[k], list):
                pts = obj[k]
                return [(float(p[0]), float(p[1])) for p in pts]
        if "roi" in obj:
            return _extract_polygon(obj["roi"])
    raise ValueError("Could not extract ROI polygon from JSON structure.")


def load_roi(rois_dir: Union[str, Path], roi_id: str) -> Roi:
    """
    Load ROI by roi_id from the flattened ROI directory.
    Expects <roi_id>.json.
    """
    rois_dir = Path(rois_dir).expanduser().resolve()
    path = rois_dir / f"{roi_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"ROI file not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    polygon = _extract_polygon(data)

    if len(polygon) < 3:
        raise ValueError(f"ROI polygon must have >= 3 points. Got {len(polygon)} for roi_id={roi_id}")

    return Roi(roi_id=roi_id, polygon=polygon)


def point_in_polygon(x: float, y: float, polygon: Sequence[Point]) -> bool:
    """
    Ray casting point-in-polygon test.
    """
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        intersects = ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1)
        if intersects:
            inside = not inside
    return inside
