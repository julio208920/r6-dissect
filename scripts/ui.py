"""Helpers shared by the R6 Match Stats pages."""

from __future__ import annotations

import re

_MARKDOWN = re.compile(r"([\\`*_\[\]<>#|~$])")


def md(text: object) -> str:
    """Text (a gamertag, a team name, an answer) shown exactly as written in Streamlit's Markdown,
    where "_Sniper_" would otherwise come out as an italic Sniper."""
    return _MARKDOWN.sub(r"\\\1", str(text))
