"""Cutting clips out of the recording with ffmpeg."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .video import keyframe_before, tool

# Stream copy starts on the keyframe before `start`; allow at most this much extra lead-in.
MAX_COPY_LEAD = 1.5


def cut(video: str, start: float, end: float, out: Path, accurate: bool = False, threads: int = 4,
        preview: bool = False) -> str:
    """Writes [start, end] of `video` to `out` (.mp4), keeping all audio tracks. Returns the mode used.

    - copy:     streams copied, no quality loss – used when a keyframe sits right before `start`
    - encode:   frame-exact re-encode (`accurate`, or when keyframes are too far apart to copy)
    - preview:  small, fast re-encode for the review page
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    base = [tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-ss", f"{start:.3f}", "-i", video,
            "-t", f"{max(end - start, 0.1):.3f}", "-map", "0:v:0", "-map", "0:a?", "-threads", str(threads)]
    copy = ["-c", "copy", "-avoid_negative_ts", "make_zero"]
    encode = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
    small = ["-vf", "scale=-2:'min(720,ih)'", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k"]
    tail = ["-movflags", "+faststart", str(out)]

    if preview:
        mode = "preview"
    elif accurate:
        mode = "encode"
    else:
        kf = keyframe_before(video, start)
        mode = "copy" if kf is not None and start - kf <= MAX_COPY_LEAD else "encode"
    args = {"copy": copy, "encode": encode, "preview": small}[mode]
    result = subprocess.run(base + args + tail, capture_output=True, text=True, check=False)
    if result.returncode != 0 and mode == "copy":
        # Some codecs can't be copied into MP4 – fall back to re-encoding.
        mode = "encode"
        result = subprocess.run(base + encode + tail, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg couldn't cut {out.name}: {result.stderr.strip()}")
    return mode


def sparse_keyframes(video: str, segments: list[tuple[float, float]]) -> bool:
    """True when some segment can't be stream-copied because its keyframe is too far back."""
    for start, _ in segments:
        kf = keyframe_before(video, start)
        if kf is None or start - kf > MAX_COPY_LEAD:
            return True
    return False


def cut_many(video: str, segments: list[tuple[float, float, Path]], preview: bool = False, threads: int = 4,
             batch: int = 24, log=lambda *a, **k: None) -> None:
    """Cuts many clips by re-encoding in ONE pass over the file instead of seeking for each.

    Recordings with keyframes minutes apart make every seek decode minutes of video first; one pass
    decodes the file once and writes each clip as it goes by. Batches keep the ffmpeg command short.
    """
    segments = sorted(segments, key=lambda s: s[0])
    if preview:
        codec = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k"]
    else:
        codec = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
    for i in range(0, len(segments), batch):
        group = segments[i:i + batch]
        first = group[0][0]
        kf = keyframe_before(video, first)
        seek = kf if kf is not None else 0.0   # start decoding at the keyframe before the first clip
        cmd = [tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-threads", str(threads),
               "-ss", f"{seek:.3f}", "-i", video]
        for start, end, out in group:
            out.parent.mkdir(parents=True, exist_ok=True)
            cmd += ["-map", "0:v:0", "-map", "0:a?", "-ss", f"{start - seek:.3f}", "-t", f"{max(end - start, 0.1):.3f}",
                    *codec, "-threads", str(threads), "-movflags", "+faststart", str(out)]
        log(f"  cutting clips {i + 1}–{i + len(group)} of {len(segments)} in one pass")
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg couldn't cut clips: {result.stderr.strip()[-800:]}")
