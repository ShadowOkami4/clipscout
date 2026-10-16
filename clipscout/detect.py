"""Turns sampled frames into events by template-matching HUD regions."""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .profile import Profile, Signal, preprocess
from .regions import Rect, game_width_pixels, region_pixels


@dataclass
class Event:
    t: float
    kind: str
    score: float
    detail: str = ""

    def to_dict(self) -> dict:
        return {"t": round(self.t, 3), "kind": self.kind, "score": round(self.score, 3), "detail": self.detail}


@dataclass
class _State:
    above: int = 0
    first_t: float = 0.0
    best: float = 0.0
    best_name: str = ""
    active: bool = False
    last_fire: float = -1e9


STATE_GRACE = 1.0  # a state counts if it was on within this many seconds of an event


@dataclass
class Detector:
    profile: Profile
    layout: Rect
    trace: list[dict] | None = None   # per-frame scores when debugging
    events: list[Event] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._state = {id(s): _State() for s in self.profile.ready_signals}
        self._last_on: dict[str, float] = {}   # state name -> last time it was on
        # States first, so events on the same frame already see them.
        self._order = sorted(self.profile.ready_signals, key=lambda s: not s.state)

    def _region(self, frame: np.ndarray, name: str, scale: float) -> np.ndarray:
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = region_pixels(self.profile.regions[name], self.layout, w, h)
        crop = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        if abs(scale - 1) > 1e-3 and crop.size:
            crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        return crop

    @staticmethod
    def _score(region: np.ndarray, sig: Signal) -> tuple[float, str]:
        best, name = 0.0, ""
        for tpl in sig.templates:
            for s in sig.scales:
                img = tpl.image if s == 1 else cv2.resize(tpl.image, None, fx=s, fy=s)
                if img.shape[0] > region.shape[0] or img.shape[1] > region.shape[1] or img.size == 0:
                    continue
                if not img.any():
                    continue
                res = cv2.matchTemplate(region, img, cv2.TM_CCOEFF_NORMED)
                v = float(np.nanmax(res)) if res.size else 0.0
                if v > best:
                    best, name = v, tpl.name
        return best, name

    def feed(self, t: float, frame: np.ndarray) -> list[Event]:
        """Processes one sampled frame; returns the events that start on it."""
        # Scale so the game area matches the width the templates were captured at.
        scale = self.profile.reference_width / game_width_pixels(self.layout, frame.shape[1])
        cache: dict[tuple[str, str], np.ndarray] = {}
        fired: list[Event] = []
        row = {"t": round(t, 3)} if self.trace is not None else None
        for sig in self._order:
            key = (sig.region, sig.match)
            if key not in cache:
                cache[key] = preprocess(self._region(frame, sig.region, scale), sig.match)
            score, name = self._score(cache[key], sig)
            if row is not None:
                row[sig.event] = round(score, 3)
            st = self._state[id(sig)]
            if sig.state:
                if score >= sig.threshold:
                    st.above += 1
                    st.active = st.active or st.above >= sig.min_frames
                elif score < sig.threshold * sig.rearm:
                    st.above, st.active = 0, False
                if st.active:
                    self._last_on[sig.event] = t
                continue
            if score >= sig.threshold:
                if st.above == 0:
                    st.first_t, st.best = t, 0.0
                st.above += 1
                if score > st.best:
                    st.best, st.best_name = score, name
                if not st.active and st.above >= sig.min_frames and st.first_t - st.last_fire >= sig.cooldown:
                    st.active, st.last_fire = True, st.first_t
                    kind = sig.event
                    for state, other in sig.when.items():
                        if st.first_t - self._last_on.get(state, -1e9) <= STATE_GRACE:
                            kind = other
                    fired.append(Event(st.first_t, kind, st.best, st.best_name))
            elif score < sig.threshold * sig.rearm:
                st.above, st.active = 0, False
        if row is not None:
            self.trace.append(row)
        self.events.extend(fired)
        return fired
