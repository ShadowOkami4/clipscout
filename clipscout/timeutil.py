"""Parsing and printing times like 1:02:03.5, 12:31 or 75."""

from __future__ import annotations


def parse_time(value: str | float | int) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    parts = value.strip().split(":")
    if not 1 <= len(parts) <= 3:
        raise ValueError(f"Can't read time {value!r} – use seconds, mm:ss or hh:mm:ss")
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + float(p)
    return seconds


def fmt_time(seconds: float) -> str:
    seconds = max(seconds, 0)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{int(h)}:{int(m):02d}:{s:04.1f}" if h else f"{int(m)}:{s:04.1f}"
