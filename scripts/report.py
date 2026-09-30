"""
report.py
=========
The "Match report" page: load a match's replay and show an R6 Pro League-style
scoreboard for every player, a round-by-round breakdown, and CSV/JSON exports.
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path

import streamlit as st

from app_info import APP_NAME, APP_VERSION, NOTICE, is_public_host, is_windows_app
from metrics_engine import (
    PRO_LEAGUE_COLUMNS, SIDE_ICONS, SIDE_NAMES, compute_match_metrics, leaderboard_rows, pro_league_rows,
    round_rows, rows_csv, scoreboard_text, side_split, team_side, win_condition_label,
)
from parser import (
    ReplayParseError, find_replay_folders, load_demo_match, r6_dissect_available, raw_shape_preview, save_uploads,
)
from season_stats import GENERIC_TEAM_NAMES, StatsManager
from sources import (
    can_read_local_files, folder_source, load_source, match_label, match_time, open_stats_db, parse,
    start_workdir_sweeper,
)
from ui import md

REPO_ROOT = Path(__file__).resolve().parent.parent
REPLAYS_DIR = REPO_ROOT / "replays"

UPLOAD = "Upload"
FOLDER = "Folder or zip on this computer"
REPLAYS_FOLDER = "From the replays/ folder"


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


def side_badge(side: str | None) -> str:
    """"⚔ ATTACK" in orange or "♜ DEFENSE" in blue, R6 broadcast colors."""
    if side not in SIDE_ICONS:
        return '<span class="side unknown">—</span>'
    return f'<span class="side {side}"><span class="ico">{SIDE_ICONS[side]}</span>{SIDE_NAMES[side]}</span>'


def rounds_html(match: dict) -> str:
    """Every round of the match: the side each team played, who won and how, and the site."""
    names = match["team_names"][:2]
    head = "".join(f"<th>{html.escape(c)}</th>" for c in ("Round", *names, "How it was won", "Site"))
    body = []
    for number, rnd in enumerate(match["rounds"], 1):
        cells = [f"<td>{number}</td>"]
        for team in range(len(names)):
            won = '<span class="won">WIN</span>' if rnd.get("winner_team") == team else ""
            cells.append(f"<td>{side_badge(team_side(team, rnd.get('attack_team')))}{won}</td>")
        how = win_condition_label(rnd.get("win_condition")) or "—"
        cells.append(f"<td>{html.escape(how)}</td>")
        cells.append(f'<td class="left">{html.escape(rnd.get("site") or "—")}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (f'<div class="pl-wrap"><table class="pl rounds"><caption>Rounds</caption>'
            f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>")


def player_rounds_html(player: str, breakdown: list, round_numbers: dict[int, int]) -> str:
    """One player's rounds: side, operator, whether their team won, and what they did."""
    head = "".join(f"<th>{c}</th>" for c in ("Round", "Side", "Operator", "Result", "Performance"))
    body = []
    for i, rb in enumerate(breakdown, 1):
        result = {True: '<span class="pos">Won</span>', False: '<span class="neg">Lost</span>'}.get(rb.won, "—")
        body.append(
            f"<tr><td>{round_numbers.get(rb.round_num, i)}</td><td>{side_badge(rb.side)}</td>"
            f"<td>{html.escape(rb.operator or '—')}</td><td>{result}</td>"
            f'<td class="left">{"🟢" if rb.survived else "🔴"} {html.escape(rb.summary())}</td></tr>'
        )
    return (f'<div class="pl-wrap"><table class="pl rounds"><caption>{html.escape(player)}</caption>'
            f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>")


def side_split_html(breakdown: list) -> str:
    """"⚔ ATTACK 5 rounds · 3 won · 6-4 K-D   ♜ DEFENSE ..." for one player."""
    parts = [
        f'<span>{side_badge(side)} <b>{s["rounds"]}</b> round{"s" if s["rounds"] != 1 else ""} · '
        f'<b>{s["won"]}</b> won · <b>{s["kills"]}-{s["deaths"]}</b> K-D</span>'
        for side, s in side_split(breakdown).items()
    ]
    return f'<div class="side-split">{"".join(parts)}</div>' if parts else ""


start_workdir_sweeper()
local_files = can_read_local_files()
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
    state = None
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
            state = load_source(sig, lambda td, sc, u=uploaded: save_uploads(u, td, sc))
    elif source == FOLDER:
        found = find_replay_folders()
        # found automatically: the folder box stays out of the way; otherwise it's the first thing to fill in
        box = st.expander("Replay folder", expanded=not found) if found else st.container()
        with box:
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
                state = folder_source(p)
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
            state = folder_source(chosen)

    if state is not None:
        if state["skipped"]:
            st.warning(state["skipped"], icon="🛡️")
        if "error" in state:
            st.error(state["error"])
            st.stop()
        names = sorted(state["groups"], key=lambda n: match_time(n) or n, reverse=True)  # newest first
        with open_stats_db() as db:
            known = {r["source"]: r for r in db.match_list(db.me())}
        opening = st.session_state.pop("open_match", None)  # "Open" on Match History
        if len(names) > 1:
            name = st.selectbox(f"{len(names)} matches", names, format_func=lambda n: match_label(n, known.get(n)),
                                index=names.index(opening) if opening in names else 0)
        else:
            name = names[0]
        if name not in state["parsed"]:
            with st.spinner("Reading the match... long matches can take a few seconds."):
                parse(state, name)
        result = state["parsed"][name]
        if isinstance(result, ReplayParseError):
            st.error(f"{name}: {result}")
            st.stop()
        match, raw, parse_warnings = result
        with open_stats_db() as db:  # every match looked at goes into the stats database
            if db.needs_import({name: state["groups"][name]}):
                db.import_match(name, match, files=len(state["groups"][name]))
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
    # r6_season is plain state, not the widget's key: Streamlit drops a widget's state when
    # another page is shown, and the other pages read the season from it
    tracker_season = st.text_input(
        "Season", value=st.session_state.get("r6_season", "current"), key="r6_season_input"
    ).strip() or "current"
    st.session_state["r6_season"] = tracker_season
    available_teams = team_names[:2]
    selected_team_index = st.selectbox("Roster team", range(len(available_teams)),
                                       format_func=lambda i: available_teams[i], key="r6_tracker_team")
    selected_team = available_teams[selected_team_index]
    player_names = [
        player["name"] for player in match.get("players", [])
        if player.get("team") == selected_team_index
    ]
    # keyed by match and team, so switching either starts from that team's players and name
    # (with fixed keys, the name box kept the other team's name and the list came up empty)
    roster_key = f"{match['match_id']}:{selected_team_index}"
    selected_players = st.multiselect(
        "Players to track", player_names, default=player_names, key=f"r6_tracker_players:{roster_key}"
    )
    generic = selected_team.strip().upper() in GENERIC_TEAM_NAMES
    tracked_team = st.text_input(
        "Team or school name", value="" if generic else selected_team, key=f"r6_tracker_team_name:{roster_key}",
        placeholder="e.g. Varsity" if generic else None,
        help=f'The replay only calls this team "{selected_team}", so enter its real name.' if generic else None,
    ).strip()
    if tracked_team.upper() in GENERIC_TEAM_NAMES:
        tracked_team = ""  # never save a replay's generic label as a team: it'd lump opponents together
    if is_public_host():
        st.info("Season tracking is disabled on shared public hosting to keep visitors' stats separate. Use the Windows app or a private local deployment.")
    with StatsManager(season=tracker_season) as tracker:
        track_column, log_column = st.columns(2)
        if track_column.button("Track selected roster", disabled=not selected_players or is_public_host(), type="primary"):
            tracker.add_players(selected_players, team=tracked_team or None)
            st.success(f"Tracking {len(selected_players)} players for {md(tracked_team)}." if tracked_team else
                       f"Tracking {len(selected_players)} players, without a team name: enter one to group them as a team.")
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
    "score": score, "players": rows, "rounds": round_rows(match, stats)},
    indent=2, ensure_ascii=False).encode("utf-8"),
    file_name=f"{match['match_id']}_stats.json", mime="application/json")
c3.download_button("⬇ TXT", (scoreboard_text(match, rows) + "\n").encode("utf-8"),
                   file_name=f"{match['match_id']}_stats.txt", mime="text/plain")

# ------------------------------------------------------------ breakdown ---
st.subheader("Round-by-round")
st.markdown(rounds_html(match), unsafe_allow_html=True)
player = st.selectbox("Player", [r["Player"] for r in rows], key="r6_round_player")
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
# numbered by play order, like the round files (r6-dissect counts rounds from 0)
round_numbers = {rnd["round_num"]: i for i, rnd in enumerate(match["rounds"], 1)}
st.markdown(side_split_html(s.round_breakdown) + player_rounds_html(player, s.round_breakdown, round_numbers),
            unsafe_allow_html=True)

with st.expander("Stat definitions"):
    st.markdown(
        "- **⚔︎ Attack / ♜ Defense**: the side the player's team played that round. "
        "**Operator**: who they picked that round.\n"
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
