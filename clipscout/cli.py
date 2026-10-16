"""Command line: clipscout scan | review | export | grab | games"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

from . import __version__
from .profile import available_games, load_profile, template_dirs
from .regions import LAYOUTS, parse_layout, region_pixels
from .timeutil import fmt_time, parse_time
from .video import FFmpegMissing, grab_frame, probe


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--threads", type=int, default=4, help="max CPU threads for ffmpeg (default 4 – keeps the PC usable)")


def cmd_scan(a) -> int:
    from .scan import scan

    profile = load_profile(a.game)
    path = scan(
        a.video, profile, parse_layout(a.layout),
        out_dir=Path(a.out) if a.out else None,
        start=parse_time(a.start) if a.start else 0.0,
        end=parse_time(a.end) if a.end else None,
        fps=a.fps, threads=a.threads, hwaccel=a.hwaccel,
        previews=not a.no_previews, debug=a.debug,
    )
    print(f"Project: {path}")
    if a.review:
        from .serve import serve
        serve(path, threads=a.threads)
    else:
        print(f"Next: clipscout review \"{a.video}\"")
    return 0


def cmd_review(a) -> int:
    from .project import resolve_project
    from .serve import serve

    serve(resolve_project(a.project), port=a.port, open_browser=not a.no_browser, threads=a.threads)
    return 0


def cmd_export(a) -> int:
    from .project import export_clips, resolve_project

    files = export_clips(resolve_project(a.project), everything=a.all, accurate=a.accurate, threads=a.threads)
    print(f"Exported {len(files)} clip(s) to {files[0].parent if files else '-'}")
    return 0


def cmd_grab(a) -> int:
    t = parse_time(a.at)
    frame = grab_frame(a.video, t)
    name = Path(a.video).stem
    if a.region:
        profile = load_profile(a.game)
        if a.region not in profile.regions:
            print(f"Unknown region {a.region!r}. {profile.name} has: {', '.join(profile.regions)}", file=sys.stderr)
            return 2
        layout = parse_layout(a.layout)
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = region_pixels(profile.regions[a.region], layout, w, h)
        frame = frame[y0:y1, x0:x1]
        scale = profile.reference_width / (layout[2] * w)
        if abs(scale - 1) > 1e-3:
            frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        out = Path(a.output or f"{name}_{a.region}_{t:.1f}s.png")
    else:
        out = Path(a.output or f"{name}_{t:.1f}s.png")
    ok, buf = cv2.imencode(".png", frame)
    if not ok:
        raise RuntimeError("Couldn't encode the PNG")
    out.parent.mkdir(parents=True, exist_ok=True)
    buf.tofile(str(out))
    print(f"Saved {out} ({frame.shape[1]}×{frame.shape[0]})")
    if a.region:
        print(f"Crop it tight to the HUD element and save it in {template_dirs(a.game)[1]}")
    return 0


def cmd_games(a) -> int:
    for gid in available_games():
        p = load_profile(gid)
        print(f"{p.name} ({gid})")
        for s in p.signals:
            state = f"{len(s.templates)} template(s)" if s.templates else "no templates yet"
            print(f"  {s.event:<12} {s.region:<14} {s.pattern:<20} {state}")
        print(f"  templates: {template_dirs(gid)[0]}")
        print(f"             {template_dirs(gid)[1]}")
    print(f"\nLayouts: {', '.join(LAYOUTS)} – or x,y,w,h as fractions / x,y,w,h@WxH in pixels")
    return 0


def cmd_info(a) -> int:
    info = probe(a.video)
    print(f"{info.width}×{info.height}  {info.fps:.2f} fps  {fmt_time(info.duration)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="clipscout", description="Finds highlights in game recordings by reading the HUD.")
    ap.add_argument("--version", action="version", version=f"clipscout {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan", help="find events in a recording and suggest clips")
    p.add_argument("video")
    p.add_argument("--game", default="valorant", choices=available_games())
    p.add_argument("--layout", default="full", help=f"where the game sits in the recording: {', '.join(LAYOUTS)}, or x,y,w,h")
    p.add_argument("--start", help="start time (e.g. 12:00)")
    p.add_argument("--end", help="end time (e.g. 1:30:00)")
    p.add_argument("--fps", type=float, help="frames checked per second (default from the game profile)")
    p.add_argument("--out", help="output folder (default: <recording>.clipscout next to it)")
    p.add_argument("--hwaccel", default="auto", help="ffmpeg hardware decoding: auto, cuda, d3d11va, vaapi, none")
    p.add_argument("--no-previews", action="store_true", help="don't cut preview clips")
    p.add_argument("--debug", action="store_true", help="also write per-frame match scores to trace.csv")
    p.add_argument("--review", action="store_true", help="open the review page when done")
    _common(p)
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("review", help="open the review page for a scanned recording")
    p.add_argument("project", help="the recording, its .clipscout folder, or project.json")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--no-browser", action="store_true")
    _common(p)
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("export", help="cut the kept clips at full quality")
    p.add_argument("project")
    p.add_argument("--all", action="store_true", help="export every suggested clip, not just kept ones")
    p.add_argument("--accurate", action="store_true", help="frame-exact cuts (re-encodes)")
    _common(p)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("grab", help="save a frame (or one HUD region) as PNG – for making templates")
    p.add_argument("video")
    p.add_argument("--at", required=True, help="time, e.g. 12:31.4")
    p.add_argument("--region", help="only this region of the game profile")
    p.add_argument("--game", default="valorant", choices=available_games())
    p.add_argument("--layout", default="full")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_grab)

    p = sub.add_parser("games", help="list game profiles and their templates")
    p.set_defaults(func=cmd_games)

    p = sub.add_parser("info", help="show a recording's size, frame rate and length")
    p.add_argument("video")
    p.set_defaults(func=cmd_info)
    return ap


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower() not in ("utf-8", "utf8"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (FFmpegMissing, FileNotFoundError, RuntimeError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
