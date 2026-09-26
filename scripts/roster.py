"""
roster.py
=========
Team rosters: a team name and its players' in-game usernames. Given the matches
in a replay source, find the ones the roster played together and add up each
player's stats across them (metrics_engine.combine_player_stats).

    matches = find_roster_matches(groups, roster, min_players=3, players_of=..., parse=...)
    report = roster_report(roster, matches)

Usernames are matched ignoring case. A match counts when at least `min_players`
of the roster were on the same team in it; only the roster's own stats from
that match are used.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from metrics_engine import PlayerStats, combine_player_stats, compute_match_metrics

ROSTER_SIZE = 5
PARALLEL_PARSES = 4  # r6-dissect runs as its own process; each can use a few hundred MB


@dataclass
class Roster:
    team: str
    players: list[str]

    @classmethod
    def from_input(cls, team: str, players: list[str]) -> "Roster":
        """Clean what someone typed: trims, drops blanks and repeats (ignoring case)."""
        seen: dict[str, str] = {}
        for p in players:
            p = p.strip()
            if p and p.casefold() not in seen:
                seen[p.casefold()] = p
        return cls(team=team.strip(), players=list(seen.values()))

    def keys(self) -> set[str]:
        return {p.casefold() for p in self.players}


@dataclass
class RosterMatch:
    name: str        # the match's folder name
    match: dict      # parser.parse_match output
    side: int        # the roster's team index in the match
    present: list[str]  # roster players (as typed) who played in it

    @property
    def won(self) -> bool | None:
        score = self.match.get("final_score") or [0, 0]
        if score[0] == score[1]:
            return None
        return score[self.side] > score[1 - self.side]


@dataclass
class RosterReport:
    roster: Roster
    matches: list[RosterMatch]
    players: dict[str, PlayerStats] = field(default_factory=dict)  # roster name -> combined stats
    matches_played: dict[str, int] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)  # roster players found in no match

    @property
    def record(self) -> tuple[int, int]:
        """(wins, losses) of the roster's side; draws count as neither."""
        results = [m.won for m in self.matches]
        return results.count(True), results.count(False)

    @property
    def team_eps(self) -> int | None:
        rounds = sum(p.rounds_played for p in self.players.values())
        if not rounds:
            return None
        return round(100 * sum(p.rating * p.rounds_played for p in self.players.values()) / rounds)


def roster_side(players_by_team: dict[str, int], roster: Roster) -> tuple[int, list[str]] | None:
    """The team the roster played on in a match ({username: team index}), and which of
    its players were there; None if no roster player was in it."""
    by_key = {p.casefold(): p for p in roster.players}
    sides: dict[int, list[str]] = {}
    for username, team in players_by_team.items():
        typed = by_key.get(username.casefold())
        if typed is not None:
            sides.setdefault(team, []).append(typed)
    if not sides:
        return None
    side = max(sides, key=lambda t: (len(sides[t]), -t))
    return side, sides[side]


def find_roster_matches(
    groups: dict[str, list[str]],
    roster: Roster,
    min_players: int,
    players_of: Callable[[str, list[str]], dict[str, int]],
    parse: Callable[[str, list[str]], dict | None],
) -> list[RosterMatch]:
    """The matches (in `groups` order) where at least `min_players` of the roster were
    on one team. players_of(name, recs) -> {username: team index} should be cheap (the
    first round is enough); parse(name, recs) -> the parsed match, or None if it can't
    be read. Only matches that pass the roster check are parsed."""
    min_players = max(1, min(min_players, len(roster.players)))
    with ThreadPoolExecutor(max_workers=PARALLEL_PARSES) as pool:
        who = list(pool.map(lambda item: players_of(*item), groups.items()))
        candidates = [name for name, players in zip(groups, who)
                      if (hit := roster_side(players, roster)) and len(hit[1]) >= min_players]
        parsed = list(pool.map(lambda name: parse(name, groups[name]), candidates))
    found = []
    for name, match in zip(candidates, parsed):
        if not match:
            continue
        # the whole match's roster, not just the first round's
        hit = roster_side({p["name"]: p["team"] for p in match.get("players", [])}, roster)
        if hit and len(hit[1]) >= min_players:
            found.append(RosterMatch(name=name, match=match, side=hit[0], present=hit[1]))
    return found


def roster_report(roster: Roster, matches: list[RosterMatch]) -> RosterReport:
    """Each roster player's stats, added up over the matches they played in."""
    per_player: dict[str, list[PlayerStats]] = {p: [] for p in roster.players}
    by_key = {p.casefold(): p for p in roster.players}
    for rm in matches:
        for username, stats in compute_match_metrics(rm.match).items():
            typed = by_key.get(username.casefold())
            if typed is not None and stats.team == rm.side and stats.rounds_played:
                per_player[typed].append(stats)
    report = RosterReport(roster=roster, matches=matches)
    for typed, games in per_player.items():
        if games:
            report.players[typed] = combine_player_stats(games[0].name, games)
            report.matches_played[typed] = len(games)
        else:
            report.missing.append(typed)
    return report


def players_from_round(raw: dict[str, Any]) -> dict[str, int]:
    """{username: team index} from r6-dissect's JSON for one round."""
    return {p["username"]: p.get("teamIndex", 0) for p in raw.get("players") or [] if p.get("username")}
