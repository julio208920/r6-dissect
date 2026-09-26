"""Searchable school and R6 roster selection from an imported NECC catalog."""

from __future__ import annotations

import html
import json
import os
import re

import streamlit as st

from necc_data import MAX_CATALOG_BYTES, fetch_school_catalog, normalize_school_catalog
from app_info import is_public_host
from season_stats import StatsManager


st.title("School Selection")
feed_configured = bool(os.environ.get("NECC_R6_DATA_URL"))
feed_column, upload_column = st.columns([1, 2])
with feed_column:
    if st.button("Sync NECC feed", disabled=not feed_configured, type="primary"):
        try:
            st.session_state["necc_schools"] = fetch_school_catalog()
            st.session_state["necc_catalog_source"] = "Configured NECC feed"
            st.rerun()
        except (OSError, ValueError) as error:
            st.error(f"School feed unavailable: {error}")
with upload_column:
    uploaded_catalog = st.file_uploader("Import school catalog (.json)", type=["json"], key="necc_catalog_upload")
    if uploaded_catalog:
        try:
            raw_catalog = uploaded_catalog.getvalue()
            if len(raw_catalog) > MAX_CATALOG_BYTES:
                raise ValueError("The school catalog exceeds the 2 MB limit.")
            st.session_state["necc_schools"] = normalize_school_catalog(json.loads(raw_catalog))
            st.session_state["necc_catalog_source"] = uploaded_catalog.name
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            st.error(f"Could not import catalog: {error}")

schools = st.session_state.get("necc_schools", [])
if not schools:
    if feed_configured:
        st.info("No catalog loaded. Sync the configured HTTPS feed or import a school JSON export.")
    else:
        st.info("No NECC data feed is configured in this workspace. Import a school JSON export to browse rosters.")
        st.code(
            '{"schools":[{"name":"University","logo_url":"https://...",'
            '"primary_color":"#286b78","teams":[{"name":"R6 Varsity",'
            '"game":"Rainbow Six Siege","roster":["PlayerOne"],"standings":{},"matches":[]}]}]}',
            language="json",
        )
    st.stop()

st.caption(f"Catalog: {st.session_state.get('necc_catalog_source', 'loaded this session')}")
selected_school = st.selectbox("School", schools, format_func=lambda school: school["name"], key="necc_school")
st.session_state["selected_school_name"] = selected_school["name"]
primary_color = selected_school.get("primary_color") or "#d49353"
if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(primary_color)):
    primary_color = "#d49353"
st.session_state["selected_school_color"] = primary_color

teams = selected_school.get("teams", [])
if not teams:
    st.warning("This school has no Rainbow Six roster in the loaded catalog.")
    st.stop()
selected_team = st.selectbox("Rainbow Six team", teams, format_func=lambda team: team["name"])
team_name = selected_team["name"]
st.session_state["selected_school_team"] = team_name
roster = selected_team.get("roster", [])

school_column, details_column = st.columns([1, 2])
with school_column:
    logo_url = selected_school.get("logo_url")
    if isinstance(logo_url, str) and logo_url.startswith(("https://", "http://")):
        st.image(logo_url, width=104)
    st.markdown(
        f'<div style="border-left:3px solid {primary_color};padding:8px 14px;background:#1b2224">'
        f'<div style="font:700 11px IBM Plex Mono,monospace;color:{primary_color};text-transform:uppercase">NECC R6</div>'
        f'<div style="font:600 24px Barlow Condensed,sans-serif;color:#e8ece9">{html.escape(selected_school["name"])}</div>'
        f'<div style="color:#9ba7a4;font-size:13px">{html.escape(team_name)}</div></div>',
        unsafe_allow_html=True,
    )
    st.metric("Roster", len(roster))
    if is_public_host():
        st.caption("Roster tracking is disabled on shared public hosting.")
    if st.button("Track this roster", disabled=not roster or is_public_host(), type="primary"):
        season = st.session_state.get("r6_season", "current")
        with StatsManager(season=season) as manager:
            manager.add_players(roster, team=team_name)
        st.success(f"Added {len(roster)} players to {team_name} for {season}.")
with details_column:
    st.subheader("Roster")
    if roster:
        st.dataframe([{"Player": name} for name in roster], hide_index=True)
    else:
        st.info("Roster data is not included for this team.")

    standings = selected_team.get("standings")
    if standings:
        st.subheader("Standings")
        if isinstance(standings, list) and all(isinstance(row, dict) for row in standings):
            st.dataframe(standings, hide_index=True)
        else:
            st.json(standings)

    matches = selected_team.get("matches") or []
    if matches:
        st.subheader("Match history")
        if isinstance(matches, list) and all(isinstance(row, dict) for row in matches):
            st.dataframe(matches, hide_index=True)
        else:
            st.json(matches)