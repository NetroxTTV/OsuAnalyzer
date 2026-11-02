# osu! Hit Analyzer

A desktop app for osu!standard that reads your replays and shows **where** and **when** you actually hit each note — so you can see whether you overaim, underaim, tap early or late, and how to adjust your tablet area.

It works with osu!stable: it finds your osu! folder, lists the replays in `Replays/`, and looks up the matching beatmap in your `Songs/` folder automatically.

## Download

Grab **`osu-Hit-Analyzer.exe`** from the [latest release](https://github.com/NetroxTTV/OsuAnalyzer/releases/latest) and run it. No install needed.

> Windows may show a SmartScreen warning because the exe isn't code-signed. Click **More info → Run anyway**, or [build it yourself](#build-from-source).

## Features

### Replay Viewer
- Plays the replay with the beatmap's music: notes, approach circles, sliders, cursor and trail
- Key presses timeline (K1/K2), click points, 300/100/50/miss judgements and a hit error bar
- Playback speed from 0.25× to 2× (DT/HT keep pitch, NC shifts it like in game)
- Jump straight to the next / previous miss

### Hit Analyzer
- Every hit drawn inside one normalised circle (edge = the real hit-circle radius)
- Average hit position, spread and early/late timing at a glance
- **Screen** view (raw axes) or **Movement** view (rotated so the jump direction points right — makes over/underaim obvious)
- Colour by timing error or by 300 / 100 / 50
- Include or ignore slider heads
- Ctrl/Shift-click several replays to combine them
- Save the plot as an image

### Tablet Zone
- Shows where on the playfield you overaim or underaim
- Suggests a corrected tablet area (top / bottom / left / right, in tablet points as in Wacom Center) from your systematic aim errors

### Quality of life
- New replays load automatically as soon as osu! saves them (F2 after a play)
- Filter replays by map, difficulty or player, or drag & drop `.osr` files onto the window
- Custom accent colour (applied instantly) and beatmap background dim

## Keyboard shortcuts

| Key | Action |
| --- | --- |
| `Ctrl+1` / `Ctrl+2` / `Ctrl+3` | Replay Viewer / Hit Analyzer / Tablet Zone |
| `Ctrl+,` | Settings |
| `Ctrl+O` | Open replay files |
| `Ctrl+F` | Filter the replay list |
| `Ctrl+S` | Save the analyzer image |
| `F5` | Rescan the replay list |
| `Space` | Play / pause (viewer) |
| `←` / `→` | Seek 1 second |
| `,` / `.` | Step one frame back / forward |
| `N` / `P` | Next / previous miss |
| `M` | Mute |

## Run from source

Requires Python 3.10+ on Windows.

```powershell
python -m pip install -r requirements.txt
python gui.py
```

There's also a command-line version that just plots the hits:

```powershell
python osu_hit_analyzer.py                         # file pickers
python osu_hit_analyzer.py replay.osr              # beatmap found automatically
python osu_hit_analyzer.py a.osr b.osr --save out.png
python osu_hit_analyzer.py replay.osr --beatmap map.osu --frame movement
python osu_hit_analyzer.py --help
```

If your osu! folder isn't detected, pick it in **Settings → osu! folder**, set the `OSU_DIR` environment variable, or pass `--osu-dir` to the CLI.

## Build from source

```powershell
python -m pip install -r requirements.txt pyinstaller
./build.ps1
```

This produces `osu Hit Analyzer.exe` (single file, no console window) in the project folder. The recipe is in `build.spec`; `build.ps1` first regenerates `assets/splash.png` from the app's loading screen (`tools/make_splash.py`) so the image shown while the exe unpacks matches it.

Pushing a tag like `v1.0.0` builds the exe on GitHub Actions and attaches it to a draft release. The tag must match `__version__` in `osu_analyzer/__init__.py`.

## Project layout

```
gui.py                  desktop app entry point
osu_hit_analyzer.py     command-line entry point
osu_analyzer/
  core/                 no UI: replay / beatmap parsing, hit detection, statistics, tablet calibration
  ui/                   PySide6 app
    theme.py, icons.py  colours, fonts, stylesheet, icon glyphs
    widgets/            custom painted widgets (buttons, segmented control, cards, inputs...)
    viewer/             Replay Viewer: scene, playback clock, renderers, seek bar, page
    analyzer/           Hit Analyzer: hit scatter, charts, page
    tablet/             Tablet Zone
    main_window.py      wires the sidebar, the analysis controller and the pages together
  audio.py              music playback for the viewer
  plot.py, cli.py       matplotlib plot used by the command line
tools/make_splash.py    renders assets/splash.png from the loading screen
build.spec, build.ps1   exe build
```

## Where data is stored

The app keeps a beatmap index (so lookups are instant after the first scan) and your settings in `%LOCALAPPDATA%\osu-hit-analyzer\`. Delete that folder to reset everything. Your osu! files are only ever read, never modified.

## License

[MIT](LICENSE)

osu! Hit Analyzer is a fan-made tool and is not affiliated with or endorsed by ppy Pty Ltd. "osu!" is a trademark of ppy Pty Ltd.
