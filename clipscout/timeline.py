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


def build_clips(events: list[Event], profile: Profile, duration: float) -> list[Clip]:
    pre = profile.clips.get("pre", 6.0)
    post = profile.clips.get("post", 3.0)
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
    for i, g in enumerate(groups, 1):
        start = max(g[0].t - pre, 0.0)
        end = min(g[-1].t + post, duration) if duration else g[-1].t + post
        inside = [e for e in events if start <= e.t <= end]     # context events (deaths, round ends) too
        counts = Counter(e.kind for e in inside)
        score = sum(weights.get(e.kind, 0) for e in inside)
        score += sum(bonus * max(counts[k] - 1, 0) for k, bonus in multi.items())
        kinds = sorted(counts, key=lambda k: (order.index(k) if k in order else len(order), k))
        title = ", ".join(profile.label(k, counts[k]) for k in kinds)
        clips.append(Clip(f"clip-{i:03d}", start, end, score, title, inside))
    return clips
