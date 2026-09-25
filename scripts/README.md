# R6 Match Stats

Give it a Rainbow Six Siege match replay (a `.zip` of the match folder, the
folder itself, or its round `.rec` files) and it builds an **R6 Pro
League-style scoreboard**: one row per player, split by team, with the same
12 columns as the official R6 Esports match page.

| Player | EPS | KD (+/-) | Entry | KOST | KPR | HS | SRV | Clutches | Multikills | Objectives | Dead for trade kill | Trade kills |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Player1 | 116 | 8-2 (+6) | 4-0 (+4) | 100% | 1.14 | 62% | 71% | 0 | 1 | 0 | 1 | 0 |

It comes three ways, all with CSV/JSON export:

- **a website** (`app.py`, a Streamlit app you can host for free),
- **a Windows app** (`R6MatchStats-Setup.exe`, built from `desktop/`) with its
  own window, Start menu and desktop shortcuts, which reads your replays
  straight from the game's folder,
- **a command-line tool** (`match_stats.py`).

## Quick start (Windows)

From the repo root, in PowerShell:

```powershell
# 1. build the replay parser (needs Go 1.23+: https://go.dev/dl/)
go build -o r6-dissect.exe .

# 2. install the Python dependencies (Python 3.10+)
python -m venv .venv
.venv\Scripts\python -m pip install -r scripts\requirements.txt

# 3a. open the dashboard (http://localhost:8501)
.venv\Scripts\python scripts\app.py

# 3b. ...or print the scoreboard in the terminal
.venv\Scripts\python scripts\match_stats.py "C:\Users\you\Downloads\Match-2026-09-23_19-19-11-23660.zip"
```

On macOS/Linux, use `go build` (it produces `r6-dissect`), `source
.venv/bin/activate`, and forward slashes.

## Using the dashboard

The **Match report** page takes a **Replay source**:

- **Folder or zip on this computer**: a path to one match folder, a `.zip`, or
  your whole `MatchReplay` folder. It's filled in automatically when Siege is
  installed through Steam (any library) or Ubisoft Connect, and the latest
  match opens right away. With several matches you get a picker, and each
  match is parsed only when you pick it.
- **Upload**: drop the match's `.zip`, or every `.rec` file from the match folder.
- **From the replays/ folder**: copy matches into `replays/` at the repo
  root. Use this on GitHub Codespaces, where browser uploads over ~50 MB fail.

On the public website only **Upload** is offered: folder paths would read the
web server's disk, so they're only available to someone on the same computer
as the app.

Below the scoreboards you'll find CSV/JSON downloads and a round-by-round
breakdown for each player. The **Use demo match** toggle loads a built-in
sample match, so you can try the dashboard without a replay. The **Get the
Windows app** page has the download button and install steps.

## Command line

```
python match_stats.py SOURCE [--csv stats.csv] [--json stats.json]
```

`SOURCE` is a `.zip`, a match folder, a single `.rec`, or a folder of many
matches (each one gets its own scoreboard). `--csv` writes the numeric stats
(one row per player per match), and `--json` writes the scoreboards.

## Stat definitions

| Column | Meaning |
|---|---|
| EPS | Performance score, where 100 is the average player in this match. Ubisoft hasn't published its EPS formula, so this one is built from the same kind of inputs: kills and deaths per round, KOST, entry differential, multikills, clutches, objectives and trade kills, each compared against the other players in the match. |
| KD (+/-) | kills-deaths (difference) |
| Entry | opening kills-opening deaths. The opening duel is the round's first death. |
| KOST | % of rounds with a **K**ill, **O**bjective, **S**urvival or **T**raded death |
| KPR | kills per round |
| HS | headshot kills / kills |
| SRV | % of rounds survived |
| Clutches | rounds won as the team's last player alive against 1+ enemies |
| Multikills | rounds with 2+ kills |
| Objectives | defuser plants + defuser disables |
| Dead for trade kill | this player's deaths that a teammate avenged within 10 s |
| Trade kills | kills on an enemy who had killed a teammate within the previous 10 s |

Team kills never count as kills, but the victim still gets a death.

### Known limitations

- **Objectives:** replays from the current game version (Y11S3) don't say
  *who* planted or disabled the defuser. The parser works it out from which
  player put their weapon away when the plant or disable started (see
  `dissect/defuse.go`). Across 22 test matches this named a player on the
  correct side for every plant and disable. If it can't tell, a plant is
  credited only when a single player on that side was alive.
- **EPS** is a close stand-in, not Ubisoft's exact number.
- Rounds that ended without a score change (an abandoned match) have no
  winner, so they give no clutch.

## Publishing

### The website (Streamlit Community Cloud, free)

Streamlit Community Cloud only deploys from a GitHub repo you're an admin of.
If you aren't one, fork this repo first: the fork is yours, and the website's
download button automatically points at the fork's releases.

1. On GitHub, fork this repository to your account.
2. Go to <https://share.streamlit.io>, sign in with GitHub, and choose
   **Create app** > **Deploy a public app from GitHub**.
3. Fill in: **Repository** `<you>/r6-dissect`, **Branch** the branch with
   this code (for example `feat/pro-league-stats`), **Main file path**
   `scripts/app.py`. Optionally pick a custom **App URL**.
4. Under **Advanced settings**, choose Python 3.13, then click **Deploy**.

It uses the Linux `r6-dissect` binary committed at the repo root, so rebuild
and commit it (`GOOS=linux GOARCH=amd64 go build -o r6-dissect .`) after
changing the Go parser. Every push to the branch redeploys the site.

### The Windows app (GitHub Releases)

The **Windows app** workflow (`.github/workflows/windows-app.yaml`) builds the
installer (`R6MatchStats-Setup.exe`) and a portable zip, installs and opens
the app on a Windows machine to check it works, and attaches both files to
every published release. The website's download button points at the newest
release that has the installer. Until there is one, the page says the app
hasn't been published yet.

1. On a fork, open the **Actions** tab once and enable workflows.
2. On GitHub, go to **Releases** > **Draft a new release**, create a tag like
   `v1.1.0` (the app takes its version from the tag), and click **Publish
   release**. About ten minutes later the installer appears on the release.

The installed app's **Get the Windows app** page tells users when a newer
release is out, and running the new installer updates the app in place.

To build it on your own PC instead, run
`powershell -ExecutionPolicy Bypass -File desktop\build.ps1`, then drag
`dist\R6MatchStats-Setup.exe` and `dist\R6MatchStats-Windows.zip` onto a
release. See [desktop/README.md](../desktop/README.md).

## Architecture

```
.zip / folder / .rec
   │  parser.collect_rec_files + group_by_match   (unzip, split into matches)
   ▼
r6-dissect (Go CLI, repo root)  →  JSON per round
   │  parser.normalize_from_r6_dissect             (stable internal schema)
   ▼
metrics_engine.compute_match_metrics  →  PlayerStats per player
   │  metrics_engine.pro_league_rows               (the 12 display columns)
   ▼
app.py → report.py, download.py (Streamlit)  /  match_stats.py (CLI)
```

`app.py` is the entry point: it sets up the page and the two pages
(`report.py`, `download.py`). `app_info.py` holds the app name, version and
download links, and tells whether it's running as the public website, the
Windows app (`desktop/launcher.py`), or from a source checkout.

`parser.py` finds the r6-dissect binary via `$R6_DISSECT_BIN`, then `PATH`,
then `r6-dissect.exe` (Windows) or `r6-dissect` at the repo root, then
`~/go/bin`. If a future r6-dissect release renames JSON fields, only
`normalize_from_r6_dissect` needs updating.

**Season-long stats:** `season_stats.py` (`StatsManager`) logs tracked
players' rounds into SQLite across a season without double-counting. See
[SEASON_STATS.md](SEASON_STATS.md) and `example_season_stats.py`.

## Tests

```bash
python -m unittest discover -s scripts   # metrics engine, pages, replay files, season stats
go test ./...                            # the Go replay parser
```

## Troubleshooting

- **"r6-dissect not found"**: build it at the repo root (step 1), or set
  `R6_DISSECT_BIN` to its full path.
- **Every stat is 0 / "no player data"**: expand **Parser debug info** in the
  sidebar to see what r6-dissect returned. Practice sessions and matches that
  ended during prep have no kill feed.
- **A map shows as `Map(123...)`**: the map is newer than this r6-dissect
  build; add its ID to `dissect/header.go` and re-run `stringer -type=Map`.
