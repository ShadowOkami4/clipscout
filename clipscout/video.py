"""Reading recordings through ffmpeg (no Python video codecs needed, works the same on Windows and Linux)."""

from __future__ import annotations

import bisect
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterator

import numpy as np


class FFmpegMissing(RuntimeError):
    pass


def tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise FFmpegMissing(
            f"{name} not found. Install ffmpeg and make sure it's on PATH:\n"
            "  Windows: winget install Gyan.FFmpeg\n"
            "  Linux:   sudo apt install ffmpeg   (or your distro's package)"
        )
    return path


@dataclass
class VideoInfo:
    width: int
    height: int
    fps: float
    duration: float


def probe(path: str) -> VideoInfo:
    out = subprocess.run(
        [tool("ffprobe"), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,avg_frame_rate:format=duration", "-of", "json", path],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe couldn't read {path}: {out.stderr.strip()}")
    data = json.loads(out.stdout)
    stream = data["streams"][0]
    num, _, den = stream.get("avg_frame_rate", "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    try:
        duration = float(data["format"]["duration"])
    except (KeyError, ValueError):
        duration = measure_duration(path)
    return VideoInfo(int(stream["width"]), int(stream["height"]), fps, duration)


@lru_cache(maxsize=16)
def measure_duration(path: str) -> float:
    """Length of a file that doesn't store one (e.g. an OBS recording that wasn't closed properly).

    Reads the whole file once without decoding – about half a minute for an hour of video.
    """
    proc = subprocess.run(
        [tool("ffmpeg"), "-hide_banner", "-nostdin", "-i", path, "-map", "0:v:0", "-c", "copy", "-f", "null", "-"],
        capture_output=True, text=True, check=False,
    )
    times = re.findall(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
    if not times:
        return 0.0
    h, m, sec = times[-1]
    return int(h) * 3600 + int(m) * 60 + float(sec)


@lru_cache(maxsize=16)
def keyframes(path: str) -> tuple[float, ...]:
    """Times of the video keyframes (only keyframes are decoded, so this is quick)."""
    out = subprocess.run(
        [tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey",
         "-show_entries", "frame=pts_time", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=False,
    )
    times = []
    for line in out.stdout.split():
        try:
            times.append(float(line.strip(",")))
        except ValueError:
            pass
    return tuple(sorted(times))


def keyframe_before(path: str, t: float) -> float | None:
    kf = keyframes(path)
    i = bisect.bisect_right(kf, t + 1e-3) - 1
    return kf[i] if i >= 0 else None


def iter_frames(
    path: str,
    fps: float,
    size: tuple[int, int],
    start: float = 0.0,
    end: float | None = None,
    hwaccel: str = "auto",
    threads: int = 4,
) -> Iterator[tuple[float, np.ndarray]]:
    """Yields (seconds, BGR frame) sampled at `fps`, scaled to `size` (w, h).

    ffmpeg does the decoding (with hardware decoding when available) and the scaling, so Python
    only ever sees small sampled frames. `threads` caps ffmpeg's CPU use.
    """
    w, h = size
    cmd = [tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin"]
    if hwaccel and hwaccel != "none":
        cmd += ["-hwaccel", hwaccel]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-threads", str(threads), "-i", path]
    if end is not None:
        cmd += ["-t", f"{max(end - start, 0):.3f}"]
    cmd += ["-an", "-sn", "-vf", f"fps={fps},scale={w}:{h}:flags=area", "-pix_fmt", "bgr24", "-f", "rawvideo", "-"]

    frame_bytes = w * h * 3
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err)
        assert proc.stdout is not None
        i = 0
        try:
            while True:
                buf = proc.stdout.read(frame_bytes)
                if len(buf) < frame_bytes:
                    break
                yield start + i / fps, np.frombuffer(buf, np.uint8).reshape(h, w, 3)
                i += 1
        finally:
            proc.stdout.close()
            code = proc.wait()
        if code not in (0, None) and i == 0:
            err.seek(0)
            raise RuntimeError(f"ffmpeg failed on {path}: {err.read().decode(errors='replace').strip()}")


def grab_frame(path: str, t: float, size: tuple[int, int] | None = None) -> np.ndarray:
    """One frame at `t` seconds (exact, for making templates)."""
    info = probe(path)
    w, h = size or (info.width, info.height)
    vf = f"scale={w}:{h}:flags=area"
    out = subprocess.run(
        [tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", path,
         "-frames:v", "1", "-vf", vf, "-pix_fmt", "bgr24", "-f", "rawvideo", "-"],
        capture_output=True, check=False,
    )
    if out.returncode != 0 or len(out.stdout) < w * h * 3:
        raise RuntimeError(f"Couldn't grab a frame at {t:.2f}s: {out.stderr.decode(errors='replace').strip()}")
    return np.frombuffer(out.stdout[: w * h * 3], np.uint8).reshape(h, w, 3).copy()
