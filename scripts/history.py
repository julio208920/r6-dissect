"""Match History: every match in the stats database, newest first, with your result in each."""

from __future__ import annotations

import streamlit as st

from metrics_engine import eps_from_rating, round_eps, rows_csv
from sources import current_source, open_stats_db, sync_with_progress
from stats_db import nice_time
from ui import md

st.title("Match History")

with open_stats_db() as db:
    source = current_source()
    if source and "error" not in source:
        sync_with_progress(db, source)
    me = db.me()
    rows = db.match_list(me)

if not rows:
    st.info("No matches yet. Open your replays on **Dashboard** (or upload them there), and they'll be listed here.")
    st.stop()

mine = [r for r in rows if r["player"]]
if mine:
    wins, losses = sum(r["won"] == 1 for r in mine), sum(r["won"] == 0 for r in mine)
    kills, deaths = sum(r["kills"] for r in mine), sum(r["deaths"] for r in mine)
    rounds = sum(r["player_rounds"] for r in mine)
    columns = st.columns(4)
    columns[0].metric("Matches", len(mine))
    columns[1].metric("Record", f"{wins}–{losses}", help="Wins–losses, from your team's side")
    columns[2].metric("K/D", f"{kills / deaths if deaths else kills:.2f}")
    eps = round_eps(100 * sum(r["rating"] * r["player_rounds"] for r in mine) / rounds) if rounds else "—"
    columns[3].metric("EPS", eps, help="Your average EPS, weighted by rounds played")
    st.caption(f"Your matches as **{md(me)}**, newest first. Select one to open it on the Dashboard.")

table = []
for r in rows:
    row = {"When": nice_time(r["played_at"]), "Map": r["map"] or "", "Type": r["match_type"] or ""}
    if r["player"]:
        own, other = (r["score0"], r["score1"]) if r["team"] == 0 else (r["score1"], r["score0"])
        row |= {"Result": {1: "Win", 0: "Loss"}.get(r["won"], "Draw"), "Score": f"{own}–{other}",
                "K-D": f"{r['kills']}-{r['deaths']}", "EPS": eps_from_rating(r["rating"])}
    else:
        row |= {"Result": "—", "Score": f"{r['score0']}–{r['score1']}", "K-D": "", "EPS": None}
    table.append(row)

picked = st.dataframe(table, hide_index=True, on_select="rerun", selection_mode="single-row", key="history_rows")
chosen = picked.selection.rows if picked else []
if chosen:
    name = rows[chosen[0]]["source"]
    if source and name in (source.get("groups") or {}):
        if st.button("Open on Dashboard", type="primary"):
            st.session_state["open_match"] = name
            st.switch_page("report.py")
    else:
        st.caption("This match's replay isn't in your replay folder anymore (the game deletes old ones), "
                   "but its stats are still here and on **Ask**.")
st.download_button("⬇ CSV", rows_csv(table).encode("utf-8"), file_name="match_history.csv", mime="text/csv")
