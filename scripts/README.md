# R6 Match Stats

Give it a Rainbow Six Siege match replay (a `.zip` of the match folder, the
folder itself, or its round `.rec` files) and it builds an **R6 Pro
League-style scoreboard**: one row per player, split by team, with the same
12 columns as the official R6 Esports match page.

| Player | EPS | KD (+/-) | Entry | KOST | KPR | HS | SRV | Clutches | Multikills | Objectives | Dead for trade kill | Trade kills |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Player1 | 116 | 8-2 (+6) | 4-0 (+4) | 100% | 1.14 | 62% | 71% | 0 | 1 | 0 | 1 | 0 |

It comes three ways, all with CSV, JSON and TXT export:

- **a website** (`app.py`, a Streamlit app you can host for free),
- **a Windows app** (`R6MatchStats-Setup.exe`, built from `desktop/`) with its
  own window, Start menu and desktop shortcuts, which reads your replays
  straight from the game's folder,
- **a command-line tool** (`match_stats.py`).

> R6 Match Stats is an unofficial fan project, free to use. It isn't made,
> endorsed or supported by Ubisoft. Rainbow Six and Ubisoft are trademarks of
> Ubisoft Entertainment. See [Ubisoft's terms](#ubisofts-terms).

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

The top navigation includes **Dashboard**, **Match History**, **Operator
Analytics**, **Team Analytics**, and **School Selection**. Dashboard takes a
**Replay source**:

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

Below the scoreboards you'll find CSV, JSON and TXT downloads and a round-by-round
breakdown for each player. The **Use demo match** toggle loads a built-in
sample match, so you can try the dashboard without a replay. The **Get the
Windows app** page has the download button and install steps.

Open **Season tracker** below a loaded scoreboard to choose a roster and record
the match. Only players explicitly tracked are saved, and duplicate rounds are
ignored. Match History and Team Analytics read those season totals from SQLite.
Operator Analytics summarizes operator picks and round outcomes for the latest
replay loaded in the current browser session.

### NECC school data

School Selection accepts a JSON catalog upload. A deployment can instead set
`NECC_R6_DATA_URL` to an HTTPS JSON endpoint that returns the same shape. The
catalog uses a top-level `schools` array; each school may contain `logo_url`,
`primary_color`, and `teams`. R6 team entries may contain `name`, `game`,
`roster` (strings or `{ "name": "..." }` objects), `standings`, and `matches`.
Other explicitly named games are filtered out. Selecting a school updates the
dashboard accent and lets you add its roster to the season tracker.

No NECC endpoint or API credentials are bundled: the official sites did not
provide a usable public feed from this environment. Until a supported endpoint
is configured, import a catalog exported from an authorized NECC source.

## Command line

```
python match_stats.py SOURCE [--csv stats.csv] [--json stats.json] [--txt stats.txt]
```

`SOURCE` is a `.zip`, a match folder, a single `.rec`, or a folder of many
matches (each one gets its own scoreboard; up to four are parsed at once).
`--csv` writes the numeric stats (one row per player per match), `--json`
writes the scoreboards, and `--txt` writes the scoreboards as plain text,
exactly as printed. Use any of them together, or none to just print.

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
and commit it (`GOOS=linux GOARCH=amd64 go build -trimpath -o r6-dissect .`;
`-trimpath` keeps your PC's folder paths out of it) after changing the Go
parser. Every push to the branch redeploys the site.

### The Windows app (GitHub Releases)

The **Windows app** workflow (`.github/workflows/windows-app.yaml`) builds the
installer (`R6MatchStats-Setup.exe`) and a portable zip, runs the tests,
scans the build with Microsoft Defender, installs and opens the app on a
Windows machine to check it works, and attaches both files plus their
checksums (`SHA256SUMS.txt`) to every published release. The website's download button points at the newest
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
`dist\R6MatchStats-Setup.exe`, `dist\R6MatchStats-Windows.zip` and
`dist\SHA256SUMS.txt` onto a release. See [desktop/README.md](../desktop/README.md).

## Safety

- **Only replays get through.** `file_guard.py`'s `ReplayScanner` checks every
  file before the parser sees it, whether it's uploaded, in a zip or in a
  folder. A file must be named `.rec`, be a plausible size for one round, and
  start with the bytes every Siege replay starts with. Anything else, like a
  renamed program, is skipped and listed on the page, and never even written
  to disk. Zips and uploads are also capped in file count and total size, and
  a zip's folder names can't write outside its temporary folder.
- **The Windows app checks itself.** The build records every file's SHA-256
  (`desktop/integrity.py`), and each time the app opens it refuses to run if
  any file was changed, added (say, a planted DLL) or removed. It can't catch
  someone replacing `R6MatchStats.exe` itself or a DLL Windows loads before
  the app's code starts. For that, compare the download with the published
  checksum (the download page shows it) and only download from the official
  release.
- **Builds are scanned.** The release workflow scans each build with Microsoft
  Defender and won't publish one it flags. The app isn't code-signed, which is
  why Windows SmartScreen warns about it. A code-signing certificate would
  remove that warning.
- **Replays are temporary; tracking is opt-in.** The Windows app reads replays
  in place and never writes to the game's folders. Uploads are deleted after an
  hour unused. When you choose to track players and save a match in a private
  local deployment, derived stats and tracked names are stored in SQLite:
  `%LOCALAPPDATA%\R6MatchStats\season_stats.db` in the Windows app, or
  `data/season_stats.db` in a source checkout. Delete that database to remove
  saved season stats. Tracking writes are disabled on shared public hosting so
  visitors' stats are not mixed into a server-wide database.

## Ubisoft's terms

This tool is built to stay clear of the Rainbow Six Siege EULA and Ubisoft's
Terms of Use, but it isn't approved by Ubisoft, and only Ubisoft can say for
certain what it allows:

- **Not a cheat or a game tool** (EULA 1.2(iii), EULA 4, Terms 7.3.4): it never
  touches the game while it runs. It doesn't read the game's memory, inject
  anything, automate input or change game files. It only reads replay files the
  game already saved, after the match, so it gives no advantage in a match.
- **Nothing online** (Terms 7.3.5, 7.3.6): it never connects to the game,
  Ubisoft's servers or anyone's Ubisoft account, and it doesn't scrape or
  collect data. Each person looks at their own replays.
- **Non-commercial** (EULA 1.1, 1.2(i), Terms 1.3): it's free, with no ads or paid
  features. Keep it that way.
- **No implied endorsement** (EULA 1.3.j) and **Ubisoft's IP** (EULA 2, Terms 9):
  the app, the installer and this README say it's unofficial and not endorsed.
  It uses no Ubisoft logos or artwork (the icon is original). It uses
  Siege's names, such as maps, operators and "R6", only to describe the game's
  data.
- **The grey area: reverse engineering** (EULA 1.2(ii)). Reading the `.rec`
  replay format relies on community reverse-engineering of that format
  ([r6-dissect](https://github.com/redraskal/r6-dissect)), which the EULA's
  no-reverse-engineering clause could be read to cover. That the format has
  been publicly documented for years isn't permission. If you want certainty,
  ask Ubisoft before publishing widely.
- **Don't feed replays to AI tools** (Terms 1.3): the Terms forbid using game
  content as input to AI tools. The app doesn't, but keep that in mind when
  asking an assistant for help with replay data.

## Architecture

```
.zip / folder / .rec
   │  file_guard.ReplayScanner                    (only real replays get through)
   │  parser.collect_rec_files + group_by_match   (unzip, split into matches)
   ▼
r6-dissect (Go CLI, repo root)  →  JSON per round
   │  parser.normalize_from_r6_dissect             (stable internal schema)
   ▼
metrics_engine.compute_match_metrics  →  PlayerStats per player
   │  metrics_engine.pro_league_rows               (the 12 display columns)
   ▼
app.py → report.py, history.py, operators.py, teams.py, schools.py, download.py
  (Streamlit)  /  match_stats.py (CLI)
```

`app.py` is the entry point: it sets up the page, Three.js scene, and navigation
across the dashboard pages. `app_info.py` holds the app name, version and
download links, and tells whether it's running as the public website, the
Windows app (`desktop/launcher.py`), or from a source checkout.

The React and Unity clients use the shared FastAPI service in `api.py`. Start it
from the repository root:

```bash
pip install -r scripts/requirements-api.txt   # FastAPI, Uvicorn; the Streamlit app doesn't need them
PYTHONPATH=scripts uvicorn api:app --app-dir scripts --host 127.0.0.1 --port 8000
```

The service exposes `GET /api/v1/health`, season summaries and match history,
roster tracking, replay upload/path parsing, match logging, and school catalog
read/import routes. The API and existing Streamlit tracker use the same SQLite
database. Set `R6_STATS_DB` to choose its path; on Windows set `R6_DESKTOP=1` to
use `%LOCALAPPDATA%\R6MatchStats\season_stats.db`. It binds to loopback by
default and has no authentication, so do not expose it to an untrusted network.

`parser.py` finds the r6-dissect binary via `$R6_DISSECT_BIN`, then `PATH`,
then `r6-dissect.exe` (Windows) or `r6-dissect` at the repo root, then
`~/go/bin`. If a future r6-dissect release renames JSON fields, only
`normalize_from_r6_dissect` needs updating.

**Season-long stats:** `season_stats.py` (`StatsManager`) logs tracked
players' rounds into SQLite across a season without double-counting. The Team
Analytics, Match History, and School Selection pages use this data. See
[SEASON_STATS.md](SEASON_STATS.md) and `example_season_stats.py`.

## Tests

```bash
python -m unittest discover -s scripts   # metrics engine, pages, command line, replay files and scanner, season stats
python -m unittest discover -s desktop   # the Windows app's integrity check
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
