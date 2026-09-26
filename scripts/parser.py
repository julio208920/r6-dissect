"""
parser.py
=========
Reads Rainbow Six Siege replay files (.rec) and normalizes them into the
internal schema used by metrics_engine.py.

IMPORTANT ENGINEERING NOTE
---------------------------
The .rec binary format is proprietary and undocumented by Ubisoft, reverse
-engineered by the community and shifting with game patches. This module
shells out to r6-dissect (https://github.com/redraskal/r6-dissect), the
actively maintained Go CLI, rather than re-deriving the byte layout in
Python.

SCHEMA (verified against dissect v0.24.x source -- header.go, feedback.go,
stats.go, match.go -- and the project's own published example output):

Single `.rec` file (one round) -> r6-dissect emits ONE round object at the
JSON root:
    {
      "gameVersion": str, "codeVersion": int, "timestamp": str,
      "matchType": {"name": str, "id": int},
      "map": {"name": str, "id": int},
      "gamemode": {"name": str, "id": int},
      "site": str, "roundNumber": int, "matchID": str,
      "teams": [
        {"name": str, "score": int, "won": bool,
         "winCondition": str, "role": "Attack"|"Defense"},
        {...}
      ],
      "players": [
        {"id": int, "username": str, "teamIndex": 0|1,
         "operator": {"name": str, "id": int}, ...}
      ],
      "matchFeedback": [
        {"type": {"name": "Kill"|"Death"|"DefuserPlantStart"|"DefuserPlantComplete"|
                          "DefuserDisableStart"|"DefuserDisableComplete"|
                          "LocateObjective"|"OperatorSwap"|"Battleye"|
                          "PlayerLeave"|"Other", "id": int},
         "username": str, "target": str, "headshot": bool,
         "time": "M:SS", "timeInSeconds": float, "message": str}
      ],
      "stats": [                     # may or may not be present depending
        {"username": str, "score": int, "kills": int, "died": bool,   # on installed r6-dissect version -- treated as optional
         "assists": int, "headshots": int, "headshotPercentage": float,
         "1vX": int}                 # clutch size won this round, omitted if 0
      ]
    }

A whole match FOLDER (multiple .rec files) -> r6-dissect wraps the same
per-round object shape inside a "rounds" list, plus a match-level "stats"
summary:
    {"rounds": [ <round object as above>, ... ], "stats": [ PlayerMatchStats, ... ]}

Notably: `map`, `matchType`, `gamemode`, and each matchFeedback `type` are
OBJECTS ({"name","id"}), not plain strings -- a naive `.get("map")` used as
a display string will render the whole dict. This module extracts
`.get("name")` from all four.

`matchFeedback` is consumed in array order, which is r6-dissect's own
chronological append order. The in-game clock (`timeInSeconds`) counts
down and resets when the defuser is planted, so each normalized event also
gets a monotonic `elapsed` (seconds since the round's first event), which
metrics_engine.py uses for trade windows.

Per-round `stats` are only used for assists (read from the scoreboard,
which the kill feed can't provide); everything else is derived from
`matchFeedback` so team kills and the round winner are handled one way.

Plant/defuse events name the player. Y11S3 replays don't say who it was
directly, so r6-dissect works it out (see dissect/defuse.go); if it can't,
the event arrives with no username and metrics_engine.py credits it only
when exactly one player on the acting side was alive.

`parse_match` takes the round files of one match; `collect_rec_files` and
`group_by_match` turn a folder, a .zip, or a whole MatchReplay directory
into per-match lists of round files first.

Falls back to a bundled synthetic sample match (sample_data.py) if the CLI
isn't installed, so the dashboard is runnable/demoable without it.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

from file_guard import ReplayRejected, ReplayScanner


class ReplayParseError(Exception):
    pass


def _find_r6_dissect() -> str | None:
    """Locate the CLI: $R6_DISSECT_BIN, then PATH, then the binary built at
    this repo's root (`go build`), then `go install`'s default dir."""
    exe = "r6-dissect.exe" if sys.platform == "win32" else "r6-dissect"
    repo_root = Path(__file__).resolve().parent.parent
    candidates = [
        os.environ.get("R6_DISSECT_BIN"),
        shutil.which("r6-dissect"),
        str(repo_root / exe),
        str(Path.home() / "go" / "bin" / exe),
    ]
    for c in candidates:
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return c
    return None


R6_DISSECT_BIN = _find_r6_dissect()

_ANSI = re.compile(r"\x1b\[[0-9;]*m")  # r6-dissect's log output is colorized

# a full match is ~6-14 MB per round; allow generous time per round file
_SECONDS_PER_ROUND = 60

# r6-dissect is a console program. Started from the Windows app, which has no console,
# Windows would open (and close) a console window for every parse; this runs it hidden.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def r6_dissect_available() -> bool:
    return R6_DISSECT_BIN is not None


def _run_r6_dissect(rec_path: Path, num_rounds: int = 1) -> dict[str, Any]:
    """Shell out to the r6-dissect CLI and return its parsed JSON. `rec_path`
    may be a single .rec file or a folder of them (a whole match)."""
    if not r6_dissect_available():
        raise ReplayParseError(
            "r6-dissect executable not found. Build it at the repo root with "
            "`go build`, put it on PATH, or set R6_DISSECT_BIN to its path "
            "(see README) -- or run the app in demo mode."
        )
    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "out.json"
        cmd = [R6_DISSECT_BIN, str(rec_path), "-o", str(out_path)]
        timeout = 60 + _SECONDS_PER_ROUND * num_rounds
        try:
            proc = subprocess.run(
                cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout, creationflags=_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            raise ReplayParseError(f"r6-dissect timed out after {timeout}s on {rec_path.name}.") from None
        except OSError as e:  # e.g. the exe was deleted or quarantined by antivirus
            raise ReplayParseError(f"Couldn't run r6-dissect ({R6_DISSECT_BIN}): {e}") from e
        if proc.returncode != 0:
            label = rec_path.name if rec_path.is_file() else "the match folder"
            raise ReplayParseError(f"r6-dissect failed on {label}: {_ANSI.sub('', proc.stderr).strip()}")
        if not out_path.exists():
            raise ReplayParseError("r6-dissect produced no output file.")
        try:
            return json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:  # ValueError: invalid JSON or text
            raise ReplayParseError(f"r6-dissect's output couldn't be read: {e}") from e


def _extract_name(field: Any, default: str = "") -> str:
    """map / matchType / gamemode all serialize as {"name": ..., "id": ...}."""
    if isinstance(field, dict):
        return field.get("name", default) or default
    if isinstance(field, str) and field:
        return field
    return default


def _display_map_name(name: str) -> str:
    """r6-dissect names reworked maps with a season suffix and no spaces
    ("VillaY10", "KafeDostoyevsky") -> "Villa", "Kafe Dostoyevsky"."""
    if name.startswith("Map("):  # unknown map id, newer than the r6-dissect build
        return name
    name = re.sub(r"Y\d+$", "", name)
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)


_OPERATOR_DISPLAY = {"Capitao": "Capitão", "Jager": "Jäger", "Nokk": "Nøkk", "Tubarao": "Tubarão"}


def _operator_name(player: dict[str, Any]) -> str:
    """A player's operator, as shown in the game: "SolidSnake" -> "Solid Snake", "Jager" -> "Jäger".
    An operator newer than the r6-dissect build ("Operator(4567...)") falls back to the name the
    replay stores for the player's role ("NOOR" -> "Noor")."""
    name = _extract_name(player.get("operator"))
    role = player.get("roleName")
    if name.startswith("Operator(") and isinstance(role, str) and role.isascii() and role.strip():
        return role.strip().title()
    return _OPERATOR_DISPLAY.get(name) or re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)


def _normalize_round(rs: dict[str, Any], idx: int) -> dict[str, Any]:
    teams = (rs.get("teams") or [])[:2]
    winner_team = None
    win_condition = "unknown"
    attack_team = None
    for i, t in enumerate(teams):
        if t.get("won") and winner_team is None:
            winner_team = i
            win_condition = t.get("winCondition") or "unknown"
        if t.get("role") == "Attack":
            attack_team = i

    # The in-game clock counts down and resets when the defuser is planted, so
    # derive a monotonic "elapsed" (seconds since the first event) for trade windows.
    events: list[dict[str, Any]] = []
    elapsed, prev_clock = 0.0, None

    def add(etype: str, clock: float, actor: str | None, **extra: Any) -> None:
        events.append({"type": etype, "time": clock, "elapsed": elapsed, "actor": actor, **extra})

    for fb in rs.get("matchFeedback") or []:
        ftype = _extract_name(fb.get("type"))  # serialized as {"name": ..., "id": ...}
        clock = float(fb.get("timeInSeconds") or 0.0)
        if prev_clock is not None and clock <= prev_clock:
            elapsed += prev_clock - clock
        prev_clock = clock
        actor = fb.get("username") or None
        if ftype == "Kill":
            victim = fb.get("target")
            if actor:
                add("kill", clock, actor, target=victim, headshot=bool(fb.get("headshot")))
            if victim:
                add("death", clock, victim, killed_by=actor)
        elif ftype == "Death" and actor:
            # no attributed killer: fall damage, own gadget, bleed-out...
            add("death", clock, actor, killed_by=None)
        elif ftype == "DefuserPlantComplete":
            add("plant", clock, actor)  # actor is None when the replay doesn't say who
        elif ftype == "DefuserDisableComplete":
            add("defuse", clock, actor)
        # OperatorSwap / Battleye / PlayerLeave / LocateObjective / Other: not needed for metrics

    round_stats = {
        s["username"]: {"assists": s.get("assists", 0)}
        for s in rs.get("stats") or [] if s.get("username")
    }

    return {
        "round_num": rs.get("roundNumber", idx + 1),  # season_stats' dedupe key: keep as-is
        # who was actually in this round -- players leave/rejoin in long matches
        "players": [p["username"] for p in (rs.get("players") or []) if p.get("username")],
        "operators": {
            p["username"]: operator
            for p in (rs.get("players") or [])
            if p.get("username") and (operator := _operator_name(p))
        },
        "winner_team": winner_team,  # None if the replay doesn't record a winner
        "win_condition": win_condition,
        "attack_team": attack_team,
        "site": rs.get("site", ""),
        "events": events,                    # matchFeedback array order == chronological
        "round_stats": round_stats or None,  # r6-dissect's scoreboard assists, if present
    }


def normalize_from_r6_dissect(raw: dict[str, Any]) -> dict[str, Any]:
    """Adapt r6-dissect's JSON into our internal MatchData schema. Handles
    both the multi-round ("rounds": [...]) folder output and the flattened
    single-round-file output (see module docstring)."""
    if isinstance(raw.get("rounds"), list) and raw["rounds"]:
        round_sources = raw["rounds"]
    else:
        round_sources = [raw]

    team_of: dict[str, int] = {}
    operator_histories: dict[str, list[str]] = {}
    team_names = ["Team A", "Team B"]
    for rs in round_sources:
        for i, t in enumerate((rs.get("teams") or [])[:2]):
            name = t.get("name")
            if name:
                team_names[i] = name
        for p in rs.get("players") or []:
            uname = p.get("username")
            if uname and uname not in team_of:
                team_of[uname] = p.get("teamIndex", 0)
            operator = _operator_name(p)
            if uname and operator:
                operator_histories.setdefault(uname, []).append(operator)

    players = [
        {"name": n, "team": t, "operator_history": operator_histories.get(n, [])}
        for n, t in team_of.items()
    ]
    rounds = [_normalize_round(rs, idx) for idx, rs in enumerate(round_sources)]

    last_teams = (round_sources[-1].get("teams") or [{}, {}]) if round_sources else [{}, {}]
    score = [
        last_teams[0].get("score", 0) if len(last_teams) > 0 else 0,
        last_teams[1].get("score", 0) if len(last_teams) > 1 else 0,
    ]
    if score == [0, 0] and rounds:
        # fallback if the "score" field is absent on this r6-dissect version:
        # count rounds won directly from our own winner_team detection above.
        score = [
            sum(1 for r in rounds if r["winner_team"] == 0),
            sum(1 for r in rounds if r["winner_team"] == 1),
        ]

    map_name = _display_map_name(_extract_name(round_sources[0].get("map") if round_sources else None, "Unknown Map"))
    match_id = round_sources[0].get("matchID", "unknown") if round_sources else "unknown"

    return {
        "map": map_name,
        "match_id": match_id,
        "team_names": team_names,
        "final_score": score,
        "players": players,
        "rounds": rounds,
    }


def parse_replay(rec_file_path: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Main entry point: .rec path -> (normalized MatchData, raw JSON).
    The raw JSON is returned too so the UI can offer a debug view if the
    normalized result ever looks wrong again."""
    path = Path(rec_file_path)
    if not path.exists():
        raise ReplayParseError(f"File not found: {rec_file_path}")
    raw = _run_r6_dissect(path)
    return normalize_from_r6_dissect(raw), raw


def _stage_match_folder(paths: list[Path], folder: Path) -> Path:
    """r6-dissect reads a whole match from one folder. Use the rounds' own
    folder when it holds exactly these files; otherwise hard-link (or copy)
    them into `folder`. Symlinks need admin rights on Windows, so they're avoided."""
    parent = paths[0].parent
    if all(p.parent == parent for p in paths) and {p.name for p in parent.glob("*.rec")} == {p.name for p in paths}:
        return parent
    for p in paths:
        dest = folder / p.name
        if dest.exists():
            continue  # the same round twice: keep the first, and never write through a hard link
        try:
            os.link(p, dest)
        except OSError:
            shutil.copyfile(p, dest)
    return folder


def parse_match(rec_paths: list[str]) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Parse a whole match (one .rec per round) -> (MatchData, raw JSON,
    warnings). The files are handed to r6-dissect as one folder, which it
    reads in filename order (R01, R02, ...). If a single corrupt/unsupported
    round makes that fail, each round is parsed on its own instead and the
    bad ones are skipped, so one broken file doesn't lose the whole match."""
    paths = sorted((Path(p) for p in rec_paths), key=lambda p: p.name)
    if not paths:
        raise ReplayParseError("No .rec files to parse.")
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        raise ReplayParseError(f"File(s) not found: {', '.join(missing)}")
    if len(paths) == 1:
        match, raw = parse_replay(str(paths[0]))
        return match, raw, []

    warnings: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        try:
            raw = _run_r6_dissect(_stage_match_folder(paths, Path(td)), num_rounds=len(paths))
            return normalize_from_r6_dissect(raw), raw, warnings
        except (ReplayParseError, json.JSONDecodeError) as e:
            warnings.append(f"Whole-match parse failed, parsing rounds individually. ({e})")

    rounds = []
    for p in paths:
        try:
            rounds.append(_run_r6_dissect(p))
        except (ReplayParseError, json.JSONDecodeError) as e:
            warnings.append(f"Skipped {p.name}: {e}")
    if not rounds:
        raise ReplayParseError("Every round failed to parse:\n" + "\n".join(warnings))
    raw = {"rounds": rounds}
    return normalize_from_r6_dissect(raw), raw, warnings


# ------------------------------------------------------ replay file input --

_ROUND_SUFFIX = re.compile(r"-R\d+$", re.IGNORECASE)


@contextlib.contextmanager
def _batch_checks():
    """Report a batch the scanner refuses as a ReplayParseError."""
    try:
        yield
    except ReplayRejected as e:
        raise ReplayParseError(str(e)) from e


def extract_zip_recs(zf: zipfile.ZipFile, dest_dir: Path, scanner: ReplayScanner | None = None) -> list[str]:
    """Extract only the replays that pass `scanner`, keeping each one's parent folder
    name so a zip holding several match folders doesn't mix their R01, R02, ... up."""
    scanner = scanner or ReplayScanner()
    members = [m for m in zf.infolist() if not m.is_dir()]
    with _batch_checks():
        scanner.check_batch(len(members), sum(m.file_size for m in members))
    paths = []
    for member in members:
        if not scanner.check(member.filename, member.file_size, lambda m=member: zf.open(m)):
            continue
        src = PurePosixPath(member.filename.replace("\\", "/"))
        dest = dest_dir / (src.parent.name or "match") / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as fsrc, open(dest, "wb") as out:
            shutil.copyfileobj(fsrc, out)
        paths.append(str(dest))
    return sorted(paths)


def _open_zip(source, name: str) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(source)
    except zipfile.BadZipFile as e:
        raise ReplayParseError(f"{name} is not a valid zip file ({e}).") from e


def save_uploads(uploaded, workdir: Path, scanner: ReplayScanner | None = None) -> list[str]:
    """.rec paths from uploaded files (Streamlit's UploadedFile, or any BytesIO with
    a .name): zips are extracted like collect_rec_files does, replays are saved.
    Anything that doesn't pass `scanner` is skipped."""
    scanner = scanner or ReplayScanner()
    with _batch_checks():
        scanner.check_batch(len(uploaded), sum(len(up.getbuffer()) for up in uploaded))
    paths = []
    for up in uploaded:
        name = Path(up.name).name
        if name.lower().endswith(".zip"):
            with _open_zip(up, name) as zf:
                paths += extract_zip_recs(zf, workdir / Path(name).stem, scanner)
            continue
        data = up.getbuffer()
        if scanner.check(name, len(data), lambda d=data: io.BytesIO(d)):
            dest = workdir / "uploaded" / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            paths.append(str(dest))
    return paths


def collect_rec_files(path: str | Path, workdir: Path, scanner: ReplayScanner | None = None) -> list[str]:
    """.rec paths from a match folder (searched recursively), a .zip of one or
    more match folders (extracted into `workdir`), or a single .rec file.
    Anything that doesn't pass `scanner` is skipped."""
    scanner = scanner or ReplayScanner()
    p = Path(path)
    if not p.exists():
        raise ReplayParseError(f"Not found: {p}")
    if p.suffix.lower() == ".zip" and p.is_file():
        with _open_zip(p, p.name) as zf:
            return extract_zip_recs(zf, workdir, scanner)
    candidates = [f for f in p.rglob("*.[rR][eE][cC]") if f.is_file()] if p.is_dir() else [p]
    with _batch_checks():
        scanner.check_batch(len(candidates), sum(f.stat().st_size for f in candidates))
    found = sorted(str(f) for f in candidates if scanner.check(f.name, f.stat().st_size, lambda f=f: open(f, "rb")))
    if not found and not p.is_dir():
        raise ReplayParseError(f"{p.name} isn't a Siege replay, a .zip, or a match folder.")
    return found


def group_by_match(rec_paths: list[str]) -> dict[str, list[str]]:
    """Split .rec paths into matches: {"Match-2026-09-23_19-19-11-23660": [R01, R02, ...]}.
    Round files are named <match>-R01.rec; anything else is grouped by its folder. A round
    found twice (a copy of the match folder inside another one) is kept once, from the
    shallowest folder, so it's neither parsed nor counted twice."""
    groups: dict[str, dict[str, str]] = defaultdict(dict)
    for rp in sorted(rec_paths, key=lambda x: (len(Path(x).parts), x)):
        p = Path(rp)
        key = _ROUND_SUFFIX.sub("", p.stem)
        if key == p.stem:  # not a round file name: fall back to the folder
            key = p.parent.name or p.stem
        groups[key].setdefault(p.name, rp)
    return {k: [v[name] for name in sorted(v)] for k, v in sorted(groups.items())}


def replay_source_version(path: Path) -> tuple[float, float]:
    """Changes whenever a replay is added under `path`, so a cached list of its matches can
    be refreshed: its own modified time and, for a folder, that of its newest subfolder
    (a new round in an existing match folder only changes that match's folder, not the
    MatchReplay folder above it)."""
    newest = 0.0
    if path.is_dir():
        for child in path.iterdir():
            with contextlib.suppress(OSError):
                if child.is_dir():
                    newest = max(newest, child.stat().st_mtime)
    return path.stat().st_mtime, newest


_SIEGE_REPLAYS = Path("Tom Clancy's Rainbow Six Siege") / "MatchReplay"


def find_replay_folders() -> list[Path]:
    """MatchReplay folders of Siege installs on this PC: every Steam library
    (from Steam's libraryfolders.vdf) and Ubisoft Connect's default games folder."""
    if sys.platform != "win32":
        return []
    candidates = []
    for program_files in dict.fromkeys(filter(None, (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")))):
        steam = Path(program_files) / "Steam"
        libraries = [steam]
        vdf = steam / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            text = vdf.read_text(encoding="utf-8", errors="ignore")
            libraries += [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', text)]
        candidates += [lib / "steamapps" / "common" / _SIEGE_REPLAYS for lib in libraries]
        candidates.append(Path(program_files) / "Ubisoft" / "Ubisoft Game Launcher" / "games" / _SIEGE_REPLAYS)
    found: list[Path] = []
    for c in candidates:
        if c.is_dir() and not any(c.samefile(f) for f in found):
            found.append(c)

    def latest_match(folder: Path) -> float:
        return max((p.stat().st_mtime for p in folder.iterdir() if p.is_dir()), default=0.0)

    return sorted(found, key=latest_match, reverse=True)  # most recently played first


def load_demo_match() -> dict[str, Any]:
    """Loads the bundled synthetic sample match (see sample_data.py)."""
    from sample_data import SAMPLE_MATCH
    return SAMPLE_MATCH


def raw_shape_preview(raw: dict[str, Any], max_items: int = 3) -> dict[str, Any]:
    """Small, safe-to-render summary of the raw parser JSON for a debug
    panel -- top-level keys plus a peek at the first round's shape, so a
    schema mismatch can be diagnosed from the UI instead of a screenshot."""
    is_multi = bool(isinstance(raw.get("rounds"), list) and raw["rounds"])
    first_round = raw["rounds"][0] if is_multi else raw
    if not isinstance(first_round, dict):
        first_round = {}
    # r6-dissect can emit null for list fields, so `or []` rather than a .get() default
    players = first_round.get("players") or []
    feedback = first_round.get("matchFeedback") or []
    return {
        "top_level_keys": sorted(raw.keys()),
        "shape": "multi-round (folder)" if is_multi else "single-round (file)",
        "num_rounds": len(raw["rounds"]) if is_multi else 1,
        "first_round_keys": sorted(first_round.keys()),
        "map_field": first_round.get("map"),
        "num_players": len(players),
        "num_matchFeedback": len(feedback),
        "sample_matchFeedback": feedback[:max_items],
        "has_stats": bool(first_round.get("stats")),
    }
