"""Season match history from the local replay-statistics database."""

from __future__ import annotations

import json

import streamlit as st

from season_stats import StatsManager


st.title("Match History")
st.caption("Recorded replay matches for the selected season.")
season = st.text_input("Season", value=st.session_state.get("r6_season", "current"), key="history_season").strip() or "current"
st.session_state["r6_season"] = season

with StatsManager(season=season) as manager:
    matches = manager.match_history()
    players = manager.all_player_stats()
    snapshot = manager.export_json()

if matches:
    total_rounds = sum(match["rounds"] for match in matches)
    columns = st.columns(3)
    columns[0].metric("Matches logged", len(matches))
    columns[1].metric("Rounds recorded", total_rounds)
    columns[2].metric("Players in season", len(players))
    st.dataframe(
        [{
            "Match ID": match["match_id"],
            "Saved": match["saved_at"].replace("T", " ").replace("+00:00", " UTC"),
            "Rounds": match["rounds"],
            "Tracked players": match["players"],
        } for match in matches],
        hide_index=True,
    )
    st.download_button(
        "Export season snapshot",
        json.dumps(snapshot, indent=2).encode("utf-8"),
        file_name=f"{season}_season_stats.json",
        mime="application/json",
    )
else:
    st.info("No saved matches in this season yet. Load a replay on Dashboard and log it to the tracker.")