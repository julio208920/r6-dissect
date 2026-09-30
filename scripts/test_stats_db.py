"""Tests for stats_db.py. Run from the repo root:  python -m unittest discover -s scripts"""

from __future__ import annotations

import copy
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from metrics_engine import compute_match_metrics
from parser import normalize_from_r6_dissect
from sample_data import SAMPLE_MATCH, TEAM0, TEAM1
from stats_db import StatsDB, nice_day, nice_time, played_at_from_folder, team_rounds

SUMMED = {  # match_players column -> PlayerStats attribute
    "rounds": "rounds_played", "kills": "kills", "deaths": "deaths", "assists": "assists", "headshots": "headshots",
    "entry_kills": "entry_kills", "entry_deaths": "entry_deaths", "kost_rounds": "kost_rounds",
    "rounds_survived": "rounds_survived", "clutches": "total_clutches", "multikills": "multikill_rounds",
    "trade_kills": "trade_kills", "traded": "trades", "plants": "plants", "defuses": "defuses",
}


def raw_round(n, winner, attack, feed, operators, recorder="p-a1"):
    """One round of r6-dissect JSON: a1-a5 (team 0) vs b1-b5 (team 1)."""
    players = [{"username": u, "teamIndex": 0 if u[0] == "a" else 1, "profileID": f"p-{u}",
                "operator": {"name": operators.get(u, "Ash" if u[0] == "a" else "Jager"), "id": 1}}
               for u in ("a1", "a2", "a3", "a4", "a5", "b1", "b2", "b3", "b4", "b5")]
    teams = [{"name": "YOUR TEAM", "won": winner == 0, "role": "Attack" if attack == 0 else "Defense"},
             {"name": "ENEMY TEAM", "won": winner == 1, "role": "Attack" if attack == 1 else "Defense"}]
    return {"roundNumber": n, "teams": teams, "players": players, "matchFeedback": feed, "site": "2F Office",
            "map": {"name": "BankY9", "id": 1}, "matchID": "match-1", "timestamp": "2026-09-20T19:00:00Z",
            "matchType": {"name": "Ranked", "id": 2}, "recordingProfileID": recorder}


def kill(clock, killer, target, headshot=False):
    return {"type": {"name": "Kill", "id": 0}, "username": killer, "target": target,
            "headshot": headshot, "timeInSeconds": clock}


def small_match():
    """Two rounds; the replay was recorded by a1."""
    return normalize_from_r6_dissect({"rounds": [
        raw_round(0, 0, 0, [kill(170, "a1", "b1", True), kill(160, "a1", "b2")], {"a1": "Sledge"}),
        raw_round(1, 1, 1, [kill(170, "b3", "a1")], {"a1": "Thermite"}),
    ]})


class TestImport(unittest.TestCase):
    def setUp(self):
        self.db = StatsDB(":memory:")
        self.addCleanup(self.db.close)

    def test_numbers_match_the_scoreboard(self):
        self.db.import_match("Match-2026-09-20_19-00-00-1", SAMPLE_MATCH, files=9)
        stats = compute_match_metrics(SAMPLE_MATCH)
        rows = {r["player"]: r for r in self.db.query("SELECT * FROM match_players")}
        self.assertEqual(set(rows), {n for n, s in stats.items() if s.rounds_played})
        for name, s in stats.items():
            for column, attribute in SUMMED.items():
                self.assertEqual(rows[name][column], getattr(s, attribute), (name, column))
            self.assertAlmostEqual(rows[name]["rating"], s.rating)
            won = SAMPLE_MATCH["final_score"][s.team] > SAMPLE_MATCH["final_score"][1 - s.team]
            self.assertEqual(rows[name]["won"], int(won))

    def test_rounds_add_up_to_the_match(self):
        self.db.import_match("demo", SAMPLE_MATCH)
        per_round = self.db.query(
            "SELECT player, COUNT(*) AS rounds, SUM(kills) AS kills, SUM(died) AS deaths, SUM(headshots) AS hs, "
            "SUM(planted) AS plants, SUM(defused) AS defuses, SUM(kost) AS kost, SUM(trade_kills) AS tk, "
            "SUM(traded) AS traded, SUM(entry_kill) AS ek, SUM(clutch IS NOT NULL) AS clutches "
            "FROM round_players GROUP BY player")
        totals = {r["player"]: r for r in self.db.query("SELECT * FROM match_players")}
        for r in per_round:
            t = totals[r["player"]]
            self.assertEqual((r["rounds"], r["kills"], r["deaths"], r["hs"], r["plants"], r["defuses"], r["kost"],
                              r["tk"], r["traded"], r["ek"], r["clutches"]),
                             (t["rounds"], t["kills"], t["deaths"], t["headshots"], t["plants"], t["defuses"],
                              t["kost_rounds"], t["trade_kills"], t["traded"], t["entry_kills"], t["clutches"]))

    def test_sides_operators_and_who_recorded_it(self):
        match = small_match()
        self.assertEqual((match["recording_player"], match["played_at"], match["match_type"]),
                         ("a1", "2026-09-20 19:00:00", "Ranked"))
        self.db.import_match("Match-2026-09-20_19-00-00-1", match, files=2)
        a1 = self.db.query("SELECT round, side, operator, won, kills, died FROM round_players "
                           "WHERE player_key = 'a1' ORDER BY round")
        self.assertEqual([(r["side"], r["operator"], r["won"], r["kills"], r["died"]) for r in a1],
                         [("attack", "Sledge", 1, 2, 0), ("defense", "Thermite", 0, 0, 1)])
        self.assertEqual(self.db.me(), "a1")
        self.assertEqual(self.db.summary()["matches"], 1)
        self.assertEqual(self.db.distinct("map"), ["Bank"])

    def test_a_replay_without_round_picks_uses_the_one_operator_played(self):
        match = copy.deepcopy(SAMPLE_MATCH)
        for rnd in match["rounds"]:
            del rnd["operators"]  # no per-round picks...
        for player in match["players"]:  # ...and everyone played one operator
            player["operator_history"] = ["Ash" if player["team"] == 0 else "Jager"]
        match["players"][1]["operator_history"] = ["Ash", "Thermite"]  # this one switched: unknown
        self.db.import_match("demo", match)
        rows = self.db.query("SELECT player, operator, COUNT(*) AS n FROM round_players "
                             "WHERE player IN (?, ?, ?) GROUP BY player, operator",
                             (TEAM0[0], TEAM0[1], TEAM1[0]))
        self.assertEqual({(r["player"], r["operator"]) for r in rows},
                         {(TEAM0[0], "Ash"), (TEAM0[1], None), (TEAM1[0], "Jager")})

    def test_match_types_as_the_game_names_them(self):
        for raw, shown in (("Ranked", "Ranked"), ("Unranked", "Unranked"), ("Standard", "Unranked"),
                           ("QuickMatch", "Quick Match"), ("CustomGameOnline", "Custom game"),
                           ("CustomGameLocal", "Custom game"), ("MatchType(7)", None)):
            rnd = raw_round(0, 0, 0, [], {})
            rnd["matchType"] = {"name": raw, "id": 0}
            self.assertEqual(normalize_from_r6_dissect({"rounds": [rnd]})["match_type"], shown, raw)

    def test_a_database_from_an_earlier_version_still_takes_matches(self):
        self.db._conn.executescript(  # an earlier schema: a matches column since dropped
            "DROP TABLE matches; CREATE TABLE matches (match_id TEXT PRIMARY KEY, source TEXT NOT NULL, "
            "files INTEGER NOT NULL, played_at TEXT, map TEXT, mode TEXT, match_type TEXT, team0 TEXT, team1 TEXT, "
            "score0 INTEGER, score1 INTEGER, rounds INTEGER NOT NULL, recorder TEXT, imported_at TEXT NOT NULL);")
        self.assertEqual(self.db.import_match("demo", SAMPLE_MATCH), SAMPLE_MATCH["match_id"])
        self.assertEqual(self.db.summary()["matches"], 1)

    def test_team_rounds(self):
        a, b = ["a1", "a2", "a3", "a4", "a5"], ["b1", "b2", "b3", "b4", "b5"]
        players = [{"name": n, "team": 0 if n[0] == "a" else 1, "operator_history": []} for n in a + b]

        def rnd(deaths, winner=0, attack=0, win_condition="KilledOpponents", present=None, plant=False):
            events = [{"type": "death", "actor": n, "time": 100 - i} for i, n in enumerate(deaths)]
            if plant:
                events.append({"type": "plant", "actor": None, "time": 50})
            return {"round_num": 0, "players": present or a + b, "winner_team": winner, "attack_team": attack,
                    "win_condition": win_condition, "events": events}

        match = {"players": players, "rounds": [
            rnd(["a1", "a2", "b1"], winner=1),                     # team 0 was 3v5: man down, and lost
            rnd(["a1", "a2", "b1", "b2", "b3", "b4", "b5"]),       # 3v5, then came back and won
            rnd(["b1", "a1", "b2", "a2", "a3", "b3", "b4", "b5"], winner=0),  # never 2 down while both alive
            rnd([], winner=1, win_condition="DisabledDefuser"),   # planted: no plant event, but the ending says so
            rnd(["a2"], winner=0, plant=True, present=a[1:] + b),  # a1 disconnected, a2 died: 3v5, still a round
            rnd([], winner=None, attack=None),                     # a round the replay can't place
        ]}
        rows = {(r, t): tuple(rest) for r, t, *rest in team_rounds(match)}
        self.assertEqual(len(rows), 12)  # both teams, every round
        self.assertEqual([rows[r, 0][3] for r in range(1, 7)], [1, 1, 0, 0, 1, 0])  # team 0 man down
        self.assertEqual([rows[r, 1][3] for r in range(1, 7)], [0, 1, 0, 0, 0, 0])  # 1v3 during the comeback
        self.assertEqual([rows[r, 0][2] for r in range(1, 7)], [0, 0, 0, 1, 1, 0])  # planted
        # back to even after being man down: 3v5 back to 3v3 in the comeback; team 1 went 1v3 and was wiped out
        self.assertEqual([rows[r, 0][4] for r in range(1, 7)], [0, 1, 0, 0, 0, 0])
        self.assertEqual([rows[r, 1][4] for r in range(1, 7)], [0, 0, 0, 0, 0, 0])
        self.assertEqual(rows[1, 0][:2], ("attack", 0))
        self.assertEqual(rows[1, 1][:2], ("defense", 1))
        self.assertEqual(rows[6, 0][:2], (None, None))

    def test_a_database_from_before_team_rounds_reads_its_matches_again(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "stats.db"
            with StatsDB(path) as db:
                db.import_match("Match-1", SAMPLE_MATCH, files=3)
                db._conn.execute("DELETE FROM team_rounds")  # as 1.3.1 left it
                db._conn.execute("DELETE FROM stats_meta WHERE key = 'data'")
                db._conn.commit()
            with StatsDB(path) as db:
                self.assertEqual(db.needs_import({"Match-1": ["r1", "r2", "r3"]}), ["Match-1"])
                db.import_match("Match-1", SAMPLE_MATCH, files=3)
                self.assertEqual(db.query("SELECT COUNT(*) AS n FROM team_rounds")[0]["n"], 2 * len(SAMPLE_MATCH["rounds"]))
            with StatsDB(path) as db:  # only once
                self.assertEqual(db.needs_import({"Match-1": ["r1", "r2", "r3"]}), [])

    def test_importing_again_replaces_never_doubles(self):
        self.db.import_match("demo", SAMPLE_MATCH, files=5)
        self.db.import_match("demo", SAMPLE_MATCH, files=9)
        self.assertEqual(self.db.summary()["matches"], 1)
        self.assertEqual(self.db.query("SELECT COUNT(*) AS n FROM match_players")[0]["n"], len(TEAM0 + TEAM1))
        self.assertEqual(self.db.imported(), {"demo": 9})

    def test_what_needs_importing(self):
        self.db.import_match("m1", SAMPLE_MATCH, files=3)
        self.db.skip("broken", 2, "not a replay")
        groups = {"m1": ["r1", "r2", "r3"], "m2": ["r1"], "grown": ["r1"], "broken": ["r1", "r2"]}
        self.assertEqual(self.db.needs_import(groups), ["m2", "grown"])
        groups["m1"].append("r4")  # the match gained a round since
        self.assertIn("m1", self.db.needs_import(groups))

    def test_the_same_match_in_two_folders_keeps_the_fuller_one_in_any_order(self):
        # seen in real replays: an aborted recording shares its match id with the real match after it
        stub = copy.deepcopy(SAMPLE_MATCH)
        stub["rounds"] = stub["rounds"][:1]
        for order in (("stub", "full"), ("full", "stub")):
            with self.subTest(order=order), StatsDB(":memory:") as db:
                for name in order:
                    db.import_match(name, stub if name == "stub" else SAMPLE_MATCH, files=1 if name == "stub" else 9)
                self.assertEqual([r["source"] for r in db.query("SELECT source FROM matches")], ["full"])
                self.assertEqual(db.query("SELECT SUM(rounds) AS r FROM match_players")[0]["r"],
                                 sum(s.rounds_played for s in compute_match_metrics(SAMPLE_MATCH).values()))
                # and neither folder is imported again
                self.assertEqual(db.needs_import({"stub": ["r1"], "full": ["r"] * 9}), [])

    def test_a_recording_with_no_players_is_skipped(self):
        empty = dict(copy.deepcopy(SAMPLE_MATCH), players=[])
        self.assertIsNone(self.db.import_match("aborted", empty, files=1))
        self.assertEqual(self.db.summary()["matches"], 0)
        self.assertEqual(self.db.needs_import({"aborted": ["r1"]}), [])

    def test_a_match_without_an_id_uses_its_folder(self):
        match = copy.deepcopy(SAMPLE_MATCH)
        match["match_id"] = "unknown"
        self.assertEqual(self.db.import_match("Match-X", match), "folder:Match-X")

    def test_rosters(self):
        self.db.save_roster("Varsity", ["Fabian", " Kanto ", ""])
        self.db.save_roster("varsity", ["Bosco"])  # same team, any case: replaced
        self.db.save_roster("JV", ["Paluh"])
        self.assertEqual(self.db.rosters(), {"JV": ["Paluh"], "varsity": ["Bosco"]})
        self.db.delete_roster("JV")
        self.assertEqual(list(self.db.rosters()), ["varsity"])

    def test_teammates_and_match_list(self):
        self.db.import_match("demo", SAMPLE_MATCH)
        mates = self.db.teammates(TEAM0[0])
        self.assertEqual(len(mates), 4)
        self.assertTrue(all(name in TEAM0 and n == 1 for name, n in mates))
        rows = self.db.match_list(TEAM0[0])
        self.assertEqual((rows[0]["player"], rows[0]["won"]), (TEAM0[0], 1))

    def test_an_update_tries_skipped_replays_again(self):
        folder = {"Match-1": ["a.rec", "b.rec"]}
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "stats.db"
            with StatsDB(path) as db:
                db.skip("Match-1", 2, "r6-dissect couldn't read it")
                self.assertEqual(db.needs_import(folder), [])
            with StatsDB(path) as db:  # the same version: still skipped
                self.assertEqual(db.needs_import(folder), [])
            with mock.patch("stats_db.APP_VERSION", "99.0.0"), StatsDB(path) as db:  # a newer one may read it
                self.assertEqual(db.needs_import(folder), ["Match-1"])

    def test_folder_times(self):
        self.assertEqual(played_at_from_folder("Match-2026-09-25_22-55-04-8956"), "2026-09-25 22:55:04")
        self.assertIsNone(played_at_from_folder("my upload"))

    def test_a_match_is_dated_by_its_folder_like_the_dashboard_picker(self):
        match = copy.deepcopy(SAMPLE_MATCH)
        match["played_at"] = "2026-09-20 19:01:30"  # when its first round started
        self.db.import_match("Match-2026-09-20_19-00-02-1", match)
        self.db.import_match("an upload", dict(match, match_id="another"))  # no time in the name
        self.assertEqual({r["source"]: r["played_at"] for r in self.db.query("SELECT source, played_at FROM matches")},
                         {"Match-2026-09-20_19-00-02-1": "2026-09-20 19:00:02", "an upload": "2026-09-20 19:01:30"})

    def test_times_as_people_read_them(self):
        year = datetime.now().year
        self.assertEqual(nice_time(f"{year}-09-25 22:55:04"), "Sep 25, 10:55 PM")
        self.assertEqual(nice_time(f"{year}-09-25 00:05:00"), "Sep 25, 12:05 AM")
        self.assertEqual(nice_time(f"{year - 1}-12-31 12:00:00"), f"Dec 31, {year - 1}, 12:00 PM")
        self.assertEqual(nice_day(f"{year}-09-21 18:00:00"), "Sep 21")
        self.assertEqual(nice_day("2026-09"), "Sep 2026")
        self.assertEqual((nice_time(None), nice_day("not a date")), ("", "not a date"))


if __name__ == "__main__":
    unittest.main()
