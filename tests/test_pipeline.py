"""End to end: render a fake recording with a HUD icon at known times, scan it, export the clips."""

import json
import shutil
import subprocess

import cv2
import numpy as np
import pytest

from clipscout import profile as profile_mod
from clipscout.project import export_clips, load
from clipscout.regions import LAYOUTS, region_pixels
from clipscout.scan import scan

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")

W, H, FPS, SECONDS = 1280, 720, 30, 10
SHOW = [(2.0, 2.6), (6.0, 6.6)]  # when the icon is on screen
REGION = (0.40, 0.66, 0.20, 0.17)


def icon(size: int) -> np.ndarray:
    """A skull-ish shape with sharp edges, drawn at `size` px wide."""
    img = np.zeros((size, size), np.uint8)
    s = size / 100
    cv2.circle(img, (int(50 * s), int(42 * s)), int(30 * s), 255, -1)
    cv2.rectangle(img, (int(32 * s), int(60 * s)), (int(68 * s), int(86 * s)), 255, -1)
    cv2.circle(img, (int(38 * s), int(42 * s)), int(9 * s), 0, -1)
    cv2.circle(img, (int(62 * s), int(42 * s)), int(9 * s), 0, -1)
    for x in (40, 50, 60):
        cv2.line(img, (int(x * s), int(70 * s)), (int(x * s), int(86 * s)), 0, max(1, int(3 * s)))
    return img


def make_video(path, layout, gop=FPS):
    rng = np.random.default_rng(1)
    base = np.zeros((H, W, 3), np.uint8)
    base[:] = np.linspace(20, 70, W, dtype=np.uint8)[None, :, None]
    gx0, gy0, gx1, gy1 = region_pixels((0, 0, 1, 1), layout, W, H)
    x0, y0, x1, y1 = region_pixels(REGION, layout, W, H)
    size = int(round(110 * (gx1 - gx0) / 1920))  # 110 px at a 1920-wide game area
    tile = cv2.cvtColor(icon(size), cv2.COLOR_GRAY2BGR)
    cx, cy = (x0 + x1) // 2 - size // 2, (y0 + y1) // 2 - size // 2
    proc = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0", str(path)],
        stdin=subprocess.PIPE,
    )
    for f in range(FPS * SECONDS):
        t = f / FPS
        frame = base.copy()
        frame[gy0:gy1, gx0:gx1] //= 2   # the "game" area is darker than the stream layout around it
        noise = rng.integers(0, 25, (60, 60, 3), dtype=np.uint8)
        frame[100:160, 100 + f % 200:160 + f % 200] = noise  # something moving
        if any(a <= t < b for a, b in SHOW):
            frame[cy:cy + size, cx:cx + size] = np.maximum(frame[cy:cy + size, cx:cx + size], tile)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    assert proc.wait() == 0


@pytest.fixture
def game(tmp_path, monkeypatch):
    games = tmp_path / "games"
    (games / "test" / "templates").mkdir(parents=True)
    cv2.imwrite(str(games / "test" / "templates" / "kill-1.png"), icon(110))
    (games / "test" / "profile.json").write_text(json.dumps({
        "id": "test", "name": "Test", "reference_width": 1920, "fps": 5,
        "regions": {"kill_banner": list(REGION)},
        "signals": [{"event": "kill", "region": "kill_banner", "templates": "kill-*.png", "threshold": 0.6, "match": "edges"}],
        "clips": {"pre": 1, "post": 1, "merge_gap": 2},
        "weights": {"kill": 1}, "labels": {"kill": ["kill", "kills"]},
    }))
    monkeypatch.setattr(profile_mod, "GAMES_DIR", games)
    monkeypatch.setenv("APPDATA", str(tmp_path / "user"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "user"))
    return profile_mod.load_profile("test")


@pytest.mark.parametrize("layout_name", ["full", "okami"])
def test_scan_finds_the_icon_and_exports(tmp_path, game, layout_name):
    layout = LAYOUTS[layout_name]
    video = tmp_path / f"rec-{layout_name}.mp4"
    make_video(video, layout)

    project_path = scan(str(video), game, layout, quiet=True, threads=2)
    data = load(project_path)
    times = [e["t"] for e in data["events"]]
    assert len(times) == 2, data["events"]
    for found, (shown, _) in zip(times, SHOW):
        assert abs(found - shown) <= 0.25
    assert [c["title"] for c in data["clips"]] == ["kill", "kill"]
    assert all((project_path.parent / "clips" / f"{c['id']}.mp4").stat().st_size > 0 for c in data["clips"])

    files = export_clips(project_path, everything=True, threads=2, log=lambda *a: None)
    assert len(files) == 2 and all(f.stat().st_size > 0 for f in files)


def test_sparse_keyframes_use_one_pass(tmp_path, game):
    """Keyframes far apart (like some OBS AV1 recordings): clips are re-encoded in one pass and still line up."""
    from clipscout.video import probe

    video = tmp_path / "sparse.mp4"
    make_video(video, LAYOUTS["full"], gop=FPS * SECONDS)   # a single keyframe at 0 s
    project_path = scan(str(video), game, LAYOUTS["full"], quiet=True, threads=2)
    data = load(project_path)
    assert len(data["clips"]) == 2
    files = export_clips(project_path, everything=True, threads=2, log=lambda *a: None)
    for f, c in zip(files, data["clips"]):
        assert abs(probe(str(f)).duration - (c["end"] - c["start"])) < 0.25
