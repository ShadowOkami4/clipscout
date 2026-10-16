# Clipscout

Finds the highlights in your game and stream recordings by **reading the game's HUD**: kill banners, round results,
victory screens. It suggests clips, lets you review them in your browser, and cuts the ones you keep at full quality.

- **Lightweight:** Python with OpenCV and NumPy. ffmpeg does the decoding (with your GPU when it can), and only a few
  frames per second are checked.
- **Windows and Linux.**
- **Works on stream recordings too:** tell it where the game sits in your layout (`--layout`) and it ignores the rest.
- **Offline and private:** it only reads your video file and never touches the game, so it's safe with anti-cheat.

> **Status: early.** Valorant works on 1080p footage. In a 65-minute test recording it found all 43 kill banners
> with no false ones, plus round results, deaths, the victory screen and "match found". Other games follow.

## Install

You need **Python 3.10+** and **ffmpeg** on your PATH.

```bash
# Windows
winget install Gyan.FFmpeg
# Linux (Debian/Ubuntu)
sudo apt install ffmpeg

pipx install git+https://github.com/ShadowOkami4/clipscout
```

For development:

```bash
git clone https://github.com/ShadowOkami4/clipscout && cd clipscout
python -m venv .venv
.venv/Scripts/activate        # Linux: source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Use

```bash
clipscout scan "2026-10-15 20-01-33.mkv" --game valorant
clipscout review "2026-10-15 20-01-33.mkv"
clipscout export "2026-10-15 20-01-33.mkv"
```

1. **`scan`** checks 5 frames per second, logs every event it finds and groups close events into clips: 6 s before
   the first event and 3 s after the last. It writes `<recording>.clipscout/project.json` and fast preview clips.
2. **`review`** opens a local page (127.0.0.1 only):
   - **Watch and decide:** play each suggestion, then **Keep** (K) or **Skip** (X).
   - **Trim:** nudge the start and end by 2 s at a time.
   - **Sort and filter:** by event type, time or score.
   - **Export:** cut every kept clip from the page.
3. **`export`** cuts the kept clips from the original recording into `<recording>.clipscout/export/`. It copies the
   streams by default (no quality loss, all audio tracks kept). Use `--accurate` for frame-exact cuts, which
   re-encodes; use `--all` to export every suggestion without reviewing.

Useful options:

| Option | What it does |
|---|---|
| `--layout okami` / `--layout 80,18,1760,990@1920x1080` | Where the game sits in the recording (stream layouts). Default `full`. |
| `--start 20:00 --end 1:10:00` | Scan only part of the recording. |
| `--threads 4` | Caps ffmpeg's CPU use (default 4, so the PC stays usable). |
| `--hwaccel cuda` | Pick the hardware decoder (`auto` by default, `none` to turn it off). |
| `--debug` | Also writes `trace.csv` with every signal's match score per frame, for tuning thresholds. |
| `--review` | Open the review page as soon as the scan finishes. |

### Tip for OBS recordings

Set **Settings → Output → Recording → Keyframe Interval** to **2 s**. Some encoders (e.g. AV1 on "auto") put
keyframes minutes apart. Clipscout still handles that by re-encoding all clips in a single pass, but with 2 s
keyframes the clips are copied losslessly and almost instantly.

## Games

| Game | Events | State |
|---|---|---|
| Valorant | kills (incl. multi-kills), deaths, round won/lost (WON, FLAWLESS, ACE, LOST), victory, new match | works; a defeat template is still missing |

`clipscout games` lists every profile, its signals and whether templates exist.

### Templates

Detection matches small template images in fixed HUD regions. Templates are captured with the game area
**1920 px wide**, and Clipscout scales your footage to match. That means one template works for 1080p, 1440p, 4K
and shrunk-down stream layouts alike.

```bash
# Save one HUD region at a moment where the element is on screen
clipscout grab recording.mkv --at 12:31.4 --region kill_banner --layout okami
```

Crop the saved PNG tightly to the element. Then save it in your user folder (`clipscout games` shows the path), or
in `clipscout/games/<game>/templates/` if you're contributing it. The file name chooses the event, for example
`kill-2.png` or `round-won.png`; [the template README](clipscout/games/valorant/templates/README.md) lists them all.

### Adding a game

A game is a folder in `clipscout/games/<id>/` with a `profile.json` and its templates:

- **`regions`:** HUD areas as fractions `[x, y, w, h]` of the game area.
- **`signals`:** which templates to look for in which region.
  - **`threshold`:** the match score that counts as found.
  - **`min_frames`:** how many frames in a row it must be found.
  - **`cooldown`:** seconds before the same signal can fire again.
  - **`match`:** `"edges"` (ignores colours and backgrounds, usually best for HUD icons) or `"gray"`.
- **`clips`:** padding before and after events (`pre`, `post`), and the gap that merges close events (`merge_gap`).
- **`weights`:** how much each event counts. Events with weight 0, like deaths, never start a clip on their own,
  but they still show up inside clips.

Run a scan with `--debug` and look at `trace.csv` to pick good thresholds.

## Roadmap

- [ ] Valorant templates from real footage
- [ ] Chat-spike detection from a chat log, and stream markers
- [ ] CS2 (Game State Integration plus HUD), Rocket League
- [ ] Vertical 9:16 export for Shorts

## License

MIT
