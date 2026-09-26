"""Team analytics: build a team from player names and add up its stats across every match it
played (from the stats database), and the season tracker's team totals."""

from __future__ import annotations

import json
import re

import streamlit as st

from app_info import is_public_host
from ask_engine import team_report
from metrics_engine import pro_league_row, rows_csv
from season_stats import StatsManager
from sources import current_source, match_label, open_stats_db, sync_with_progress
from stats_db import nice_time
from ui import md

ROSTER_SIZE = 5
NEW = "New team"


def _fmt_eps(eps: int | None) -> str:
    return "—" if eps is None else str(eps)


def _names(choice: str) -> list[str]:
    """The player names typed into the form for `choice`, without blanks or repeats (any case)."""
    seen: dict[str, str] = {}
    for i in range(ROSTER_SIZE):
        name = st.session_state.get(f"roster_{choice}_{i}", "").strip()
        if name and name.casefold() not in seen:
            seen[name.casefold()] = name
    return list(seen.values())


def _save_team(choice: str) -> None:
    team = st.session_state.get(f"team_name_{choice}", "").strip()
    names = _names(choice)
    if not team or not names:
        st.session_state["team_error"] = "Enter a team name and at least one player."
        return
    with open_stats_db() as db:
        db.save_roster(team, names)
    st.session_state["team_shown"] = (team, st.session_state.get(f"roster_min_{choice}", 3))
    st.session_state["team_choice"] = team  # the saved team is what's shown and selected now


def _delete_team(team: str) -> None:
    with open_stats_db() as db:
        db.delete_roster(team)
    st.session_state["team_choice"] = NEW
    st.session_state.pop("team_shown", None)


st.title("Team Analytics")
build_tab, season_tab = st.tabs(["Build a team", "Season teams"])

# ------------------------------------------------------------ build a team --
with build_tab:
    st.caption("Pick up to five players. Every match where enough of them played on the same side is found, "
               "and each player's stats are added up across those matches. Teams you build are saved, and "
               "**Ask** understands their names.")
    with open_stats_db() as db:
        source = current_source()
        if source and "error" not in source:
            sync_with_progress(db, source)
        has_matches = db.summary()["matches"] > 0
        me = db.me()
        teams = db.rosters()
        mates = [name for name, _ in db.teammates(me, limit=ROSTER_SIZE - 1)] if me else []

    if not has_matches:
        st.info("No matches yet. Open your replays on **Dashboard** (or upload them there) first.")
    else:
        if st.session_state.get("team_choice") not in [NEW, *teams]:
            st.session_state["team_choice"] = NEW
        choice = st.selectbox("Team", [NEW, *teams], key="team_choice") if teams else NEW
        # a new team starts as you and the players you've played with most
        name, players = ("", [me, *mates] if me else []) if choice == NEW else (choice, teams[choice])
        players = (players + [""] * ROSTER_SIZE)[:ROSTER_SIZE]
        with st.form(f"roster_form_{choice}"):
            st.text_input("Team name", value=name, placeholder="e.g. Varsity", key=f"team_name_{choice}")
            columns = st.columns(ROSTER_SIZE)
            for i, col in enumerate(columns):
                col.text_input(f"Player {i + 1}", value=players[i], placeholder="Username", key=f"roster_{choice}_{i}")
            st.slider("Count a match when at least this many of them were on the same side", 1, ROSTER_SIZE, 3,
                      key=f"roster_min_{choice}")
            st.form_submit_button("Show team stats", type="primary", on_click=_save_team, args=(choice,))
        if error := st.session_state.pop("team_error", None):
            st.error(error)
        if choice != NEW:
            st.button(f"Delete {md(choice)}", on_click=_delete_team, args=(choice,), type="tertiary")

        shown = st.session_state.get("team_shown")
        if shown and shown[0] in teams:
            with open_stats_db() as db:
                report = team_report(db, *shown)
            team, need = shown
            if not report["matches"]:
                st.warning(f"No match had {need}+ of {md(team)}'s players on the same side. Check the spelling of "
                           "the names, or lower the number above.")
            else:
                wins, losses = report["wins"], report["losses"]
                m = st.columns(4)
                m[0].metric("Matches", len(report["matches"]))
                m[1].metric("Record", f"{wins}–{losses}")
                m[2].metric("Win %", f"{100 * wins / (wins + losses):.0f}%" if wins + losses else "—")
                m[3].metric("Team EPS", _fmt_eps(report["eps"]), help="Rounds-weighted over the team's players")
                if report["missing"]:
                    st.warning(f"Not found in {md(team)}'s matches: {md(', '.join(report['missing']))}. "
                               "Check the spelling.")
                table = []
                for r in sorted(report["players"], key=lambda r: -(r["eps"] or 0)):
                    row = pro_league_row(
                        team=0, player=r["name"], eps=int(r["eps"] or 0), kills=r["kills"], deaths=r["deaths"],
                        entry_kills=r["entry_kills"], entry_deaths=r["entry_deaths"], kost_pct=r["kost"] or 0,
                        kpr=r["kpr"] or 0, hs_pct=r["hs"] or 0, srv_pct=r["survival"] or 0, clutches=r["clutches"],
                        multikills=r["multikills"], objectives=r["objectives"], traded=r["traded"],
                        trade_kills=r["trade_kills"])
                    row.pop("Team")
                    table.append({"Player": row.pop("Player"), "Matches": r["matches"], **row})
                st.subheader(f"{md(team)}: player stats")
                st.dataframe(table, hide_index=True)
                st.caption("Only stats from playing on this team count: a match where a player was on the other "
                           "side isn't included for them. EPS is the rounds-weighted average of their per-match EPS.")
                st.subheader("Matches")
                matches = []
                for r in report["matches"]:
                    own, other = (r["score0"], r["score1"]) if r["team"] == 0 else (r["score1"], r["score0"])
                    matches.append({"When": nice_time(r["played_at"]), "Map": r["map"], "Score": f"{own}–{other}",
                                    "Result": {1: "Win", 0: "Loss"}.get(r["won"], "Draw"), "Players": r["players"]})
                st.dataframe(matches, hide_index=True)
                dl, track = st.columns([1, 2])
                safe_name = re.sub(r"[^\w\- ]+", "", team).strip() or "team"  # a usable file name
                dl.download_button("⬇ CSV", rows_csv(table).encode("utf-8"), file_name=f"{safe_name}_team_stats.csv",
                                   mime="text/csv")
                if not is_public_host() and track.button(f"Also track {md(team)} in the season tracker"):
                    with StatsManager(season=st.session_state.get("r6_season", "current")) as manager:
                        manager.add_players(teams[team], team=team)
                    st.success(f"Tracking {len(teams[team])} players as {md(team)}. Save matches from Dashboard to add "
                               "them to the season.")

# ------------------------------------------------------------ season teams --
with season_tab:
    st.caption("The season tracker: totals for the players you track, from the matches you save on the Dashboard.")
    season = st.text_input("Season", value=st.session_state.get("r6_season", "current"), key="team_season").strip() or "current"
    st.session_state["r6_season"] = season
    with StatsManager(season=season) as manager:
        season_teams = [t for t in (manager.get_team_stats(n) for n in manager.teams()) if t]
        saved = manager.match_history()
        snapshot = manager.export_json()

    if not season_teams:
        st.info("No team totals yet. Track a roster and save a match from Dashboard, or import a school roster first.")
    else:
        selected = st.selectbox("Season team", [t.team for t in season_teams])
        team = next(t for t in season_teams if t.team == selected)
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
        st.subheader("All season teams")
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
        } for t in season_teams], hide_index=True)
        st.caption("EPS is the rounds-weighted average of each player's per-match EPS. "
                   "Matches saved before EPS was recorded show —.")
    if saved:
        with open_stats_db() as db:  # name the saved matches the way the rest of the app does
            known = {r["match_id"]: r for r in db.match_list()}
        with st.expander(f"Matches saved to {season} ({len(saved)})"):
            st.dataframe([{
                "Match": match_label(known[m["match_id"]]["source"], known[m["match_id"]])
                if m["match_id"] in known else m["match_id"],
                "Saved": nice_time(m["saved_at"][:19].replace("T", " ")),
                "Rounds": m["rounds"],
                "Tracked players": m["players"],
            } for m in saved], hide_index=True)
    st.download_button("Export season report", json.dumps(snapshot, indent=2).encode("utf-8"),
                       file_name=f"{season}_team_report.json", mime="application/json")
