"""Normalize a public or exported NECC Rainbow Six school catalog."""

from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

MAX_CATALOG_BYTES = 2 * 1024 * 1024


def _roster(team: dict[str, Any]) -> list[str]:
    raw = team.get("roster") or team.get("players") or team.get("members") or []
    names = []
    for player in raw:
        name = player if isinstance(player, str) else (
            player.get("name") or player.get("username") if isinstance(player, dict) else None)
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return list(dict.fromkeys(names))


def normalize_school_catalog(payload: Any) -> list[dict[str, Any]]:
    """Convert a simple schools/teams JSON response to the UI's stable shape.

    Expected top-level shape: {"schools": [{"name": ..., "teams": [...]}]}.
    Team entries may provide game, roster/players, standings, and matches.
    """
    if isinstance(payload, dict):
        payload = payload.get("schools", payload.get("data"))
    if not isinstance(payload, list):
        raise ValueError("Catalog must be a JSON array or an object containing a schools array.")

    schools = []
    for source in payload:
        if not isinstance(source, dict):
            continue
        name = source.get("name") or source.get("school") or source.get("institution")
        if not isinstance(name, str) or not name.strip():
            continue
        raw_teams = source.get("teams") or source.get("rosters") or []
        teams = []
        for raw_team in raw_teams:
            if not isinstance(raw_team, dict):
                continue
            game = str(raw_team.get("game") or raw_team.get("title") or "").strip()
            if game and not re.search(r"rainbow\s*six|\br6\b|siege", game, re.I):
                continue
            team_name = raw_team.get("name") or raw_team.get("team") or "Rainbow Six"
            teams.append({
                "name": str(team_name),
                "game": game or "Rainbow Six Siege",
                "roster": _roster(raw_team),
                "standings": raw_team.get("standings") or source.get("standings"),
                "matches": raw_team.get("matches") or source.get("matches") or [],
            })
        if not teams and source.get("roster"):
            teams.append({
                "name": str(source.get("team_name") or "Rainbow Six"),
                "game": "Rainbow Six Siege",
                "roster": _roster(source),
                "standings": source.get("standings"),
                "matches": source.get("matches") or [],
            })
        schools.append({
            "name": name.strip(),
            "logo_url": source.get("logo_url") or source.get("logo"),
            "primary_color": source.get("primary_color") or source.get("color"),
            "teams": teams,
        })
    if not schools:
        raise ValueError("No schools with names were found in this catalog.")
    return sorted(schools, key=lambda school: school["name"].casefold())


def fetch_school_catalog(url: str | None = None) -> list[dict[str, Any]]:
    """Fetch the configured NECC feed; the deployment owner supplies its URL."""
    feed_url = (url or os.environ.get("NECC_R6_DATA_URL", "")).strip()
    if not feed_url or urlparse(feed_url).scheme != "https":
        raise ValueError("Set NECC_R6_DATA_URL to an HTTPS JSON feed.")
    request = Request(feed_url, headers={"Accept": "application/json", "User-Agent": "R6MatchStats/1"})
    with urlopen(request, timeout=10) as response:
        body = response.read(MAX_CATALOG_BYTES + 1)
    if len(body) > MAX_CATALOG_BYTES:
        raise ValueError("The school catalog exceeds the 2 MB limit.")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("The configured NECC feed did not return valid JSON.") from error
    return normalize_school_catalog(payload)
