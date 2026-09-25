# Windows app

R6 Match Stats for Windows is the Streamlit dashboard (`scripts/app.py`)
packaged with Python, its libraries and `r6-dissect.exe`, so it runs on a PC
without installing anything else. It opens in its own window (Microsoft Edge
WebView2, built into Windows 10 and 11) with the app's icon in the taskbar,
runs the dashboard's server hidden in the background (only reachable from
that PC), and finds the game's MatchReplay folder on its own.

Users get it from the website's **Get the Windows app** page:

- `R6MatchStats-Setup.exe`, the installer: installs for the current user (no
  administrator needed), adds Start menu and desktop shortcuts, and an
  uninstaller in **Settings > Apps**. Running a newer installer updates the
  app in place.
- `R6MatchStats-Windows.zip`, the portable version: extract it and run
  `R6MatchStats\R6MatchStats.exe`.

## Build

From the repo root, in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File desktop\build.ps1
```

This needs Python 3.10+ (it uses `.venv` if there is one), Go 1.23+ (or an
already built `r6-dissect.exe` at the repo root) and Inno Setup 6, which the
script installs with winget if it's missing. It produces:

- `dist\R6MatchStats\R6MatchStats.exe` (run it to try the build)
- `dist\R6MatchStats-Setup.exe` (the installer)
- `dist\R6MatchStats-Windows.zip` (the portable version)

GitHub builds both for every published release with the **Windows app**
workflow (`.github/workflows/windows-app.yaml`), which also installs the app,
opens its window, checks that the dashboard shows up in it, and uninstalls it.
Set `R6_VERSION` (the workflow passes the release tag) to set the app's
version; otherwise it's `APP_VERSION` in `scripts/app_info.py`.

## Files

- `launcher.py` is the entry point. It opens the app window, starts the
  dashboard's server as a hidden copy of itself (`R6MatchStats.exe --serve`),
  and stops the server when the window closes. Opening the app while it's
  already open brings the existing window to the front. Without WebView2 it
  falls back to the default browser.
- `R6MatchStats.spec` tells PyInstaller what to bundle: a windowed exe (no
  console) with the icon and version details. The app files ship as plain
  files, because Streamlit runs `app.py` and its pages from disk.
- `installer.iss` is the Inno Setup script for the installer.
- `build.ps1` builds `r6-dissect.exe`, runs PyInstaller, zips the result and
  builds the installer. It also stamps `build\repo.txt` (the GitHub repo the
  app checks for updates) and `build\version.txt`.
- `assets\app.ico` is the icon (with `scripts\icon.png`, the page's favicon),
  drawn by `make_icon.py`.

The app writes its log to `%LOCALAPPDATA%\R6MatchStats\app.log`.

For testing, set `R6_NO_WINDOW=1` to open the app in the default browser
instead of a window, or `R6_SMOKE_TEST=result.json` to load the app, record
what the window shows, and quit (exit code 0 if the dashboard rendered).
