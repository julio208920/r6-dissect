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
from branding import render_identity

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
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
:root { --bg:#101416; --panel:#181e20; --row:#202729; --border:#333d3d; --accent:#d49353;
        --mint:#83a99c; --dim:#9ba7a4; --text:#e8ece9; --pos:#86b99f; --neg:#e17e69; }
.stApp { background:linear-gradient(122deg, #101416 0%, #171d1f 58%, #14191a 100%); color:var(--text); }
.stApp, [data-testid="stMarkdownContainer"] p, [data-testid="stWidgetLabel"] p { font-family:'IBM Plex Sans', sans-serif; }
.stMainBlockContainer { max-width:1480px; padding-top:1.2rem; padding-bottom:4rem; }
header[data-testid="stHeader"] { background:rgba(16,20,22,.84); }
section[data-testid="stSidebar"] { background:#161c1e; border-right:1px solid var(--border); }
h1, h2, h3, h4 { color:var(--text) !important; font-family:'Barlow Condensed', sans-serif !important; font-weight:600 !important; letter-spacing:0 !important; }
h1 { font-size:2.2rem !important; }
[data-testid="stMetric"] { padding:12px 14px; background:rgba(24,30,32,.72); border:1px solid var(--border); border-radius:4px; }
[data-testid="stMetricLabel"] { color:var(--dim) !important; }
[data-testid="stMetricValue"] { font-family:'IBM Plex Mono', monospace; }
[data-testid="stTabs"] button[role="tab"] { font-family:'Barlow Condensed',sans-serif; font-size:1.05rem; text-transform:uppercase; }
[data-testid="stTabs"] button[aria-selected="true"] { color:var(--accent); }
button[kind="primary"] { background:#a96839; border-color:#a96839; color:#101416; }
button[kind="primary"]:hover { background:#c4844c; border-color:#c4844c; color:#101416; }
.scorecard { background:linear-gradient(112deg,#202729,#171d1f); border:1px solid var(--border); border-left:3px solid var(--accent);
             border-radius:4px; padding:18px 24px; margin-bottom:18px; display:flex; align-items:center;
             justify-content:space-between; gap:16px; flex-wrap:wrap; box-shadow:0 12px 28px rgba(0,0,0,.18); }
.team-name { font-size:1.05rem; color:var(--text); font-weight:700; }
.score-big { font:600 2.35rem 'IBM Plex Mono',monospace; color:var(--accent); }
.map-pill { display:inline-block; background:#252d2e; color:var(--dim); border-radius:2px;
            padding:4px 10px; font:10px 'IBM Plex Mono',monospace; text-transform:uppercase; border:1px solid var(--border); }
.pl-wrap { overflow-x:auto; margin-bottom:22px; border:1px solid var(--border); border-radius:4px; }
table.pl { width:100%; border-collapse:collapse; font-size:0.84rem; color:var(--text); font-variant-numeric:tabular-nums; }
table.pl caption { caption-side:top; text-align:left; padding:10px 14px; font-weight:700;
                   font-size:1rem; background:var(--panel); color:var(--text); }
table.pl caption .won { color:var(--accent); margin-left:8px; font:10px 'IBM Plex Mono',monospace; }
table.pl th { background:#1b2224; color:var(--dim); font:500 10px 'IBM Plex Mono',monospace; text-align:center;
              padding:9px 8px; white-space:nowrap; border-top:1px solid var(--border); }
table.pl td { padding:9px 8px; text-align:center; white-space:nowrap; border-top:1px solid #303839; }
table.pl tr:nth-child(even) td { background:rgba(32,39,41,.72); }
table.pl th:first-child, table.pl td:first-child { text-align:left; font-weight:600; }
table.pl td.eps { color:var(--accent); font-weight:800; }
.pos { color:var(--pos); } .neg { color:var(--neg); }
@media(max-width:700px) { .stMainBlockContainer { padding-left:1rem; padding-right:1rem; } h1 { font-size:1.8rem !important; } }
</style>
""", unsafe_allow_html=True)

page = st.navigation([
    st.Page("report.py", title="Dashboard", icon=":material/dashboard:", default=True),
    st.Page("history.py", title="Match History", icon=":material/history:"),
    st.Page("operators.py", title="Operator Analytics", icon=":material/target:"),
    st.Page("teams.py", title="Team Analytics", icon=":material/groups:"),
    st.Page("schools.py", title="School Selection", icon=":material/school:"),
    st.Page("appearance.py", title="School Theme", icon=":material/palette:"),
    st.Page("download.py", title="Get the Windows app", icon=":material/download:"),
], position="sidebar")
render_identity()
page.run()
