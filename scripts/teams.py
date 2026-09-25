"""Persistent season team analytics."""

from __future__ import annotations

import json

import streamlit as st

from season_stats import StatsManager


st.title("Team Analytics")
season = st.text_input("Season", value=st.session_state.get("r6_season", "current"), key="team_season")

with StatsManager(season=season) as manager:
    team_names = manager.teams()
    snapshot = manager.export_json()
    summaries = []
    for name in team_names:
        team = manager.get_team_stats(name)
        if team:
            summaries.append({
                "Team": team.team,
                "Players": len(team.players),
                "Rounds": team.totals["rounds_played"],
                "Kills": team.totals["kills"],
                "Deaths": team.totals["deaths"],
                "K/D": round(team.kd, 2),
                "Entry +/-": team.entry_diff,
                "KOST": f"{team.kost_avg:.1f}%",
            })

if not summaries:
    st.info("No team totals yet. Track a roster and log a match from Dashboard, or import a school roster first.")
else:
    selected_team = st.selectbox("Team", team_names)
    with StatsManager(season=season) as manager:
        team = manager.get_team_stats(selected_team)
        members = team.member_stats if team else []
    if team:
        metric_columns = st.columns(5)
        metric_columns[0].metric("Rounds", team.totals["rounds_played"])
        metric_columns[1].metric("K/D", f"{team.kd:.2f}")
        metric_columns[2].metric("Entry +/-", f"{team.entry_diff:+d}")
        metric_columns[3].metric("KOST avg", f"{team.kost_avg:.1f}%")
        metric_columns[4].metric("Clutch success", "—" if team.clutch_success_rate is None else f"{team.clutch_success_rate:.0%}")
        st.subheader("Roster performance")
        st.dataframe([{
            "Player": player.username,
            "Rounds": player.totals["rounds_played"],
            "K / D / A": f"{player.totals['kills']} / {player.totals['deaths']} / {player.totals['assists']}",
            "K/D": round(player.kd, 2),
            "Entry +/-": player.entry_diff,
            "KOST": f"{player.kost_pct:.1f}%",
            "HS": f"{player.hs_pct:.1f}%",
            "Clutches": player.clutches_won,
        } for player in members], use_container_width=True, hide_index=True)
    st.subheader("Season teams")
    st.dataframe(summaries, use_container_width=True, hide_index=True)
    st.download_button(
        "Export season report",
        json.dumps(snapshot, indent=2).encode("utf-8"),
        file_name=f"{season}_team_report.json",
        mime="application/json",
    )