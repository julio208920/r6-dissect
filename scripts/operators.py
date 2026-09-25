"""Operator performance for the latest replay loaded in this session."""

from __future__ import annotations

from collections import defaultdict

import streamlit as st


st.title("Operator Analytics")
match = st.session_state.get("r6_last_match")
if not match:
    st.info("Load a replay on Dashboard to see operator performance.")
    st.stop()

team_by_player = {player["name"]: player["team"] for player in match.get("players", [])}
records: dict[str, dict] = defaultdict(lambda: {
    "picks": 0, "round_wins": 0, "kills": 0, "deaths": 0, "sites": defaultdict(lambda: [0, 0]),
})
total_picks = 0

for round_data in match.get("rounds", []):
    operators = dict(round_data.get("operators", {}))
    if not operators:
        for player in match.get("players", []):
            history = player.get("operator_history", [])
            if len(history) == 1 and player["name"] in round_data.get("players", []):
                operators[player["name"]] = history[0]
    site = round_data.get("site") or "Unknown site"
    for username, operator_name in operators.items():
        if not operator_name:
            continue
        row = records[operator_name]
        row["picks"] += 1
        total_picks += 1
        row["sites"][site][0] += 1
        if round_data.get("winner_team") == team_by_player.get(username):
            row["round_wins"] += 1
            row["sites"][site][1] += 1
        for event in round_data.get("events", []):
            if event.get("type") == "kill" and event.get("actor") == username:
                row["kills"] += 1
            elif event.get("type") == "death" and event.get("actor") == username:
                row["deaths"] += 1

if not records:
    st.info("This replay does not include operator selections. Try a recent match replay.")
    st.stop()

rows = []
site_rows = []
for name, record in sorted(records.items(), key=lambda item: (-item[1]["picks"], item[0])):
    rows.append({
        "Operator": name,
        "Picks": record["picks"],
        "Pick rate": f"{record['picks'] / total_picks:.0%}" if total_picks else "0%",
        "Round win rate": f"{record['round_wins'] / record['picks']:.0%}",
        "K / D": f"{record['kills']} / {record['deaths']}",
        "K/D": round(record["kills"] / record["deaths"], 2) if record["deaths"] else record["kills"],
    })
    for site, (picks, wins) in sorted(record["sites"].items()):
        site_rows.append({"Operator": name, "Site": site, "Rounds": picks, "Wins": wins,
                          "Win rate": f"{wins / picks:.0%}" if picks else "0%"})

st.caption(f"{match.get('map', 'Current match')} · {len(match.get('rounds', []))} rounds · current session")
st.dataframe(rows, use_container_width=True, hide_index=True)
st.subheader("Site performance")
st.dataframe(site_rows, use_container_width=True, hide_index=True)