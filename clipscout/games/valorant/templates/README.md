# Valorant templates

Small greyscale crops of HUD elements, captured with the game area **1920 px wide**. Clipscout looks for them in
the regions from `../profile.json`. File names pick the signal:

| File pattern | Event | What to crop |
|---|---|---|
| `kill-1.png` … `kill-5.png` | kill | The kill banner icon in the lower middle after your 1st…5th kill of a round |
| `death-*.png` | death | Something that only shows while you're dead (e.g. the "killed by" panel) |
| `round-won*.png` / `round-lost*.png` | round result | The round result text in the top middle |
| `victory*.png` / `defeat*.png` | match result | The end-of-match banner |
| `agent-select*.png` | new match | Something unique to agent select (e.g. the lock-in button) |

Make one from your own recording:

```
clipscout grab recording.mkv --at 12:31.4 --region kill_banner --layout okami
```

That saves the region as a PNG. Crop it tight to the element in any image editor, then save it here (to ship it)
or in your user folder (`clipscout games` prints the path). Several files per event are fine – e.g. different
agents' kill banners or colourblind modes.
