"""Persistent local rosters and season statistics, isolated demo storage."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from app_info import is_public_host, is_loopback
from season_stats import DEFAULT_DB_PATH, StatsError, StatsManager


def storage_path(demo: bool, local: bool) -> Path:
    # Public sessions never share a roster or expose the host's saved database.
    if demo or not local:
        key = 'demo_team_storage' if demo else 'session_team_storage'
        if key not in st.session_state:
            st.session_state[key] = tempfile.TemporaryDirectory(prefix='r6-teams-')
        return Path(st.session_state[key].name) / 'teams.db'
    return DEFAULT_DB_PATH


def render_hub():
    st.caption('RAINBOW SIX SIEGE  /  TEAM OPERATIONS')
    st.title('Team Hub')
    st.caption('Your roster, match history and season performance in one place.')
    match = st.session_state.get('active_match')
    demo = st.toggle('Demo workspace', value=bool(st.session_state.get('active_match_demo', False)), key='hub_demo')
    local = not is_public_host() and is_loopback(st.context.ip_address)
    if demo:
        st.info('Demo workspace — sample results are separate from your real season records.')
    elif not local:
        st.info('Browser-session storage. Export your stats before leaving, or use the Windows app for permanent local storage.')
    else:
        st.caption('Saved on this computer. Your roster and results remain after closing or updating the app.')
    season = st.text_input('Season', value='NECC Fall 2026').strip()
    if not season:
        st.info('Enter a season to open your team workspace.')
        return
    with StatsManager(storage_path(demo, local), season=season) as sm:
        roster_tab, performance_tab, history_tab = st.tabs(['Roster & imports', 'Season performance', 'Match history'])
        with roster_tab:
            st.subheader('Build your roster')
            tracked = sm.tracked_players()
            available = sorted(set(tracked) | {p['name'] for p in (match or {}).get('players', [])})
            with st.form('save_roster'):
                team = st.text_input('Team name', placeholder='University / team name').strip()
                selected = st.multiselect('Select players from the current match or saved roster', available)
                manual = st.text_area('Add players by Siege username', placeholder='One username per line')
                submitted = st.form_submit_button('Save roster', type='primary')
            if submitted:
                names = list(dict.fromkeys(selected + [n.strip() for n in manual.splitlines() if n.strip()]))
                if not team or not names:
                    st.warning('Enter a team name and choose at least one player.')
                else:
                    sm.add_players(names, team=team)
                    st.success(f'Saved {len(names)} players to {team}.')
                    tracked = sm.tracked_players()
            if tracked:
                st.dataframe(pd.DataFrame([{'Player': p, 'Team': t or 'Unassigned'} for p, t in tracked.items()]), hide_index=True, width='stretch')
                with st.expander('Manage tracking'):
                    remove = st.multiselect('Stop tracking players (saved results are kept)', list(tracked))
                    if st.button('Stop tracking selected', disabled=not remove):
                        for player in remove:
                            sm.remove_player(player)
                        st.rerun()
            else:
                st.info('Load a match in Match Report to select its players, or enter usernames above.')
            st.subheader('Save current match')
            st.page_link('report.py', label='Open Match Report', icon=':material/analytics:')
            compatible = match and demo == bool(st.session_state.get('active_match_demo', False))
            warnings = st.session_state.get('active_match_warnings', [])
            if compatible:
                st.caption(f"{match['map']} · {len(match['rounds'])} rounds · {match['match_id']}")
                acknowledge = True
                if warnings:
                    st.warning('This import has parser warnings and may be incomplete. Review them in Match Report.')
                    acknowledge = st.checkbox('Save these partial results anyway')
                if st.button('Save match stats', type='primary', disabled=not tracked or not acknowledge):
                    result = sm.log_match(match)
                    if result.rounds_logged:
                        st.success(f'Saved {result.rounds_logged} player-rounds for {len(result.players_logged)} players.')
                    elif result.rounds_skipped_duplicate:
                        st.info('This match is already saved. No stats were counted twice.')
                    else:
                        st.warning('None of your tracked usernames matched this replay.')
                    for warning in result.warnings:
                        st.warning(warning)
            else:
                st.info('Load a match first. Demo matches can only be saved in the demo workspace.')

        with performance_tab:
            st.subheader('Season performance')
            teams = sm.teams()
            chosen = st.selectbox('Team', ['All teams'] + teams)
            players = [p for p in sm.all_player_stats() if chosen == 'All teams' or p.team == chosen]
            totals = {key: sum(p.totals[key] for p in players) for key in ('kills', 'deaths', 'rounds_played', 'kost_rounds')}
            a, b, c, d = st.columns(4)
            a.metric('Players', len(players))
            b.metric('Kills / deaths', f"{totals['kills']} / {totals['deaths']}")
            c.metric('KOST', f"{100 * totals['kost_rounds'] / max(1, totals['rounds_played']):.1f}%")
            d.metric('Player-rounds', totals['rounds_played'])
            table = []
            for p in players:
                t = p.totals
                rounds = max(1, t['rounds_played'])
                table.append({'Player': p.username, 'Team': p.team, 'Rounds': t['rounds_played'],
                    'Kills': t['kills'], 'Deaths': t['deaths'], 'Assists': t['assists'], 'K/D': round(p.kd, 2),
                    'KOST %': round(p.kost_pct, 1), 'KPR': round(t['kills'] / rounds, 2), 'HS %': round(p.hs_pct, 1),
                    'Survival %': round(100 * t['kost_survive'] / rounds, 1),
                    'Entry kills': t['entry_kills'], 'Entry deaths': t['entry_deaths'],
                    'Plants': t['plants'], 'Defuses': t['defuses'], 'Trades received': t['trades'],
                    'Trade kills': t['trade_kills'], 'Multikill rounds': t['multikill_rounds'], 'Clutches': p.clutches_won})
            if table:
                frame = pd.DataFrame(table)
                st.dataframe(frame, hide_index=True, width='stretch')
                st.bar_chart(frame.set_index('Player')[['Kills', 'Deaths']], color=['#54d6e8', '#e88775'])
                st.download_button('Export team CSV', frame.to_csv(index=False).encode('utf-8'), file_name='team-stats.csv', mime='text/csv')
            else:
                st.info('Save your first match to see season totals here.')
            st.caption('EPS is a relative match score, not an official Ubisoft rating. It is shown per match rather than added across a season.')
            st.download_button('Export season JSON', json.dumps(sm.export_json(), indent=2).encode('utf-8'), file_name='season-stats.json', mime='application/json')

        with history_tab:
            st.subheader('Saved matches')
            history = sm.match_history()
            if history:
                st.dataframe(pd.DataFrame(history), hide_index=True, width='stretch')
            else:
                st.info('No matches saved in this season yet.')
            st.caption('Re-importing the same player and round does not add it twice. Partial imports can be completed by importing the remaining rounds.')


try:
    render_hub()
except (StatsError, sqlite3.Error, OSError) as exc:
    st.error(f'Could not save or load team statistics: {exc}')
    st.caption('Check available disk space and folder permissions, then retry. Existing saved records have not been reset.')
