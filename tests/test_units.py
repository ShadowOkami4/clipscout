from pathlib import Path

import pytest

from clipscout.detect import Event
from clipscout.profile import Profile
from clipscout.regions import LAYOUTS, parse_layout, region_pixels
from clipscout.timeline import build_clips
from clipscout.timeutil import fmt_time, parse_time


def test_parse_time():
    assert parse_time("75") == 75
    assert parse_time("12:31.5") == 751.5
    assert parse_time("1:00:02") == 3602
    assert fmt_time(751.5) == "12:31.5"
    assert fmt_time(3602) == "1:00:02.0"
    with pytest.raises(ValueError):
        parse_time("1:2:3:4")


def test_layouts():
    assert parse_layout("okami") == LAYOUTS["okami"]
    assert parse_layout("80,18,1760,990@1920x1080") == pytest.approx(LAYOUTS["okami"])
    assert parse_layout("0.1,0.1,0.8,0.8") == (0.1, 0.1, 0.8, 0.8)
    with pytest.raises(ValueError):
        parse_layout("nope")


def test_region_pixels_follow_the_layout():
    # Whole game, full frame
    assert region_pixels((0.5, 0.5, 0.5, 0.5), LAYOUTS["full"], 1920, 1080) == (960, 540, 1920, 1080)
    # Okami layout at 1440p: game area starts at 106.7, 24 and is 2346.7 wide
    x0, y0, x1, y1 = region_pixels((0, 0, 1, 1), LAYOUTS["okami"], 2560, 1440)
    assert (x0, y0) == (107, 24) and (x1, y1) == (2453, 1344)


def _profile(**clips) -> Profile:
    return Profile(
        id="t", name="Test", reference_width=1920, fps=5, regions={}, signals=[],
        clips={"pre": 5, "post": 2, "merge_gap": 6, **clips},
        weights={"kill": 1, "round_won": 0.5, "death": 0},
        labels={"kill": ["kill", "kills"], "round_won": ["round won", "rounds won"]},
        path=Path("."),
    )


def test_clips_merge_close_events_and_skip_context_only():
    events = [Event(10, "kill", .9), Event(13, "kill", .9), Event(15, "round_won", .8),
              Event(40, "death", .9),  # weight 0 → no clip on its own
              Event(80, "kill", .9)]
    clips = build_clips(events, _profile(multi_bonus={"kill": 0.5}, title_order=["kill"]), duration=100)
    assert len(clips) == 2
    first = clips[0]
    assert (first.start, first.end) == (5, 17)
    assert first.title == "2 kills, round won"
    assert first.score == pytest.approx(1 + 1 + .5 + .5)
    assert clips[1].title == "kill"


def test_clips_clamp_to_the_recording():
    clips = build_clips([Event(1, "kill", 1), Event(99, "kill", 1)], _profile(), duration=100)
    assert clips[0].start == 0 and clips[1].end == 100
