"""Where the game sits in the recording, and HUD regions relative to the game.

Regions are fractions (x, y, w, h) of the *game area*, so the same profile works at 1080p,
1440p, in a full-screen recording or with the game shrunk into a stream layout.
"""

from __future__ import annotations

import re

Rect = tuple[float, float, float, float]

# Named layouts: the game area as a fraction of the recording frame.
LAYOUTS: dict[str, Rect] = {
    "full": (0.0, 0.0, 1.0, 1.0),
    # Okami's "Gaming" stream scene: game window at 80,18 sized 1760×990 on a 1920×1080 canvas.
    "okami": (80 / 1920, 18 / 1080, 1760 / 1920, 990 / 1080),
}


def parse_layout(value: str | None) -> Rect:
    """'full', a named layout, or 'x,y,w,h' as fractions (0.04,0.02,0.92,0.92) or pixels@WxH."""
    if not value:
        return LAYOUTS["full"]
    if value in LAYOUTS:
        return LAYOUTS[value]
    m = re.fullmatch(r"\s*(\d+),(\d+),(\d+),(\d+)@(\d+)x(\d+)\s*", value)
    if m:
        x, y, w, h, fw, fh = map(int, m.groups())
        return (x / fw, y / fh, w / fw, h / fh)
    parts = [float(p) for p in value.split(",")]
    if len(parts) != 4 or not all(0 <= p <= 1 for p in parts):
        raise ValueError(f"Unknown layout {value!r}. Use {', '.join(LAYOUTS)}, x,y,w,h fractions, or x,y,w,h@WxH pixels.")
    return tuple(parts)  # type: ignore[return-value]


def region_pixels(region: Rect, layout: Rect, frame_w: int, frame_h: int) -> tuple[int, int, int, int]:
    """Pixel box (x0, y0, x1, y1) of a game-relative region inside a frame."""
    gx, gy, gw, gh = layout
    rx, ry, rw, rh = region
    x0 = (gx + rx * gw) * frame_w
    y0 = (gy + ry * gh) * frame_h
    x1 = x0 + rw * gw * frame_w
    y1 = y0 + rh * gh * frame_h
    clamp = lambda v, hi: int(round(min(max(v, 0), hi)))  # noqa: E731
    return clamp(x0, frame_w), clamp(y0, frame_h), clamp(x1, frame_w), clamp(y1, frame_h)


def game_width_pixels(layout: Rect, frame_w: int) -> float:
    return layout[2] * frame_w
