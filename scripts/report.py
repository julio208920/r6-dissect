"""
report.py
=========
The "Match report" page: load a match's replay and show an R6 Pro League-style
scoreboard for every player, a round-by-round breakdown, and CSV/JSON exports.
"""

from __future__ import annotations

import contextlib
import html
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

import streamlit as st

from app_info import APP_NAME, APP_VERSION, NOTICE, is_loopback, is_public_host, is_windows_app
from file_guard import ReplayScanner
from metrics_engine import (
    PRO_LEAGUE_COLUMNS, compute_match_metrics, leaderboard_rows, pro_league_rows, rows_csv, scoreboard_text,
)
from parser import (
    ReplayParseError, collect_rec_files, find_replay_folders, group_by_match, load_demo_match,
    parse_match, r6_dissect_available, raw_shape_preview, save_uploads,
)
from season_stats import StatsManager

REPO_ROOT = Path(__file__).resolve().parent.parent
REPLAYS_DIR = REPO_ROOT / "replays"

UPLOAD = "Upload"
FOLDER = "Folder or zip on this computer"
REPLAYS_FOLDER = "From the replays/ folder"


WORKDIR_PREFIX = "r6-match-"
WORKDIR_MAX_IDLE = 3600  # seconds; extracted replays are deleted after an hour unused


def _sweep_idle_workdirs() -> None:
    """Delete extracted replays nobody has used for an hour, so uploads don't pile
    up on a server (a visitor leaving the page never tells us)."""
    cutoff = time.time() - WORKDIR_MAX_IDLE
    for d in Path(tempfile.gettempdir()).glob(WORKDIR_PREFIX + "*"):
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


@st.cache_resource(show_spinner=False)
def _start_workdir_sweeper() -> None:
    """Sweep idle workdirs every 10 minutes for as long as this server runs, even
    when nobody's visiting. Started once per server process."""
    def sweep_forever() -> None:
        while True:
            time.sleep(600)
            _sweep_idle_workdirs()

    threading.Thread(target=sweep_forever, name="workdir-sweeper", daemon=True).start()


def _load_source(sig, collect) -> dict:
    """Find the matches in a source once per source: collect(workdir, scanner) -> .rec
    paths. Zips/uploads are extracted into a workdir that lives as long as the source
    is selected (and is in use), so each match can be parsed only when it's picked."""
    state = st.session_state.get("source")
    if state and state["sig"] == sig:
        with contextlib.suppress(OSError):
            os.utime(state["workdir"])  # still in use: keep it from being swept
        return state
    if state:
        shutil.rmtree(state["workdir"], ignore_errors=True)
    _sweep_idle_workdirs()
    workdir = tempfile.mkdtemp(prefix=WORKDIR_PREFIX)
    scanner = ReplayScanner()
    state = {"sig": sig, "workdir": workdir, "parsed": {}}
    try:
        state["groups"] = group_by_match(collect(Path(workdir), scanner))
        if not state["groups"]:
            state["error"] = "No Siege replay files found."
    except ReplayParseError as e:
        state["error"] = str(e)
    state["skipped"] = scanner.summary()
    st.session_state["source"] = state
    return state


def _signed_cell(text: str) -> str:
    """Color the "(+4)" / "(-2)" part of a KD or Entry cell."""
    text = html.escape(text)
    if "(+" in text:
        return text.replace("(+", '<span class="pos">(+').replace(")", ")</span>")
    if "(-" in text:
        return text.replace("(-", '<span class="neg">(-').replace(")", ")</span>")
    return text


def scoreboard_html(team_name: str, won: bool, rows: list[dict]) -> str:
    head = "".join(f"<th>{html.escape(c)}</th>" for c in ("Player",) + PRO_LEAGUE_COLUMNS)
    body = []
    for r in rows:
        cells = [f"<td>{html.escape(r['Player'])}</td>", f'<td class="eps">{r["EPS"]}</td>']
        for c in PRO_LEAGUE_COLUMNS[1:]:
            v = str(r[c])
            cells.append(f"<td>{_signed_cell(v) if c in ('KD (+/-)', 'Entry') else html.escape(v)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    badge = '<span class="won">WIN</span>' if won else ""
    return (f'<div class="pl-wrap"><table class="pl"><caption>{html.escape(team_name)}{badge}</caption>'
            f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>")


_start_workdir_sweeper()

# Reading folders on disk only makes sense, and is only safe, when the visitor is
# on the machine running the app -- never on the public website.
local_files = not is_public_host() and is_loopback(st.context.ip_address)
if not local_files:
    sources = [UPLOAD]
elif is_windows_app():
    sources = [FOLDER, UPLOAD]
else:
    sources = [FOLDER, UPLOAD, REPLAYS_FOLDER]

# ------------------------------------------------------------- sidebar ----
with st.sidebar:
    st.caption("Drop in a match replay for an esports-style scoreboard of every player.")
    if not r6_dissect_available():
        st.warning("r6-dissect not found, so real replays can't be parsed. "
                   "See the README to build it, or use the demo match below.", icon="⚠️")
    demo_mode = st.toggle("Use demo match (no file needed)", value=not r6_dissect_available())
    st.divider()
    st.caption("EPS · KD (+/-) · Entry · KOST · KPR · HS · SRV · Clutches · Multikills · "
               "Objectives · Dead for trade kill · Trade kills")
    st.caption(f"{APP_NAME} {APP_VERSION}")
    st.caption(NOTICE)

st.title("Dashboard")

# ------------------------------------------------------------- input -------
match = raw = None
parse_warnings: list[str] = []

if demo_mode:
    match = load_demo_match()
    st.caption("Showing the bundled demo match. Turn off demo mode in the sidebar to load a real replay.")
else:
    source = sources[0]
    if len(sources) > 1:
        source = st.radio(
            "Replay source", sources, horizontal=True,
            help="On GitHub Codespaces, browser uploads over ~50 MB fail with HTTP 413; "
                 "put big matches in replays/ instead." if os.environ.get("CODESPACES") else None,
        )
    picked = None  # (cache signature, collect(tempdir) -> .rec paths)
    if source == UPLOAD:
        uploaded = st.file_uploader(
            "Drop the match's .zip (or every .rec file from the match folder)",
            type=["zip", "rec"], accept_multiple_files=True,
        )
        if not local_files:
            st.caption("Your replays are in the game's `MatchReplay` folder, one folder per match. "
                       "Right-click a match folder, choose **Send to > Compressed (zipped) folder**, "
                       "and upload that zip. Prefer not to upload? Get the Windows app, which "
                       "reads the folder directly.")
        if uploaded:
            sig = ("upload",) + tuple((u.name, u.size, u.file_id) for u in uploaded)
            picked = (sig, lambda td, sc, u=uploaded: save_uploads(u, td, sc))
    elif source == FOLDER:
        found = find_replay_folders()
        typed = st.text_input(
            "Path to a match folder, a .zip, or your whole MatchReplay folder",
            value=str(found[0]) if found else "",
            placeholder=r"C:\Program Files (x86)\Steam\steamapps\common\Tom Clancy's Rainbow Six Siege\MatchReplay",
        ).strip().strip('"')
        if found and typed == str(found[0]):
            st.caption("Found your Siege replays folder automatically.")
        if typed:
            p = Path(typed).expanduser()
            if not p.exists():
                st.error(f"Not found: {p}")
            else:
                picked = (("path", str(p), p.stat().st_mtime), lambda td, sc, c=p: collect_rec_files(c, td, sc))
    else:
        REPLAYS_DIR.mkdir(exist_ok=True)
        choices = sorted(
            [p for p in REPLAYS_DIR.iterdir()
             if (p.is_dir() and any(p.rglob("*.rec"))) or p.suffix.lower() in (".zip", ".rec")],
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        st.caption(f"Copy a match folder or its `.zip` into `{REPLAYS_DIR}`, then pick it here.")
        if not choices:
            st.info(f"No matches in `{REPLAYS_DIR}` yet.")
        else:
            chosen = st.selectbox("Match", choices, format_func=lambda p: p.name + ("/" if p.is_dir() else ""))
            picked = (("path", str(chosen), chosen.stat().st_mtime), lambda td, sc, c=chosen: collect_rec_files(c, td, sc))

    if picked is not None:
        state = _load_source(*picked)
        if state["skipped"]:
            st.warning(state["skipped"], icon="🛡️")
        if "error" in state:
            st.error(state["error"])
            st.stop()
        names = list(state["groups"])
        if len(names) > 1:
            name = st.selectbox(f"{len(names)} matches found", names, index=len(names) - 1)
        else:
            name = names[0]
        if name not in state["parsed"]:
            with st.spinner(f"Parsing {name}... long matches can take a minute."):
                try:
                    state["parsed"][name] = parse_match(state["groups"][name])
                except ReplayParseError as e:
                    state["parsed"][name] = e
        result = state["parsed"][name]
        if isinstance(result, ReplayParseError):
            st.error(f"{name}: {result}")
            st.stop()
        match, raw, parse_warnings = result
        for w in parse_warnings:
            st.warning(w, icon="⚠️")
        with st.sidebar:
            with st.expander("🔍 Parser debug info"):
                st.json(raw_shape_preview(raw))

if match is None:
    st.info("Load a replay above, or turn on the demo match in the sidebar.")
    st.stop()

# ------------------------------------------------------------ compute ------
stats = compute_match_metrics(match)
rows = pro_league_rows(stats)
team_names = match["team_names"]
score = match["final_score"]
st.session_state["r6_last_match"] = match

if not stats:
    st.warning("This replay has no player data (it may be a practice session or a match "
               "that ended before it started).", icon="⚠️")
    st.stop()
if not any(s.kills for s in stats.values()):
    st.warning("Parsed, but no kills were found. Expand **Parser debug info** in the sidebar "
               "to see what r6-dissect returned.", icon="⚠️")

top_player = max(stats.values(), key=lambda player: (player.eps, player.kills))
snapshot_columns = st.columns(4)
snapshot_columns[0].metric("Rounds", len(match["rounds"]))
snapshot_columns[1].metric("Match score", f"{score[0]} : {score[1]}")
snapshot_columns[2].metric("Top EPS", top_player.eps)
snapshot_columns[3].metric("Top performer", top_player.name)

# ------------------------------------------------------------ scorecard ---
st.markdown(
    f'<div class="scorecard">'
    f'<div class="team-name">{html.escape(team_names[0])}</div>'
    f'<div style="text-align:center"><span class="score-big">{score[0]}</span>'
    f'<span style="color:#8b949e;font-size:1.6rem"> : </span><span class="score-big">{score[1]}</span><br>'
    f'<span class="map-pill">{html.escape(match["map"])} · {len(match["rounds"])} round{"s" if len(match["rounds"]) != 1 else ""}</span></div>'
    f'<div class="team-name" style="text-align:right">{html.escape(team_names[1])}</div>'
    f'</div>', unsafe_allow_html=True)

# ------------------------------------------------------------ scoreboards -
for team_idx, team_name in enumerate(team_names[:2]):
    team_rows = [r for r in rows if r["Team"] == team_idx]
    if team_rows:
        won = score[team_idx] > score[1 - team_idx]
        st.markdown(scoreboard_html(team_name, won, team_rows), unsafe_allow_html=True)

with st.expander("Season tracker", expanded=False):
    tracker_season = st.text_input(
        "Season", value=st.session_state.get("r6_season", "current"), key="r6_season"
    ).strip() or "current"
    available_teams = team_names[:2]
    selected_team = st.selectbox("Roster team", available_teams, key="r6_tracker_team")
    selected_team_index = available_teams.index(selected_team)
    player_names = [
        player["name"] for player in match.get("players", [])
        if player.get("team") == selected_team_index
    ]
    selected_players = st.multiselect(
        "Players to track", player_names, default=player_names, key="r6_tracker_players"
    )
    tracked_team = st.text_input("Team or school name", value=selected_team, key="r6_tracker_team_name").strip()
    if is_public_host():
        st.info("Season tracking is disabled on shared public hosting to keep visitors' stats separate. Use the Windows app or a private local deployment.")
    with StatsManager(season=tracker_season) as tracker:
        track_column, log_column = st.columns(2)
        if track_column.button("Track selected roster", disabled=not selected_players or is_public_host(), type="primary"):
            tracker.add_players(selected_players, team=tracked_team or selected_team)
            st.success(f"Tracking {len(selected_players)} players for {tracked_team or selected_team}.")
        tracked = tracker.tracked_players()
        if log_column.button("Save this match", disabled=not tracked or is_public_host()):
            result = tracker.log_match(match)
            if result.rounds_logged:
                st.success(f"Saved {result.rounds_logged} player-rounds for {tracker_season}.")
            else:
                st.info("All tracked player-rounds from this match were already saved.")
            for warning in result.warnings:
                st.warning(warning)
        st.caption(f"{len(tracked)} players tracked in {tracker_season}. Re-importing a match never counts a round twice.")

c1, c2, c3, _ = st.columns([1, 1, 1, 3])
c1.download_button("⬇ CSV", rows_csv([{"Player": r["Player"], "Team Name": team_names[r["Team"]], **r}
                                       for r in leaderboard_rows(stats)]).encode("utf-8"),
                   file_name=f"{match['match_id']}_stats.csv", mime="text/csv")
c2.download_button("⬇ JSON", json.dumps({
    "map": match["map"], "match_id": match["match_id"], "teams": team_names,
    "score": score, "players": rows}, indent=2, ensure_ascii=False).encode("utf-8"),
    file_name=f"{match['match_id']}_stats.json", mime="application/json")
c3.download_button("⬇ TXT", (scoreboard_text(match, rows) + "\n").encode("utf-8"),
                   file_name=f"{match['match_id']}_stats.txt", mime="text/plain")

# ------------------------------------------------------------ breakdown ---
st.subheader("Round-by-round")
player = st.selectbox("Player", [r["Player"] for r in rows])
s = stats[player]
for col, (label, value) in zip(st.columns(3) + st.columns(3), (
    ("EPS", s.eps),
    ("K-D-A", f"{s.kills}-{s.deaths}-{s.assists}"),
    ("Entry K-D", f"{s.entry_kills}-{s.entry_deaths}"),
    ("KOST", f"{s.kost_pct:.0f}%"),
    ("Plants-Defuses", f"{s.plants}-{s.defuses}"),
    ("Traded-Trade kills", f"{s.trades}-{s.trade_kills}"),
)):
    col.metric(label, value)
for i, rb in enumerate(s.round_breakdown, 1):
    st.markdown(f"**{'🟢' if rb.survived else '🔴'} Round {i}** — {rb.summary()}")

with st.expander("Stat definitions"):
    st.markdown(
        "- **EPS**: performance score centered on 100 (match average). Ubisoft hasn't published "
        "its EPS formula; this one combines KPR, deaths, KOST, entry differential, multikills, "
        "clutches, objectives and trade kills, weighted against everyone in this match.\n"
        "- **KD (+/-)**: kills-deaths (difference). **Entry**: opening kills-opening deaths.\n"
        "- **KOST**: % of rounds with a Kill, Objective, Survival or Traded death. "
        "**KPR**: kills per round. **HS**: headshot kills %. **SRV**: % of rounds survived.\n"
        "- **Clutches**: rounds won as the team's last player alive vs 1+ enemies. "
        "**Multikills**: rounds with 2+ kills.\n"
        "- **Objectives**: defuser plants + disables.\n"
        "- **Dead for trade kill**: deaths a teammate avenged within 10 s. "
        "**Trade kills**: kills that avenged a teammate within 10 s."
    )
