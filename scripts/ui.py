"""The header shared by the R6 Match Stats pages."""

from __future__ import annotations

import html
import re

import streamlit as st

from app_info import APP_NAME

DEFAULT_ACCENT = "#d49353"
_MARKDOWN = re.compile(r"([\\`*_\[\]<>#|~$])")


def md(text: object) -> str:
    """Text (a gamertag, a team name, an answer) shown exactly as written in Streamlit's Markdown,
    where "_Sniper_" would otherwise come out as an italic Sniper."""
    return _MARKDOWN.sub(r"\\\1", str(text))


def render_header(accent_color: str = DEFAULT_ACCENT) -> None:
    """A slim header: the app's name, with a stripe in the selected school's color. Plain HTML and
    CSS (styled in app.py): nothing to download, so it shows at once and works offline."""
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent_color or ""):
        accent_color = DEFAULT_ACCENT
    st.markdown(
        f'<div class="r6-header" style="--r6-accent:{accent_color}">'
        f'<span class="r6-title">{html.escape(APP_NAME)}</span>'
        '<span class="r6-sub">Replay stats, trends and teams</span></div>',
        unsafe_allow_html=True,
    )
