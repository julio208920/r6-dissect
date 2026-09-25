"""
app.py
======
Entry point of the R6 Match Stats website and Windows app (Streamlit).
Pages: report.py (the match report) and download.py (get the Windows app).

Run with:  streamlit run scripts/app.py   (from the repo root)
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

from app_info import APP_NAME, quiet_windows_connection_resets

if __name__ == "__main__":
    from streamlit import runtime

    if not runtime.exists():
        # started with `python app.py` (e.g. VS Code's Run button) -- relaunch
        # under `streamlit run` from the repo root, where .streamlit/config.toml lives
        import os

        from streamlit.web import cli as stcli

        quiet_windows_connection_resets()
        os.chdir(Path(__file__).resolve().parent.parent)
        sys.argv = ["streamlit", "run", str(Path(__file__).resolve())]
        sys.exit(stcli.main())

# for `streamlit run app.py`, which starts the server before this script runs
quiet_windows_connection_resets()

st.set_page_config(page_title=APP_NAME, page_icon=str(Path(__file__).with_name("icon.png")), layout="wide")

# ---------------------------------------------------------------- styling --
st.markdown("""
<style>
:root { --bg:#0d1117; --panel:#151b23; --row:#1a212b; --border:#232b36; --accent:#54d6e8;
        --dim:#8b949e; --text:#f0f3f6; --pos:#3fb950; --neg:#f85149; }
.stApp { background-color: var(--bg); }
section[data-testid="stSidebar"] { background-color: var(--panel); }
h1, h2, h3, h4 { color: var(--text) !important; letter-spacing: -0.02em; }
.scorecard { background:var(--panel); border:1px solid var(--border); border-radius:14px;
             padding:20px 28px; margin-bottom:18px; display:flex; align-items:center;
             justify-content:space-between; gap:16px; flex-wrap:wrap; }
.team-name { font-size:1.15rem; color:var(--text); font-weight:700; }
.score-big { font-size:2.6rem; font-weight:800; color:var(--accent); }
.map-pill { display:inline-block; background:#1f2733; color:var(--dim); border-radius:999px;
            padding:4px 14px; font-size:0.8rem; font-weight:600; border:1px solid var(--border); }
.pl-wrap { overflow-x:auto; margin-bottom:22px; border:1px solid var(--border); border-radius:10px; }
table.pl { width:100%; border-collapse:collapse; font-size:0.9rem; color:var(--text);
           font-variant-numeric: tabular-nums; }
table.pl caption { caption-side:top; text-align:left; padding:10px 14px; font-weight:700;
                   font-size:1.05rem; background:var(--panel); color:var(--text); }
table.pl caption .won { color:var(--accent); margin-left:8px; }
table.pl th { background:var(--panel); color:var(--dim); font-weight:600; text-align:center;
              padding:8px 10px; white-space:nowrap; border-top:1px solid var(--border); }
table.pl td { padding:9px 10px; text-align:center; white-space:nowrap; border-top:1px solid var(--border); }
table.pl tr:nth-child(even) td { background:var(--row); }
table.pl th:first-child, table.pl td:first-child { text-align:left; font-weight:600; }
table.pl td.eps { color:var(--accent); font-weight:800; }
.pos { color:var(--pos); } .neg { color:var(--neg); }
.block-container { max-width:1400px; padding-top:2.5rem; }
[data-testid="stMetric"] { background:#151e2b; border:1px solid #29374a; border-radius:10px; padding:16px; }
[data-testid="stMetricLabel"] { color:#a6b8cb; text-transform:uppercase; font-size:.75rem; letter-spacing:.08em; }
.scorecard { border-top:3px solid #54d6e8; background:linear-gradient(120deg,#152537,#111923); }
table.pl th { font-size:.75rem; letter-spacing:.025em; }
table.pl tbody tr:hover td { background:#203247; }
.stButton > button { border-radius:7px; }
@media(max-width:700px) { .block-container { padding:1.2rem; } .score-big { font-size:2rem; } }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### R6 / MATCH STATS")
    st.caption("COLLEGIATE COMPETITION")
    st.caption("Built for Siege teams competing in NECC. Independent community tool.")

st.navigation([
    st.Page("report.py", title="Match report", icon="🎯", default=True),
    st.Page("team_hub.py", title="Team Hub", icon=":material/groups:"),
    st.Page("download.py", title="Get the Windows app", icon="💾"),
]).run()
