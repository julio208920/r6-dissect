"""Team analytics: build a roster from usernames and add up its stats across the
loaded replays, and the saved season team totals."""

from __future__ import annotations

import contextlib
import json
import os

import streamlit as st

from app_info import is_public_host
from metrics_engine import pro_league_rows, rows_csv
from parser import ReplayParseError, parse_match, parse_replay
from roster import ROSTER_SIZE, Roster, find_roster_matches, players_from_round, roster_report
from season_stats import StatsManager


def _fmt_eps(eps: int | None) -> str:
    return "—" if eps is None else str(eps)


st.title("Team Analytics")
build_tab, season_tab = st.tabs(["Build a team", "Season teams"])

# ------------------------------------------------------------ build a team --
with build_tab:
    st.caption("Enter a team name and its players' in-game usernames. Every loaded match those players "
               "played together is found, and each player's stats are added up across them.")
    saved = st.session_state.get("r6_roster") or {"team": "", "players": [""] * ROSTER_SIZE}
    with st.form("roster_form"):
        team_name = st.text_input("Team name", value=saved["team"], placeholder="e.g. Varsity")
        columns = st.columns(ROSTER_SIZE)
        typed = [col.text_input(f"Player {i + 1}", value=saved["players"][i], placeholder="Username")
                 for i, col in enumerate(columns)]
        min_players = st.slider("Count a match when at least this many of them were on the same team",
                                1, ROSTER_SIZE, 3)
        submitted = st.form_submit_button("Find their matches", type="primary")
    if submitted:
        st.session_state["r6_roster"] = {"team": team_name, "players": typed}

    roster = Roster.from_input(team_name, typed)
    source = st.session_state.get("source")
    if not submitted:
        pass
    elif not roster.team or not roster.players:
        st.error("Enter a team name and at least one username.")
    elif not source or not source.get("groups"):
        st.info("First load your replays on **Dashboard**: your whole MatchReplay folder, or a zip of "
                "several matches. This page uses the matches loaded there.")
    else:
        with contextlib.suppress(OSError, KeyError):
            os.utime(source["workdir"])  # in use: keep Dashboard's hourly cleanup from deleting uploads
        groups = source["groups"]
        firsts = source.setdefault("players", {})  # match name -> {username: team}, from its first round
        parsed = source.setdefault("parsed", {})    # shared with Dashboard

        def players_of(name: str, recs: list[str]) -> dict[str, int]:
            if name not in firsts:
                try:
                    firsts[name] = players_from_round(parse_replay(recs[0])[1])
                except (ReplayParseError, ValueError):
                    firsts[name] = {}
            return firsts[name]

        def parse(name: str, recs: list[str]) -> dict | None:
            if name not in parsed:
                try:
                    parsed[name] = parse_match(recs)
                except ReplayParseError as e:
                    parsed[name] = e
            result = parsed[name]
            return None if isinstance(result, ReplayParseError) else result[0]

        with st.spinner(f"Looking through {len(groups)} matches..."):
            found = find_roster_matches(groups, roster, min_players, players_of, parse)
        st.session_state["r6_roster_report"] = roster_report(roster, found)

    report = st.session_state.get("r6_roster_report")
    if report is not None:
        if not report.matches:
            st.warning(f"None of the loaded matches had {min_players}+ of {report.roster.team}'s players "
                       "on the same team. Check the spelling of the usernames, or lower the number above.")
        else:
            wins, losses = report.record
            m = st.columns(4)
            m[0].metric("Matches", len(report.matches))
            m[1].metric("Record", f"{wins}-{losses}")
            m[2].metric("Team EPS", _fmt_eps(report.team_eps))
            m[3].metric("Rounds", sum(len(rm.match["rounds"]) for rm in report.matches))
            if report.missing:
                st.warning(f"Not found in those matches: {', '.join(report.missing)}. Check the spelling.")
            rows = pro_league_rows(report.players)
            by_name = {s.name: typed for typed, s in report.players.items()}
            table = [{"Player": r["Player"], "Matches": report.matches_played[by_name[r["Player"]]],
                      **{k: v for k, v in r.items() if k not in ("Team", "Player")}} for r in rows]
            st.subheader(f"{report.roster.team}: combined player stats")
            st.dataframe(table, hide_index=True)
            st.caption("Only stats from playing on this team count: a match where a player was on the other "
                       "side isn't included for them. EPS is the rounds-weighted average of their per-match EPS.")
            st.subheader("Matches")
            st.dataframe([{
                "Match": rm.name, "Map": rm.match.get("map", ""),
                "Score": "{}-{}".format(rm.match["final_score"][rm.side], rm.match["final_score"][1 - rm.side]),
                "Result": {True: "Win", False: "Loss", None: "Draw"}[rm.won],
                "Players": ", ".join(rm.present),
            } for rm in report.matches], hide_index=True)
            dl, track = st.columns([1, 2])
            dl.download_button("⬇ CSV", rows_csv(table).encode("utf-8"),
                               file_name=f"{report.roster.team}_team_stats.csv", mime="text/csv")
            if not is_public_host() and track.button(f"Track {report.roster.team} for the season"):
                with StatsManager(season=st.session_state.get("r6_season", "current")) as manager:
                    manager.add_players(report.roster.players, team=report.roster.team)
                st.success(f"Tracking {len(report.roster.players)} players as {report.roster.team}. "
                           "Save matches from Dashboard to add them to the season.")

# ------------------------------------------------------------ season teams --
with season_tab:
    season = st.text_input("Season", value=st.session_state.get("r6_season", "current"), key="team_season").strip() or "current"
    st.session_state["r6_season"] = season
    with StatsManager(season=season) as manager:
        teams = [t for t in (manager.get_team_stats(n) for n in manager.teams()) if t]
        snapshot = manager.export_json()

    if not teams:
        st.info("No team totals yet. Track a roster and save a match from Dashboard, or import a school roster first.")
    else:
        selected = st.selectbox("Team", [t.team for t in teams])
        team = next(t for t in teams if t.team == selected)
        metric_columns = st.columns(6)
        metric_columns[0].metric("Rounds", team.totals["rounds_played"])
        metric_columns[1].metric("EPS", _fmt_eps(team.eps))
        metric_columns[2].metric("K/D", f"{team.kd:.2f}")
        metric_columns[3].metric("Entry +/-", f"{team.entry_diff:+d}")
        metric_columns[4].metric("KOST avg", f"{team.kost_avg:.1f}%")
        metric_columns[5].metric("Clutch success", "—" if team.clutch_success_rate is None else f"{team.clutch_success_rate:.0%}")
        st.subheader("Roster performance")
        st.dataframe([{
            "Player": player.username,
            "EPS": _fmt_eps(player.eps),
            "Rounds": player.totals["rounds_played"],
            "K / D / A": f"{player.totals['kills']} / {player.totals['deaths']} / {player.totals['assists']}",
            "K/D": round(player.kd, 2),
            "Entry +/-": player.entry_diff,
            "KOST": f"{player.kost_pct:.1f}%",
            "HS": f"{player.hs_pct:.1f}%",
            "Clutches": player.clutches_won,
        } for player in team.member_stats], hide_index=True)
        st.subheader("Season teams")
        st.dataframe([{
            "Team": t.team,
            "EPS": _fmt_eps(t.eps),
            "Players": len(t.players),
            "Rounds": t.totals["rounds_played"],
            "Kills": t.totals["kills"],
            "Deaths": t.totals["deaths"],
            "K/D": round(t.kd, 2),
            "Entry +/-": t.entry_diff,
            "KOST": f"{t.kost_avg:.1f}%",
        } for t in teams], hide_index=True)
        st.caption("EPS is the rounds-weighted average of each player's per-match EPS. "
                   "Matches saved before EPS was recorded show —.")
        st.download_button(
            "Export season report",
            json.dumps(snapshot, indent=2).encode("utf-8"),
            file_name=f"{season}_team_report.json",
            mime="application/json",
        )
