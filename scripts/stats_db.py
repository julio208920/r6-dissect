"""
stats_db.py
===========
A database of every match the app has read: one row per match, per player per
match, and per player per round. It fills itself from the replays (Ask, Match
History and Build a team read from it), so nothing is ever imported by hand, and
the teams built on the Team page are kept in it so questions can name them.

Tables (SQLite, in the same file as the season tracker's tables):

    matches        one per match (the replay's matchID): when, map, match type, teams, score,
                   and who recorded the replay ("you")
    match_players  one per player per match: the scoreboard's numbers, EPS rating, won or lost
    round_players  one per player per round: operator, side, site, kills, died, round won
    team_rounds    one per team per round: side, round won, bomb planted, and whether the team
                   was ever two or more players down. Every round of a match counts for both
                   teams, so a player who disconnected doesn't take rounds away from their team.
    rosters        the teams built on the Team page: team name -> players
    skipped        replays that couldn't be read, so they aren't retried until they change (or the
                   app is updated: a newer version may read them)

Every number comes from metrics_engine.compute_match_metrics, exactly what the
scoreboards show. Importing a match again replaces it (a match still being played
gains rounds), so nothing is ever counted twice.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import season_stats
from app_info import APP_VERSION
from metrics_engine import compute_match_metrics

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    match_id    TEXT PRIMARY KEY,
    source      TEXT NOT NULL,     -- the replay folder, e.g. Match-2026-09-25_22-55-04-8956
    files       INTEGER NOT NULL,  -- round files it was read from (a match being played gains more)
    played_at   TEXT,              -- local time, "YYYY-MM-DD HH:MM:SS"
    map         TEXT,
    match_type  TEXT,
    team0       TEXT,
    team1       TEXT,
    score0      INTEGER,
    score1      INTEGER,
    rounds      INTEGER NOT NULL,
    recorder    TEXT,              -- who recorded the replay: "you"
    imported_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS matches_played_at ON matches (played_at);
CREATE INDEX IF NOT EXISTS matches_source ON matches (source);

CREATE TABLE IF NOT EXISTS match_players (
    match_id        TEXT NOT NULL,
    player_key      TEXT NOT NULL,  -- the username, casefolded
    player          TEXT NOT NULL,
    team            INTEGER NOT NULL,
    won             INTEGER,        -- 1 won, 0 lost, NULL a draw
    rounds          INTEGER NOT NULL,
    kills           INTEGER NOT NULL,
    deaths          INTEGER NOT NULL,
    assists         INTEGER NOT NULL,
    headshots       INTEGER NOT NULL,
    entry_kills     INTEGER NOT NULL,
    entry_deaths    INTEGER NOT NULL,
    kost_rounds     INTEGER NOT NULL,
    rounds_survived INTEGER NOT NULL,
    clutches        INTEGER NOT NULL,
    multikills      INTEGER NOT NULL,
    trade_kills     INTEGER NOT NULL,
    traded          INTEGER NOT NULL,  -- deaths a teammate avenged ("dead for trade kill")
    plants          INTEGER NOT NULL,
    defuses         INTEGER NOT NULL,
    rating          REAL NOT NULL,     -- EPS / 100, relative to this match's players
    PRIMARY KEY (match_id, player_key)
);
CREATE INDEX IF NOT EXISTS match_players_player ON match_players (player_key);

CREATE TABLE IF NOT EXISTS round_players (
    match_id    TEXT NOT NULL,
    round       INTEGER NOT NULL,  -- 1, 2, ... in play order
    player_key  TEXT NOT NULL,
    player      TEXT NOT NULL,
    team        INTEGER NOT NULL,
    side        TEXT,              -- 'attack' or 'defense'
    operator    TEXT,
    site        TEXT,
    won         INTEGER,           -- 1 round won, 0 lost
    kills       INTEGER NOT NULL,
    died        INTEGER NOT NULL,
    headshots   INTEGER NOT NULL,
    assists     INTEGER NOT NULL,
    entry_kill  INTEGER NOT NULL,
    entry_death INTEGER NOT NULL,
    traded      INTEGER NOT NULL,
    trade_kills INTEGER NOT NULL,
    planted     INTEGER NOT NULL,
    defused     INTEGER NOT NULL,
    kost        INTEGER NOT NULL,
    clutch      INTEGER,           -- size of a clutch won (1 = 1v1, ...), NULL if none
    PRIMARY KEY (match_id, round, player_key)
);
CREATE INDEX IF NOT EXISTS round_players_player ON round_players (player_key);

CREATE TABLE IF NOT EXISTS team_rounds (
    match_id TEXT NOT NULL,
    round    INTEGER NOT NULL,  -- 1, 2, ... in play order
    team     INTEGER NOT NULL,
    side     TEXT,              -- 'attack' or 'defense'
    won      INTEGER,           -- 1 round won, 0 lost, NULL if the replay doesn't say
    planted  INTEGER NOT NULL,  -- the defuser was planted this round (by the attackers)
    man_down INTEGER NOT NULL,  -- this team was two or more players down at some point
    PRIMARY KEY (match_id, round, team)
);

CREATE TABLE IF NOT EXISTS rosters (
    team       TEXT NOT NULL COLLATE NOCASE,
    player     TEXT NOT NULL,
    player_key TEXT NOT NULL,
    PRIMARY KEY (team, player_key)
);

CREATE TABLE IF NOT EXISTS skipped (
    source TEXT PRIMARY KEY,
    files  INTEGER NOT NULL,
    reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stats_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _insert(table: str, columns: str) -> str:
    """An INSERT naming its columns, so a database made by an earlier version (with a column
    since dropped) still takes new rows."""
    names = columns.split()
    return f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})"


_INSERT_MATCH = _insert("matches", "match_id source files played_at map match_type team0 team1 score0 score1 "
                                   "rounds recorder imported_at")
_INSERT_PLAYER = _insert("match_players", "match_id player_key player team won rounds kills deaths assists "
                                          "headshots entry_kills entry_deaths kost_rounds rounds_survived clutches "
                                          "multikills trade_kills traded plants defuses rating")
_INSERT_ROUND = _insert("round_players", "match_id round player_key player team side operator site won kills "
                                         "died headshots assists entry_kill entry_death traded trade_kills "
                                         "planted defused kost clutch")
_INSERT_TEAM_ROUND = _insert("team_rounds", "match_id round team side won planted man_down")
DATA_VERSION = 2  # 2: team_rounds. Matches read by an earlier version are read again, if their replays remain
# how a round ends once the defuser is down, even when the kill feed missed the plant itself
_PLANTED_ENDINGS = {"DefusedBomb", "DisabledDefuser"}
_MATCH_FOLDER_TIME = re.compile(r"Match-(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})")


def default_path() -> Path:
    """The database file: next to the season tracker's (read at call time, so tests can move it)."""
    return Path(season_stats.DEFAULT_DB_PATH)


def played_at_from_folder(source: str) -> str | None:
    """"Match-2026-09-25_22-55-04-8956" -> "2026-09-25 22:55:04" (the game names folders by local time)."""
    found = _MATCH_FOLDER_TIME.search(source)
    if not found:
        return None
    y, mo, d, h, mi, s = found.groups()
    return f"{y}-{mo}-{d} {h}:{mi}:{s}"


def nice_time(stamp: str | None) -> str:
    """"2026-09-25 22:55:04" -> "Sep 25, 10:55 PM" (with the year when it isn't this year)."""
    try:
        d = datetime.strptime(stamp or "", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return stamp or ""
    return f"{nice_day(stamp)}, {d.hour % 12 or 12}:{d:%M} {'AM' if d.hour < 12 else 'PM'}"


def nice_day(stamp: str | None) -> str:
    """"2026-09-25..." -> "Sep 25" (with the year when it isn't this year); "2026-09" -> "Sep 2026"."""
    text = stamp or ""
    try:
        if len(text) == 7:
            return f"{datetime.strptime(text, '%Y-%m'):%b %Y}"
        d = datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return text
    return f"{d:%b} {d.day}" + (f", {d.year}" if d.year != datetime.now().year else "")


def team_rounds(match: dict[str, Any]) -> list[tuple[int, int, str | None, int | None, int, int]]:
    """(round, team, side, won, planted, man_down) for both teams in every round of a match.
    Man down: while both teams still had someone alive, the team had two or more fewer players
    alive than the other one (from the start, if it began a round short)."""
    team_of = {p["name"]: p["team"] for p in match.get("players") or []}
    rows = []
    for index, rnd in enumerate(match.get("rounds") or [], 1):
        present = [n for n in (rnd.get("players") or team_of) if n in team_of]
        alive = {side: {n for n in present if team_of[n] == side} for side in (0, 1)}
        down = {0: False, 1: False}
        planted = rnd.get("win_condition") in _PLANTED_ENDINGS

        def check() -> None:
            if alive[0] and alive[1]:  # once a team is wiped out the round is over
                for side in (0, 1):
                    down[side] = down[side] or len(alive[side]) <= len(alive[1 - side]) - 2

        check()
        for event in rnd.get("events") or []:
            if event.get("type") == "death" and event.get("actor") in alive[0] | alive[1]:
                alive[team_of[event["actor"]]].discard(event["actor"])
                check()
            elif event.get("type") == "plant":
                planted = True
        attack, winner = rnd.get("attack_team"), rnd.get("winner_team")
        for team in (0, 1):
            rows.append((index, team, None if attack not in (0, 1) else ("attack" if team == attack else "defense"),
                         None if winner not in (0, 1) else int(winner == team), int(planted), int(down[team])))
    return rows


class StatsDB:
    """The stats database. Use as a context manager, or call close()."""

    def __init__(self, path: str | Path | None = None):
        path = default_path() if path is None else path
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Streamlit may run a session's reruns on different threads; each page opens its own
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(SCHEMA)
            # replays an earlier version couldn't read are tried again: this one may read them
            seen = self._conn.execute("SELECT value FROM stats_meta WHERE key = 'version'").fetchone()
            if not seen or seen[0] != APP_VERSION:
                self._conn.execute("DELETE FROM skipped")
                self._conn.execute("INSERT OR REPLACE INTO stats_meta VALUES ('version', ?)", (APP_VERSION,))
            # matches read before a table was added are read again, once, wherever their replays still are
            data = self._conn.execute("SELECT value FROM stats_meta WHERE key = 'data'").fetchone()
            if not data or int(data[0]) < DATA_VERSION:
                self._conn.execute("UPDATE matches SET files = 0 WHERE match_id NOT IN "
                                   "(SELECT DISTINCT match_id FROM team_rounds)")
                self._conn.execute("INSERT OR REPLACE INTO stats_meta VALUES ('data', ?)", (str(DATA_VERSION),))

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "StatsDB":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------------------------------------------------------- importing ----

    def imported(self) -> dict[str, int]:
        """{replay folder: round files it was read from} for every match in the database,
        plus the replays that couldn't be read (so they're only retried once they change)."""
        rows = self._conn.execute("SELECT source, files FROM matches UNION ALL SELECT source, files FROM skipped")
        found: dict[str, int] = {}
        for r in rows:
            found[r["source"]] = max(found.get(r["source"], 0), r["files"])
        return found

    def needs_import(self, groups: dict[str, list[str]]) -> list[str]:
        """The matches in `groups` ({folder: round files}) that are new, or have gained rounds."""
        done = self.imported()
        return [name for name, recs in groups.items() if done.get(name, -1) < len(recs)]

    def import_match(self, source: str, match: dict[str, Any], files: int = 0) -> str | None:
        """Add (or replace) a parsed match (parser.parse_match's MatchData) read from the replay
        folder `source`; returns its match id, or None if it was skipped. A recording with no
        players (an aborted one) is skipped, and when two folders hold the same match, the one
        with more rounds is kept, whichever is imported first."""
        match_id = str(match.get("match_id") or "")
        if not match_id or match_id == "unknown":
            match_id = f"folder:{source}"
        rounds = match.get("rounds") or []
        if not match.get("players"):
            self.skip(source, files, "no players in this recording")
            return None
        other = self._conn.execute("SELECT source, files, rounds FROM matches WHERE match_id = ? AND source != ?",
                                   (match_id, source)).fetchone()
        if other and other["rounds"] >= len(rounds):
            self.skip(source, files, f"the same match as {other['source']}, which has more of it")
            return None
        stats = compute_match_metrics(match)
        score = list(match.get("final_score") or [0, 0]) + [0, 0]
        team_names = list(match.get("team_names") or []) + ["", ""]

        player_rows = []
        for name, s in stats.items():
            if not s.rounds_played:
                continue
            won = None if score[0] == score[1] else int(score[s.team] > score[1 - s.team])
            player_rows.append((
                match_id, name.casefold(), name, s.team, won, s.rounds_played, s.kills, s.deaths, s.assists,
                s.headshots, s.entry_kills, s.entry_deaths, s.kost_rounds, s.rounds_survived, s.total_clutches,
                s.multikill_rounds, s.trade_kills, s.trades, s.plants, s.defuses, s.rating,
            ))

        # compute_match_metrics gives each player one breakdown per round they were in, in play
        # order; walk the rounds the same way to line each breakdown up with its round
        team_of = {p["name"]: p["team"] for p in match.get("players", [])}
        # a replay without each round's picks still shows who played one operator all match
        only_operator = {p["name"]: p["operator_history"][0] for p in match.get("players", [])
                         if len(p.get("operator_history") or []) == 1}
        breakdowns = {name: iter(s.round_breakdown) for name, s in stats.items()}
        round_rows = []
        for index, rnd in enumerate(rounds, 1):
            attack, winner = rnd.get("attack_team"), rnd.get("winner_team")
            operators = rnd.get("operators") or only_operator
            for name in [n for n in (rnd.get("players") or team_of) if n in team_of]:
                rb = next(breakdowns[name], None)
                if rb is None:
                    continue
                team = team_of[name]
                round_rows.append((
                    match_id, index, name.casefold(), name, team,
                    None if attack not in (0, 1) else ("attack" if team == attack else "defense"),
                    operators.get(name), rnd.get("site") or None,
                    None if winner not in (0, 1) else int(winner == team),
                    rb.kills, rb.deaths, rb.headshots, rb.assists, int(rb.entry_kill), int(rb.entry_death),
                    int(rb.traded), rb.trade_kills, int(rb.planted), int(rb.defused), int(rb.kost),
                    int(rb.clutch[-1]) if rb.clutch else None,
                ))

        now = datetime.now().isoformat(timespec="seconds")
        with self._conn:  # one transaction: a match is either fully in or not at all
            # replace this match, and anything imported from the same folder under another id
            old = {r[0] for r in self._conn.execute(
                "SELECT match_id FROM matches WHERE match_id = ? OR source = ?", (match_id, source))}
            for mid in old | {match_id}:
                for table in ("team_rounds", "round_players", "match_players", "matches"):
                    self._conn.execute(f"DELETE FROM {table} WHERE match_id = ?", (mid,))
            self._conn.execute("DELETE FROM skipped WHERE source = ?", (source,))
            if other:  # this folder has more of the match than the one imported before: that one is skipped now
                self._conn.execute("INSERT OR REPLACE INTO skipped VALUES (?, ?, ?)",
                                   (other["source"], other["files"],
                                    f"the same match as {source}, which has more of it"))
            self._conn.execute(_INSERT_MATCH, (
                match_id, source, files, played_at_from_folder(source) or match.get("played_at"), match.get("map"),
                match.get("match_type"), team_names[0], team_names[1], score[0], score[1], len(rounds),
                match.get("recording_player"), now,
            ))
            self._conn.executemany(_INSERT_PLAYER, player_rows)
            self._conn.executemany(_INSERT_ROUND, round_rows)
            self._conn.executemany(_INSERT_TEAM_ROUND, [(match_id, *row) for row in team_rounds(match)])
        return match_id

    def skip(self, source: str, files: int, reason: str) -> None:
        """Remember a replay that couldn't be read, so it isn't retried until it changes."""
        with self._conn:
            self._conn.execute("INSERT OR REPLACE INTO skipped VALUES (?, ?, ?)", (source, files, reason[:500]))

    # ------------------------------------------------------------ rosters ----

    def save_roster(self, team: str, players: list[str]) -> None:
        """Keep a team built on the Team page (replacing an earlier one with the same name)."""
        team = team.strip()
        with self._conn:
            self._conn.execute("DELETE FROM rosters WHERE team = ?", (team,))
            self._conn.executemany("INSERT OR IGNORE INTO rosters VALUES (?, ?, ?)",
                                   [(team, p.strip(), p.strip().casefold()) for p in players if p.strip()])

    def delete_roster(self, team: str) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM rosters WHERE team = ?", (team,))

    def rosters(self) -> dict[str, list[str]]:
        """{team: [players]} in the order they were saved."""
        found: dict[str, list[str]] = {}
        for r in self._conn.execute("SELECT team, player FROM rosters ORDER BY team COLLATE NOCASE, rowid"):
            found.setdefault(r["team"], []).append(r["player"])
        return found

    # ------------------------------------------------------------ reading ----

    def query(self, sql: str, params: tuple | list | dict = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self._conn.execute(sql, params)]

    def summary(self) -> dict[str, Any]:
        """How much is in the database: matches, players, and the first and last match."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS matches, MIN(played_at) AS first, MAX(played_at) AS last FROM matches"
        ).fetchone()
        players = self._conn.execute("SELECT COUNT(DISTINCT player_key) FROM match_players").fetchone()[0]
        return {"matches": row["matches"], "players": players, "first": row["first"], "last": row["last"]}

    def me(self) -> str | None:
        """The player who recorded most of the replays: the app's user."""
        row = self._conn.execute(
            "SELECT recorder, COUNT(*) AS n FROM matches WHERE recorder IS NOT NULL "
            "GROUP BY recorder COLLATE NOCASE ORDER BY n DESC, MAX(played_at) DESC LIMIT 1"
        ).fetchone()
        return row["recorder"] if row else None

    def players(self) -> dict[str, str]:
        """{player_key: username as last seen} for everyone in the database."""
        rows = self._conn.execute(
            "SELECT mp.player_key, mp.player FROM match_players mp JOIN matches m USING (match_id) "
            "ORDER BY m.played_at"
        )
        return {r["player_key"]: r["player"] for r in rows}  # later matches overwrite earlier spellings

    def distinct(self, column: str) -> list[str]:
        """Every value of matches.map / matches.match_type / round_players.operator / .site in the data."""
        table = {"map": "matches", "match_type": "matches",
                 "operator": "round_players", "site": "round_players"}[column]
        rows = self._conn.execute(f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL ORDER BY 1")
        return [r[0] for r in rows]

    def teammates(self, player: str, limit: int = 4) -> list[tuple[str, int]]:
        """The players who were on `player`'s team most often: [(username, matches together)]."""
        rows = self._conn.execute(
            """SELECT o.player_key, COUNT(*) AS n FROM match_players me
               JOIN match_players o ON o.match_id = me.match_id AND o.team = me.team AND o.player_key != me.player_key
               WHERE me.player_key = ? GROUP BY o.player_key ORDER BY n DESC, o.player_key LIMIT ?""",
            (player.casefold(), limit),
        )
        names = self.players()
        return [(names.get(r["player_key"], r["player_key"]), r["n"]) for r in rows]

    def match_list(self, player: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        """Matches, newest first, with `player`'s result and numbers (if given and in them)."""
        sql = """SELECT m.match_id, m.source, m.played_at, m.map, m.match_type, m.team0, m.team1, m.score0,
                        m.score1, m.rounds, mp.player, mp.team, mp.won, mp.kills, mp.deaths, mp.assists,
                        mp.rounds AS player_rounds, mp.rating
                 FROM matches m LEFT JOIN match_players mp ON mp.match_id = m.match_id AND mp.player_key = ?
                 ORDER BY m.played_at DESC, m.match_id"""
        params: list[Any] = [(player or "").casefold()]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return self.query(sql, params)
