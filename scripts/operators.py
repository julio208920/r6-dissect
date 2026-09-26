"""Operator performance for the latest replay loaded in this session."""

from __future__ import annotations

from collections import defaultdict

import streamlit as st

from metrics_engine import compute_match_metrics


st.title("Operator Analytics")
match = st.session_state.get("r6_last_match")
if not match:
    st.info("Load a replay on Dashboard to see operator performance.")
    st.stop()

team_by_player = {player["name"]: player["team"] for player in match.get("players", [])}
# kills and deaths per (player, round), counted exactly as on the scoreboard (no team kills)
round_stats = {(name, rb.round_num): rb for name, s in compute_match_metrics(match).items() for rb in s.round_breakdown}
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
        rb = round_stats.get((username, round_data.get("round_num")))
        if rb is not None:
            row["kills"] += rb.kills
            row["deaths"] += rb.deaths

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
        "Kills / Deaths": f"{record['kills']} / {record['deaths']}",
        "K/D": round(record["kills"] / record["deaths"], 2) if record["deaths"] else record["kills"],
    })
    for site, (picks, wins) in sorted(record["sites"].items()):
        site_rows.append({"Operator": name, "Site": site, "Rounds": picks, "Wins": wins,
                          "Win rate": f"{wins / picks:.0%}" if picks else "0%"})

st.caption(f"{match.get('map', 'Current match')} · {len(match.get('rounds', []))} rounds · current session")
st.dataframe(rows, hide_index=True)
st.subheader("Site performance")
st.dataframe(site_rows, hide_index=True)