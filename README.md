# VLC Redesign

A desktop media player built from the community Figma concept **"VLC Redesign"**. It uses
VLC's own playback engine (**libVLC**), so it plays everything VLC plays, but the interface
is new: a frameless dark window, an orange play button, a wedge-shaped volume control, and
overlay panels for the queue, settings and tracks.

> This is a concept implementation. It isn't affiliated with VideoLAN. VLC is a trademark of VideoLAN.

## Download

Get the latest build from the [Releases page](https://github.com/satvik1808/vlc-redesign/releases/latest):

- **`VLCRedesign-<version>-setup-win64.exe`**: the installer. It installs for your user
  without admin rights, adds a Start menu entry, and can add the player to "Open with" for
  video and audio files. Uninstall it from Windows Settings → Apps.
- **`VLCRedesign-<version>-portable-win64.zip`**: unzip and run `VLCRedesign.exe`.

Both are self-contained: libVLC is bundled, so you don't need VLC or Python installed.
The builds aren't code-signed, so Windows SmartScreen may warn the first time you run one.
Click **More info → Run anyway**.

## Build the installer

```bash
.venv\Scripts\python -m pip install pyinstaller
```

```bash
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

The build needs VLC 3 (64-bit) installed, because its libVLC is what gets bundled, and
[Inno Setup 6](https://jrsoftware.org/isinfo.php). The output goes to `build\`.

## Run from source

Requirements:
- Windows 10/11.
- **VLC 3 (64-bit)** installed. The player loads `libvlc.dll` from the VLC install folder,
  or from the folder in the `VLC_PATH` environment variable.
- Python 3.10 or later.

First-time setup (from this folder):

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Start the player. You can pass files or folders to play:

```bash
run.bat
```

```bash
run.bat "D:\Movies\film.mkv"
```

## What's in the design, and what it does here

| Area | Implemented |
|---|---|
| **Title bar** | Cone logo, menu (⋯), library toggle, folder breadcrumb of the current file, centred title, minimise / maximise / fullscreen / close. Drag to move, double-click to maximise, resize from the window edges (with Aero Snap). |
| **Control bar** | Previous, play/pause pill, next, elapsed time, seek bar (hover time, chapter ticks, optional subtitle-cue marks), duration, mute, volume wedge (click, drag or scroll), tracks, subtitles, settings and queue buttons. |
| **Queue panel** | Queue (drag to reorder, item count and total length, sort, repeat off/all/one, shuffle, remove, add), Bookmarks (add at the current time, click to seek, rename, delete; saved per file), Chapters (click to jump; the current chapter is highlighted). |
| **Settings → Playback** | Subtitle timeline on the seek bar, statistics overlay, resume where you left off, sleep timer (minutes or end of item), audio visualiser, speed slider from 0.25× to 2×. *Reverse* is shown disabled because libVLC 3 can't play in reverse. |
| **Settings → Video** | Flip, rotate, zoom, aspect ratio, crop, deinterlace, and brightness / contrast / saturation / hue / gamma. |
| **Settings → Audio** | Audio track, stereo mode, audio delay (field and slider), equaliser presets plus 10 bands and preamp. |
| **Settings → Subtitles** | Subtitle track, add a subtitle file, subtitle delay, and font, size, colour and background box (these apply on the next start). |
| **Tracks popup** | Video, audio and subtitle tracks with check marks, audio output devices with refresh, external subtitle tracks, and a "Show Preferences" button. |
| **Library sidebar** | Home (Continue Watching, Listen Again, frequently visited folders and playlists), Videos, Music, Network streams, Playlists (create, rename, delete, add to), History, and a button to add a folder. Back/forward, sort, details toggle, search filter, and "show in Explorer". |

Also: drag and drop files, folders or subtitles onto the window; fullscreen with an
auto-hiding control bar; on-screen messages; snapshots; always-on-top. The queue, volume,
window position, history, resume points, bookmarks and playlists are kept in
`%APPDATA%\VLCRedesign\library.json`.

## Keyboard shortcuts

| Key | Action |
|---|---|
| Space | Play / pause |
| F / F11, Esc | Fullscreen, exit fullscreen or close panels |
| ← → / Shift / Ctrl | Seek 10 s / 3 s / 1 min |
| ↑ ↓, M | Volume, mute |
| N / P, S, E | Next / previous, stop, next frame |
| [ ] = | Slower / faster / normal speed |
| V, B, H / J | Cycle subtitles, cycle audio track, subtitle delay |
| Ctrl+O / Ctrl+F / Ctrl+N | Open a file / folder / network stream |
| Ctrl+L, Q, Ctrl+P | Library, queue, settings |
| Ctrl+B, Shift+S | Add a bookmark, take a snapshot |

## Code layout

```
vlcredesign/
  __main__.py    app setup (font, stylesheet, icon)
  mainwindow.py  frameless window, title bar, video surface, control bar, play queue
  engine.py      libVLC wrapper (python-vlc); all playback goes through VLC
  panels.py      queue / bookmarks / chapters, settings, and the tracks popup
  library.py     sidebar library
  widgets.py     custom-painted controls (seek bar, volume wedge, toggles, tabs, sliders)
  rows.py        the list-row delegate shared by every list
  icons.py       line-icon set and the cone artwork
  theme.py       colour tokens and the Qt stylesheet
  store.py       JSON persistence and helpers
```

## Planned / future upgrades

Not implemented yet:

- Actual VLC icons
- Winter-themed and Halloween-themed icons
- YouTube integration
- YouTube direct download (scope to be decided)
- Auto-update from within the app
- Generalized aggregator and viewer for Prime Video and other streaming services

## License

Copyright (C) 2026 satvik1808

This program is free software: you can redistribute it and/or modify it under the terms of
the GNU General Public License as published by the Free Software Foundation, either version 3
of the License, or (at your option) any later version. See [LICENSE](LICENSE).

The packaged builds also bundle libVLC and its plugins (LGPL-2.1+ / GPL-2.0+), Qt / PySide6
(LGPL-3.0), python-vlc (LGPL-2.1+) and Python (PSF). Their licences and source links are in
`THIRD-PARTY-NOTICES.txt` and `vlc\COPYING.txt` inside the app.

The cone on the start screen (`vlcredesign/assets/vlc-cone-256.png`) is VLC's own icon artwork,
(c) VideoLAN, distributed with VLC under GPL-2.0-or-later. The VLC name and cone are trademarks of
VideoLAN; this project uses them only to identify VLC and is not affiliated with VideoLAN.

### Implementation notes
- libVLC draws into a native child window. The overlay panels are native windows too, so
  they can sit on top of the video. Rounded corners come from window masks.
- In libVLC 3, flip, rotate and the audio visualisers only work as instance options. When
  you change one, the engine rebuilds the libVLC instance at the current position and keeps
  the rest of your settings.
