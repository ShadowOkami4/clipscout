"""Scanning a recording: sample frames, detect events, build clips, save a project file."""

from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .detect import Detector
from .export import cut, cut_many, sparse_keyframes
from .profile import Profile
from .regions import Rect
from .timeline import build_clips
from .timeutil import fmt_time
from .video import iter_frames, keyframes, probe


def project_dir(video: str | Path) -> Path:
    video = Path(video)
    return video.with_name(video.stem + ".clipscout")


def analysis_size(width: int, height: int, layout: Rect, reference_width: int) -> tuple[int, int]:
    """Frame size where the game area is about `reference_width` wide (never upscaled)."""
    target = min(width, reference_width / layout[2])
    w = int(round(target / 2)) * 2
    h = int(round(height * w / width / 2)) * 2
    return w, h


def scan(
    video: str,
    profile: Profile,
    layout: Rect,
    out_dir: Path | None = None,
    start: float = 0.0,
    end: float | None = None,
    fps: float | None = None,
    threads: int = 4,
    hwaccel: str = "auto",
    previews: bool = True,
    debug: bool = False,
    quiet: bool = False,
) -> Path:
    info = probe(video)
    out_dir = out_dir or project_dir(video)
    out_dir.mkdir(parents=True, exist_ok=True)
    fps = fps or profile.fps
    size = analysis_size(info.width, info.height, layout, profile.reference_width)
    stop = min(end, info.duration) if end else info.duration
    log = (lambda *a, **k: None) if quiet else (lambda *a, **k: print(*a, file=sys.stderr, **k))

    missing = [s.event for s in profile.signals if not s.templates]
    if missing:
        log(f"Note: no templates yet for {', '.join(missing)} – those events are skipped (see `clipscout games`).")
    if not profile.ready_signals:
        raise RuntimeError(f"The {profile.name} profile has no templates yet, so there's nothing to look for.")

    kf = keyframes(video)
    if len(kf) > 2:
        gap = sorted(b - a for a, b in zip(kf, kf[1:]))[len(kf) // 2]
        if gap > 10:
            log(f"Note: keyframes are {gap:.0f} s apart, so clips can't be copied losslessly and get re-encoded (slower).\n"
                "      In OBS set Settings → Output → Recording → Keyframe Interval to 2 s for future recordings.")
    log(f"Scanning {Path(video).name} ({info.width}×{info.height}, {fmt_time(info.duration)}) "
        f"at {fps:g} fps, analysing at {size[0]}×{size[1]}")
    det = Detector(profile, layout, trace=[] if debug else None)
    began, last_print = time.monotonic(), 0.0
    for t, frame in iter_frames(video, fps, size, start=start, end=end, hwaccel=hwaccel, threads=threads):
        for e in det.feed(t, frame):
            log(f"  {fmt_time(e.t):>9}  {e.kind:<12} {e.score:.2f}  {e.detail}")
        now = time.monotonic()
        if not quiet and now - last_print > 2:
            done = (t - start) / max(stop - start, 1e-6)
            speed = (t - start) / max(now - began, 1e-6)
            print(f"\r  {done * 100:5.1f}%  {fmt_time(t)} / {fmt_time(stop)}  ({speed:.0f}× realtime)", end="", file=sys.stderr)
            last_print = now
    if not quiet:
        print("\r" + " " * 60 + "\r", end="", file=sys.stderr)

    clips = build_clips(det.events, profile, info.duration)
    log(f"Found {len(det.events)} events → {len(clips)} clips in {time.monotonic() - began:.0f} s")

    if previews and clips:
        began_cut = time.monotonic()
        jobs = [(c.start, c.end, out_dir / "clips" / f"{c.id}.mp4") for c in clips]
        if sparse_keyframes(video, [(a, b) for a, b, _ in jobs]):
            cut_many(video, jobs, preview=True, threads=threads, log=log)
        else:
            for i, (a, b, out) in enumerate(jobs, 1):
                log(f"\r  cutting previews {i}/{len(jobs)}", end="")
                cut(video, a, b, out, threads=threads, preview=True)
            log("")
        log(f"Previews ready in {time.monotonic() - began_cut:.0f} s")

    project = {
        "clipscout": __version__,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "video": str(Path(video).resolve()),
        "duration": info.duration,
        "size": [info.width, info.height],
        "game": profile.id,
        "layout": list(layout),
        "range": [start, stop],
        "events": [e.to_dict() for e in det.events],
        "clips": [c.to_dict() for c in clips],
    }
    path = out_dir / "project.json"
    path.write_text(json.dumps(project, indent=2), encoding="utf-8")
    if debug and det.trace:
        with (out_dir / "trace.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(det.trace[0]))
            writer.writeheader()
            writer.writerows(det.trace)
        log(f"Per-frame scores: {out_dir / 'trace.csv'}")
    return path
