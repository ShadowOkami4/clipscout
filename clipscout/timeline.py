"""Groups events into clips: a few seconds before the first event, a few after the last."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .detect import Event
from .profile import Profile


@dataclass
class Clip:
    id: str
    start: float
    end: float
    score: float
    title: str
    events: list[Event] = field(default_factory=list)
    keep: bool | None = None   # set in the review page

    def to_dict(self) -> dict:
        return {
            "id": self.id, "start": round(self.start, 3), "end": round(self.end, 3), "score": round(self.score, 2),
            "title": self.title, "events": [e.to_dict() for e in self.events], "keep": self.keep,
        }


def build_clips(events: list[Event], profile: Profile, duration: float,
                pre: float | None = None, post: float | None = None) -> list[Clip]:
    pre = profile.clips.get("pre", 6.0) if pre is None else pre
    post = profile.clips.get("post", 3.0) if post is None else post
    min_len = profile.clips.get("min_length", 0.0)
    max_len = profile.clips.get("max_length", 0.0)    # 0 = no limit
    gap = profile.clips.get("merge_gap", 6.0)
    multi = profile.clips.get("multi_bonus", {})          # e.g. {"kill": 0.5}: extra per additional kill
    order = profile.clips.get("title_order", [])
    weights = profile.weights
    events = sorted(events, key=lambda e: e.t)
    worthy = [e for e in events if weights.get(e.kind, 0) > 0]

    groups: list[list[Event]] = []
    for e in worthy:
        if groups and e.t - groups[-1][-1].t <= gap:
            groups[-1].append(e)
        else:
            groups.append([e])

    clips = []
    prev_end = 0.0
    for i, g in enumerate(groups, 1):
        start = g[0].t - pre
        end = g[-1].t + post
        if min_len and end - start < min_len:
            start = end - min_len                       # extra time goes before: the build-up
        if max_len and end - start > max_len:
            # Too long: trim the lead-in first, but keep 2 s before the first event.
            start = min(max(start, end - max_len), g[0].t - 2)
        # Never repeat the end of the previous clip (keeps at least 2 s before this clip's first event).
        start = max(start, min(prev_end, g[0].t - 2), 0.0)
        end = min(end, duration) if duration else end
        prev_end = end
        inside = [e for e in events if start <= e.t <= end]     # context events (deaths, round ends) too
        counts = Counter(e.kind for e in inside)
        score = sum(weights.get(e.kind, 0) for e in inside)
        score += sum(bonus * max(counts[k] - 1, 0) for k, bonus in multi.items())
        kinds = sorted(counts, key=lambda k: (order.index(k) if k in order else len(order), k))
        title = ", ".join(profile.label(k, counts[k]) for k in kinds)
        clips.append(Clip(f"clip-{i:03d}", start, end, score, title, inside))
    return clips
