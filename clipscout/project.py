"""Loading, saving and exporting a scan's project.json."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .export import cut, cut_many, sparse_keyframes


def resolve_project(path: str | Path) -> Path:
    """Accepts project.json, its folder, or the recording itself."""
    p = Path(path)
    if p.is_dir():
        p = p / "project.json"
    elif p.suffix.lower() != ".json":
        p = p.with_name(p.stem + ".clipscout") / "project.json"
    if not p.exists():
        raise FileNotFoundError(f"No project at {p} – run `clipscout scan` on the recording first.")
    return p


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, project: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(project, indent=2), encoding="utf-8")
    tmp.replace(path)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "clip"


def export_clips(path: Path, everything: bool = False, accurate: bool = False, threads: int = 4, log=print) -> list[Path]:
    project = load(path)
    clips = project["clips"]
    chosen = clips if everything else [c for c in clips if c.get("keep") is True]
    if not chosen:
        raise RuntimeError("No clips marked to keep. Review them first (`clipscout review`) or export everything with --all.")
    out_dir = path.parent / "export"
    stem = Path(project["video"]).stem
    jobs = [(c["start"], c["end"], out_dir / f"{stem}_{c['id']}_{slug(c['title'])}.mp4") for c in chosen]
    if len(jobs) > 1 and (accurate or sparse_keyframes(project["video"], [(a, b) for a, b, _ in jobs])):
        # Re-encoding anyway: one pass over the file beats seeking for every clip.
        cut_many(project["video"], jobs, threads=threads, log=log)
    else:
        for i, (a, b, out) in enumerate(jobs, 1):
            log(f"  [{i}/{len(jobs)}] {out.name}")
            cut(project["video"], a, b, out, accurate=accurate, threads=threads)
    return [out for _, _, out in jobs]
