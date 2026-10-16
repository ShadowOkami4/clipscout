"""Game profiles: HUD regions, the signals to look for, and how events become clips.

A profile lives in clipscout/games/<id>/profile.json with its templates in templates/.
Templates you capture yourself (`clipscout grab --save`) go to your user folder and are used too:
  Windows: %APPDATA%\\clipscout\\games\\<id>\\templates
  Linux:   ~/.config/clipscout/games/<id>/templates
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

GAMES_DIR = Path(__file__).parent / "games"


def user_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "clipscout"


@dataclass
class Template:
    name: str
    image: np.ndarray  # preprocessed (grey or edges)


@dataclass
class Signal:
    event: str
    region: str
    pattern: str
    threshold: float = 0.7
    min_frames: int = 1
    rearm: float = 0.85       # score must drop below threshold * rearm before it can fire again
    cooldown: float = 0.5     # seconds between two events of this signal
    match: str = "gray"       # "gray" or "edges" (edges ignore colour and brightness)
    scales: list[float] = field(default_factory=lambda: [1.0])
    templates: list[Template] = field(default_factory=list)


@dataclass
class Profile:
    id: str
    name: str
    reference_width: int
    fps: float
    regions: dict[str, tuple[float, float, float, float]]
    signals: list[Signal]
    clips: dict
    weights: dict[str, float]
    labels: dict[str, list[str]]
    path: Path

    def label(self, kind: str, count: int = 1) -> str:
        one, many = (self.labels.get(kind) or [kind.replace("_", " ")] * 2)[:2]
        return f"{count} {many}" if count > 1 else one

    @property
    def ready_signals(self) -> list[Signal]:
        return [s for s in self.signals if s.templates]


def preprocess(gray: np.ndarray, mode: str) -> np.ndarray:
    if mode == "edges":
        # Softened edges: thin Canny lines alone break on a 1 px shift from scaling or compression.
        return cv2.GaussianBlur(cv2.Canny(gray, 60, 160), (5, 5), 1.2)
    return gray


def available_games() -> list[str]:
    return sorted(p.name for p in GAMES_DIR.iterdir() if (p / "profile.json").exists())


def template_dirs(game_id: str) -> list[Path]:
    return [GAMES_DIR / game_id / "templates", user_dir() / "games" / game_id / "templates"]


def load_profile(game_id: str) -> Profile:
    path = GAMES_DIR / game_id / "profile.json"
    if not path.exists():
        raise ValueError(f"No profile for {game_id!r}. Available: {', '.join(available_games())}")
    data = json.loads(path.read_text(encoding="utf-8"))
    signals = []
    for raw in data["signals"]:
        sig = Signal(
            event=raw["event"], region=raw["region"], pattern=raw["templates"],
            threshold=raw.get("threshold", 0.7), min_frames=raw.get("min_frames", 1),
            rearm=raw.get("rearm", 0.85), cooldown=raw.get("cooldown", 0.5),
            match=raw.get("match", "gray"), scales=raw.get("scales", [1.0]),
        )
        seen = set()
        for folder in reversed(template_dirs(game_id)):  # user templates win on equal names
            for file in sorted(folder.glob(sig.pattern)) if folder.exists() else []:
                if file.stem in seen:
                    continue
                img = cv2.imdecode(np.fromfile(str(file), np.uint8), cv2.IMREAD_GRAYSCALE)
                if img is None:
                    continue
                seen.add(file.stem)
                sig.templates.append(Template(file.stem, preprocess(img, sig.match)))
        signals.append(sig)
    return Profile(
        id=data["id"], name=data["name"], reference_width=data.get("reference_width", 1920),
        fps=data.get("fps", 5), regions={k: tuple(v) for k, v in data["regions"].items()},
        signals=signals, clips=data.get("clips", {}), weights=data.get("weights", {}),
        labels=data.get("labels", {}), path=path,
    )
