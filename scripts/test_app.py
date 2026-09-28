"""Tests for the Streamlit pages (app.py, report.py, download.py) and app_info.py.
Run from the repo root:  python -m unittest discover -s scripts"""

from __future__ import annotations

import copy
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import streamlit as st
from streamlit.testing.v1 import AppTest

import app_info
import necc_data
import parser as replay_parser
import season_stats

APP = str(Path(__file__).with_name("app.py"))
_DB_FOLDER = tempfile.mkdtemp()
_PATCHES = [
    # the pages' stats database: a throwaway one, never this PC's real one
    mock.patch.object(season_stats, "DEFAULT_DB_PATH", Path(_DB_FOLDER) / "stats.db"),
    # and no replay folder is found on this PC, so nothing's parsed unless a test asks for it
    mock.patch.object(replay_parser, "find_replay_folders", return_value=[]),
]


def setUpModule():
    for patch in _PATCHES:
        patch.start()


def tearDownModule():
    for patch in _PATCHES:
        patch.stop()
    shutil.rmtree(_DB_FOLDER, ignore_errors=True)


def run_app(local_visitor: bool = True, **env: str) -> AppTest:
    # AppTest has no real visitor IP; env and the visitor apply to this first run only
    with mock.patch.dict(os.environ, env), \
            mock.patch.object(app_info, "is_loopback", return_value=local_visitor):
        at = AppTest.from_file(APP, default_timeout=60)
        at.run()
    return at


class TestReportPage(unittest.TestCase):
    def test_local_visitor_can_read_folders(self):
        at = run_app()
        self.assertFalse(at.exception)
        self.assertEqual(at.radio[0].options, ["Folder or zip on this computer", "Upload", "From the replays/ folder"])

    def test_public_site_only_takes_uploads(self):
        at = run_app(R6_HOSTED="1")
        self.assertFalse(at.exception)
        self.assertEqual(len(at.radio), 0)  # no folder paths on a public server
        self.assertEqual(len(at.text_input), 0)

    def test_remote_visitor_only_uploads_even_off_a_known_host(self):
        at = run_app(local_visitor=False)
        self.assertEqual(len(at.radio), 0)
        self.assertEqual(len(at.text_input), 0)

    def test_windows_app_has_no_replays_folder_option(self):
        at = run_app(R6_DESKTOP="1")
        self.assertEqual(at.radio[0].options, ["Folder or zip on this computer", "Upload"])

    def test_demo_match_can_be_downloaded_as_csv_json_and_txt(self):
        at = run_app(R6_HOSTED="1")
        at.toggle[0].set_value(True).run()
        buttons = at.get("download_button")
        self.assertEqual([b.proto.label for b in buttons], ["⬇ CSV", "⬇ JSON", "⬇ TXT"])
        self.assertEqual([Path(b.proto.url).suffix for b in buttons], [".csv", ".json", ".txt"])

    @staticmethod
    def tracker(at: AppTest):
        """The season tracker's roster team, team name and players widgets."""
        name = next(t for t in at.text_input if str(t.key).startswith("r6_tracker_team_name"))
        players = next(m for m in at.multiselect if str(m.key).startswith("r6_tracker_players"))
        return at.selectbox(key="r6_tracker_team"), name, players

    def test_season_tracker_follows_the_selected_team(self):
        from sample_data import SAMPLE_MATCH

        at = run_app(R6_HOSTED="1")
        at.toggle[0].set_value(True).run()
        team, name, players = self.tracker(at)
        team.set_value(1).run()
        team, name, players = self.tracker(at)
        self.assertEqual(name.value, SAMPLE_MATCH["team_names"][1])  # not the other team's name
        self.assertEqual(sorted(players.value), sorted(p["name"] for p in SAMPLE_MATCH["players"] if p["team"] == 1))

    def test_season_tracker_never_offers_a_replays_generic_label_as_the_team(self):
        from sample_data import SAMPLE_MATCH

        generic = {**SAMPLE_MATCH, "team_names": ["YOUR TEAM", "ENEMY TEAM"]}
        with mock.patch.object(replay_parser, "load_demo_match", return_value=generic):
            at = run_app(R6_HOSTED="1")
            at.toggle[0].set_value(True).run()
        self.assertFalse(at.exception)
        self.assertEqual(self.tracker(at)[1].value, "")  # asks for the real name instead

    def test_demo_match_renders_both_scoreboards(self):
        at = run_app(R6_HOSTED="1")
        at.toggle[0].set_value(True).run()
        self.assertFalse(at.exception)
        tables = [m.value for m in at.markdown if 'class="pl"' in m.value]
        self.assertEqual(len(tables), 2)
        self.assertIn("Team Liquid", tables[0])


class TestOperatorNormalization(unittest.TestCase):
    def test_operator_data_is_preserved_per_round(self):
        raw = {"rounds": [
            {"roundNumber": 1, "players": [{"username": "Player", "teamIndex": 0,
                                               "operator": {"name": "Ash"}}]},
            {"roundNumber": 2, "players": [{"username": "Player", "teamIndex": 0,
                                               "operator": {"name": "Sledge"}}]},
        ]}
        match = replay_parser.normalize_from_r6_dissect(raw)
        self.assertEqual(match["players"][0]["operator_history"], ["Ash", "Sledge"])
        self.assertEqual(match["rounds"][0]["operators"], {"Player": "Ash"})


class TestSchoolCatalog(unittest.TestCase):
    def test_normalizes_school_roster_and_filters_other_games(self):
        schools = necc_data.normalize_school_catalog({"schools": [{
            "name": "North University",
            "teams": [
                {"name": "Varsity", "game": "Rainbow Six Siege", "roster": ["Ash", {"username": "Thermite"}]},
                {"name": "Overwatch", "game": "Overwatch", "roster": ["Tracer"]},
            ],
        }]})
        self.assertEqual(schools[0]["teams"][0]["roster"], ["Ash", "Thermite"])
        self.assertEqual([team["name"] for team in schools[0]["teams"]], ["Varsity"])

    def test_rejects_catalog_without_schools(self):
        with self.assertRaises(ValueError):
            necc_data.normalize_school_catalog({"schools": []})


def with_matches(at: AppTest, count: int = 2) -> AppTest:
    """Give the session a replay source of `count` demo matches (Fabian recorded them), already
    parsed, the way Dashboard leaves it after loading a folder."""
    from sample_data import SAMPLE_MATCH

    parsed = {}
    for i in range(count):
        match = copy.deepcopy(SAMPLE_MATCH)
        match.update(match_id=f"demo-{i}", played_at=f"2026-09-2{i} 20:00:00", recording_player="Fabian",
                     match_type="Ranked")
        parsed[f"Match-2026-09-2{i}_20-00-00-1"] = (match, {}, [])
    at.session_state["source"] = {"sig": ("upload", "test"), "workdir": tempfile.mkdtemp(), "parsed": parsed,
                                  "groups": {n: [f"{n}-R01.rec"] for n in parsed}, "skipped": None}
    return at


class TestAnalyticsPages(unittest.TestCase):
    """The pages that read the stats database, run as in the Windows app (on this PC)."""

    def setUp(self):
        patch = mock.patch.object(season_stats, "DEFAULT_DB_PATH", Path(tempfile.mkdtemp(dir=_DB_FOLDER)) / "stats.db")
        patch.start()
        self.addCleanup(patch.stop)  # every test starts with an empty database

    def test_pages_without_matches_say_where_to_start(self):
        for page in ("ask.py", "history.py", "operators.py", "teams.py", "schools.py", "appearance.py"):
            with self.subTest(page=page):
                at = run_app()
                at.switch_page(page).run()
                self.assertFalse(at.exception)
                if page not in ("schools.py", "appearance.py"):
                    self.assertTrue(any("No matches yet" in i.value for i in at.info), page)

    def test_ask_answers_about_the_loaded_matches(self):
        from metrics_engine import compute_match_metrics
        from sample_data import SAMPLE_MATCH

        at = with_matches(run_app())
        at.switch_page("ask.py").run()
        at.text_input(key="ask_question").set_value("who has the most kills?")
        at = next(b for b in at.button if b.label == "Ask").click().run()
        self.assertFalse(at.exception)
        best = max(compute_match_metrics(SAMPLE_MATCH).values(), key=lambda s: s.kills)
        self.assertEqual(best.name, "Fabian")  # who recorded the demo matches, so "you"
        headline = next(m.value for m in at.markdown if m.value.startswith("#### "))
        # the same match twice: twice the kills
        self.assertEqual(headline, f"#### You have the most kills: {2 * best.kills} (2 matches).")
        self.assertEqual(len(at.dataframe), 1)

    def test_ask_example_buttons(self):
        at = with_matches(run_app())
        at.switch_page("ask.py").run()
        at = next(b for b in at.button if "best map" in b.label.lower()).click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.text_input(key="ask_question").value, "What's my best map?")
        self.assertTrue(any(m.value.startswith("#### ") for m in at.markdown))

    def test_match_history_lists_every_match(self):
        at = with_matches(run_app(), count=3)
        at.switch_page("history.py").run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.dataframe[0].value), 3)
        self.assertEqual({m.label: m.value for m in at.metric}["Matches"], "3")

    def test_build_a_team_starts_with_you_and_your_teammates(self):
        from sample_data import TEAM0

        at = with_matches(run_app())
        at.switch_page("teams.py").run()
        players = [at.text_input(key=f"roster_New team_{i}").value for i in range(5)]
        self.assertEqual(players[0], "Fabian")
        self.assertEqual(sorted(players), sorted(TEAM0))  # Fabian's four teammates fill the rest

    def test_build_a_team(self):
        from metrics_engine import compute_match_metrics
        from sample_data import SAMPLE_MATCH

        at = with_matches(run_app())
        at.switch_page("teams.py").run()
        players = [at.text_input(key=f"roster_New team_{i}").value for i in range(4)]
        at.text_input(key="team_name_New team").set_value("Liquid")
        at.text_input(key="roster_New team_4").set_value("Nobody")  # four of the team, and one stranger
        at = next(b for b in at.button if b.label == "Show team stats").click().run()
        self.assertFalse(at.exception)
        metrics = {m.label: m.value for m in at.metric}
        self.assertEqual(metrics["Maps"], "2")
        self.assertNotIn("Team EPS", metrics)  # a team's numbers are its own, never its players' added up
        rounds = len(SAMPLE_MATCH["rounds"])
        won = sum(r["winner_team"] == 0 for r in SAMPLE_MATCH["rounds"])  # Fabian's team is team 0
        self.assertEqual(metrics["Round W–L"], f"{2 * won}–{2 * (rounds - won)}")  # each round once
        situations = at.dataframe[0].value
        self.assertEqual(list(situations.columns), ["Situation", "%", "Rounds"])
        self.assertEqual(len(situations), 7)
        # the man-down rows after the first are out of the man-down rounds only
        went_down = int(situations["Rounds"][0].split(" of ")[0])
        self.assertTrue(situations["Rounds"][1].endswith(f" of {went_down}"))
        self.assertTrue(situations["Rounds"][2].endswith(f" of {went_down}"))
        table = at.dataframe[1].value
        self.assertEqual(sorted(table["Player"]), sorted(players))
        self.assertEqual(set(table["Matches"]), {2})
        eps = {p: round(100 * s.rating) for p, s in compute_match_metrics(SAMPLE_MATCH).items()}
        self.assertEqual(dict(zip(table["Player"], table["All-time EPS"])), {p: str(eps[p]) for p in players})
        self.assertIn("Nobody", at.warning[0].value)
        self.assertEqual(at.selectbox(key="team_choice").value, "Liquid")  # saved, and Ask knows it now

    def test_operators_over_all_matches(self):
        from metrics_engine import compute_match_metrics
        from sample_data import SAMPLE_MATCH

        at = with_matches(run_app())
        at.switch_page("operators.py").run()
        self.assertFalse(at.exception)
        self.assertEqual(at.selectbox[0].value, "fabian")  # you come first
        table = at.dataframe[0].value
        rounds = compute_match_metrics(SAMPLE_MATCH)["Fabian"].rounds_played
        self.assertEqual(dict(zip(table["Operator"], table["Rounds"])), {"Ash": 2 * rounds})

    def test_operators_in_the_open_match(self):
        from sample_data import SAMPLE_MATCH, TEAM0, TEAM1

        at = run_app()
        at.switch_page("operators.py").run()
        at = at.segmented_control[0].set_value("This match").run()
        self.assertIn("No matches yet", at.info[0].value)
        # before a match is opened on the Dashboard: the newest one
        at = with_matches(at).run()
        self.assertFalse(at.exception)
        self.assertIn("newest match", at.caption[0].value)
        picks = {r["Operator"]: r["Picks"] for r in at.dataframe[0].value.to_dict("records")}
        rounds = len(SAMPLE_MATCH["rounds"])
        self.assertEqual(picks, {"Ash": rounds * len(TEAM0), "Jager": rounds * len(TEAM1)})
        at.session_state["r6_last_match"] = SAMPLE_MATCH  # opened on the Dashboard
        at = at.run()
        self.assertFalse(any("newest match" in c.value for c in at.caption))

    def test_track_a_school_roster(self):
        from necc_data import normalize_school_catalog
        from season_stats import StatsManager

        at = run_app()
        at.session_state["necc_schools"] = normalize_school_catalog({"schools": [{"name": "Test U", "teams": [
            {"name": "Varsity", "game": "Rainbow Six Siege", "roster": ["_Sniper_", "Bravo"]}]}]})
        at.switch_page("schools.py").run()
        at = next(b for b in at.button if b.label == "Track this roster").click().run()
        self.assertFalse(at.exception)
        self.assertIn("Added 2 players to Varsity", at.success[0].value)
        with StatsManager() as manager:  # this test's own database, not a real one
            self.assertEqual(sorted(manager.tracked_players()), ["Bravo", "_Sniper_"])

    def test_season_teams_are_team_stats_and_eps_is_worked_out_again(self):
        from metrics_engine import compute_match_metrics
        from sample_data import SAMPLE_MATCH, TEAM0
        from season_stats import StatsManager

        at = with_matches(run_app())
        with StatsManager(season="current") as tracker:
            tracker.add_players(TEAM0, team="Squad")
            for match, _raw, _warnings in at.session_state["source"]["parsed"].values():
                tracker.log_match(match)
            tracker._conn.execute("DELETE FROM match_ratings")  # saved before the tracker kept EPS
            tracker._conn.commit()
        at.switch_page("teams.py").run()
        self.assertFalse(at.exception)
        self.assertEqual({m.label: m.value for m in at.metric}["Maps"], "2")
        roster = at.dataframe[1].value
        eps = {p: str(round(100 * s.rating)) for p, s in compute_match_metrics(SAMPLE_MATCH).items()}
        self.assertEqual(dict(zip(roster["Player"], roster["EPS"])), {p: eps[p] for p in TEAM0})  # not "—"
        self.assertEqual(dict(zip(roster["Player"], roster["All-time EPS"])), {p: eps[p] for p in TEAM0})
        teams = at.dataframe[2].value
        self.assertIn("Back to even %", teams.columns)
        self.assertNotIn("K/D", teams.columns)

    def test_season_teams_tab(self):
        at = run_app()
        at.switch_page("teams.py").run()
        self.assertFalse(at.exception)
        self.assertEqual([t.label for t in at.tabs], ["Build a team", "Season teams"])


class TestStatsSync(unittest.TestCase):
    """sources.sync_stats_db: every replay of a folder into the stats database."""

    def test_a_replay_that_fails_is_skipped_and_the_rest_are_added(self):
        from sample_data import SAMPLE_MATCH
        from sources import sync_stats_db
        from stats_db import StatsDB

        def parse_match(recs):
            if recs == ["b.rec"]:
                raise KeyError("roundNumber")  # read by r6-dissect, but not the way this app expects
            if recs == ["c.rec"]:
                raise replay_parser.ReplayParseError("r6-dissect couldn't read it")
            return dict(SAMPLE_MATCH, match_id=recs[0]), {}, []

        groups = {"Match-2026-09-20_19-00-00-1": ["a.rec"], "Match-2026-09-21_19-00-00-2": ["b.rec"],
                  "Match-2026-09-22_19-00-00-3": ["c.rec"]}
        state = {"groups": groups, "parsed": {}}
        with StatsDB(":memory:") as db, mock.patch("sources.parse_match", side_effect=parse_match):
            self.assertEqual(sync_stats_db(state, db), 1)
            self.assertEqual(db.summary()["matches"], 1)
            skipped = {r["source"]: r["reason"] for r in db.query("SELECT source, reason FROM skipped")}
            self.assertEqual(sorted(skipped), ["Match-2026-09-21_19-00-00-2", "Match-2026-09-22_19-00-00-3"])
            self.assertIn("roundNumber", skipped["Match-2026-09-21_19-00-00-2"])
            self.assertEqual(sync_stats_db(state, db), 0)  # and they aren't tried again on every page


class TestMatchLabels(unittest.TestCase):
    def test_names_show_as_written_in_markdown(self):
        from ui import md

        self.assertEqual(md("_Sniper_"), r"\_Sniper\_")  # not an italic "Sniper"
        self.assertEqual(md("Rook-_- has 3 kills"), r"Rook-\_- has 3 kills")
        self.assertEqual(md("Paltry.FBRD: 67% (3 matches)."), "Paltry.FBRD: 67% (3 matches).")

    def test_labels(self):
        from sources import match_label
        from stats_db import nice_time

        name = "Match-2026-09-25_22-55-04-8956"  # the Dashboard's picker, before the match is imported
        self.assertEqual(match_label(name), nice_time("2026-09-25 22:55:04"))
        row = {"played_at": "2026-09-25 22:55:04", "map": "Bank", "team": 1, "score0": 2, "score1": 4, "won": 1}
        self.assertEqual(match_label(name, row), f"{nice_time('2026-09-25 22:55:04')} · Bank · Won 4–2")
        self.assertEqual(match_label("my upload"), "my upload")


class TestWindowsAppBundle(unittest.TestCase):
    """The Windows app ships the pages as plain files, listed in desktop/R6MatchStats.spec, and
    PyInstaller can't see what plain files import: anything missing only fails in the installed app."""

    def test_every_file_and_module_the_pages_need_is_bundled(self):
        import ast
        import re
        import sys

        scripts = Path(__file__).resolve().parent
        spec = (scripts.parent / "desktop" / "R6MatchStats.spec").read_text(encoding="utf-8")
        files = set(re.findall(r'"(\w+\.py)"', spec.split("datas")[0]))
        stdlib = set(re.findall(r'"([\w.]+)"', spec.split("standard library")[1].split("]")[0]))
        local = {p.name for p in scripts.glob("*.py")}
        needed, imports, todo = set(), set(), ["app.py"]
        while todo:
            name = todo.pop()
            if name in needed:
                continue
            needed.add(name)
            source = (scripts / name).read_text(encoding="utf-8")
            found = set(re.findall(r'st\.Page\("(\w+\.py)"', source))
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Import):
                    imports |= {a.name for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    imports.add(node.module)
            found |= {m.split(".")[0] + ".py" for m in imports}
            todo += [f for f in found & local if f not in needed]
        self.assertEqual(sorted(needed - files), [])
        used = {m for m in imports if m.split(".")[0] in sys.stdlib_module_names} - {"__future__"}
        self.assertEqual(sorted(used - stdlib), [])


RELEASE = {"version": "9.9.0", "url": "https://github.com/o/r/releases/tag/v9.9.0",
           "installer": "https://github.com/o/r/releases/download/v9.9.0/R6MatchStats-Setup.exe",
           "zip": "https://github.com/o/r/releases/download/v9.9.0/R6MatchStats-Windows.zip"}


def download_page(release, **env: str) -> AppTest:
    """The download page, with GitHub's newest release mocked: a dict, None (no
    release yet) or an OSError (GitHub unreachable)."""
    st.cache_data.clear()
    lookup = {"side_effect": release} if isinstance(release, Exception) else {"return_value": release}
    with mock.patch.dict(os.environ, env), \
            mock.patch.object(app_info, "is_loopback", return_value=True), \
            mock.patch.object(app_info, "latest_release", **lookup):
        at = AppTest.from_file(APP, default_timeout=60)
        at.run()
        at.switch_page("download.py").run()
    return at


def links(at: AppTest) -> list[str]:
    return [b.proto.url for b in at.get("link_button")]


class TestDownloadPage(unittest.TestCase):
    def test_links_to_the_newest_installer(self):
        at = download_page(RELEASE, R6_HOSTED="1")
        self.assertFalse(at.exception)
        self.assertEqual(links(at), [RELEASE["installer"]])
        self.assertIn(RELEASE["zip"], " ".join(c.value for c in at.caption))

    def test_no_release_yet_says_so_instead_of_a_broken_link(self):
        at = download_page(None, R6_HOSTED="1")
        self.assertFalse(at.exception)
        self.assertEqual(len(at.warning), 1)
        self.assertNotIn(app_info.WINDOWS_DOWNLOAD_URL, links(at))

    def test_github_unreachable_falls_back_to_the_latest_release_link(self):
        at = download_page(OSError("offline"), R6_HOSTED="1")
        self.assertFalse(at.exception)
        self.assertEqual(links(at), [app_info.WINDOWS_DOWNLOAD_URL])
        self.assertTrue(app_info.WINDOWS_DOWNLOAD_URL.endswith("/releases/latest/download/" + app_info.WINDOWS_INSTALLER))

    def test_windows_app_offers_a_newer_version(self):
        at = download_page(RELEASE, R6_DESKTOP="1")
        self.assertFalse(at.exception)
        self.assertEqual(links(at), [RELEASE["installer"]])
        self.assertIn("9.9.0", at.info[0].value)

    def test_windows_app_up_to_date(self):
        at = download_page({**RELEASE, "version": app_info.APP_VERSION}, R6_DESKTOP="1")
        self.assertEqual(links(at), [])
        self.assertEqual(len(at.info), 0)


class TestLatestRelease(unittest.TestCase):
    def fetch(self, releases):
        response = mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(json.dumps(releases).encode())
        with mock.patch("urllib.request.urlopen", return_value=response):
            return app_info.latest_release("o/r")

    @staticmethod
    def release(tag, *assets, **flags):
        return {"tag_name": tag, "html_url": f"https://github.com/o/r/releases/tag/{tag}", **flags,
                "assets": [{"name": a, "browser_download_url": f"https://dl/{tag}/{a}"} for a in assets]}

    def test_skips_releases_without_the_app_drafts_and_prereleases(self):
        found = self.fetch([
            self.release("v3.0.0", "R6MatchStats-Setup.exe", prerelease=True),
            self.release("v2.1.0", "r6-dissect-windows-amd64.zip"),
            self.release("v2.0.0", "R6MatchStats-Setup.exe", "R6MatchStats-Windows.zip"),
        ])
        self.assertEqual(found["version"], "2.0.0")
        self.assertEqual(found["installer"], "https://dl/v2.0.0/R6MatchStats-Setup.exe")
        self.assertEqual(found["zip"], "https://dl/v2.0.0/R6MatchStats-Windows.zip")

    def test_no_releases(self):
        self.assertIsNone(self.fetch([]))

    def test_version_order(self):
        self.assertGreater(app_info.version_tuple("1.10.0"), app_info.version_tuple("1.9.2"))
        self.assertEqual(app_info.version_tuple("1.0"), (1, 0))

    def test_any_tag_style_gives_the_version(self):
        for tag in ("v1.2.0", "V1.2.0", "app-v1.2.0", "1.2.0", "release-1.2.0"):
            self.assertEqual(app_info.release_version(tag), "1.2.0", tag)
        self.assertGreater(app_info.version_tuple("app-v1.2.0"), app_info.version_tuple("1.1.9"))

    def test_published_checksum(self):
        digest = "a" * 64
        releases = io.BytesIO(json.dumps([self.release("v2.0.0", "R6MatchStats-Setup.exe", "SHA256SUMS.txt")]).encode())
        sums = io.BytesIO(f"{digest}  R6MatchStats-Setup.exe\n{'b' * 64}  R6MatchStats-Windows.zip\n".encode())
        responses = []
        for body in (releases, sums):
            response = mock.MagicMock()
            response.__enter__.return_value = body
            responses.append(response)
        with mock.patch("urllib.request.urlopen", side_effect=responses):
            self.assertEqual(app_info.latest_release("o/r")["sha256"], digest)


class TestAppInfo(unittest.TestCase):
    def test_loopback(self):
        for ip in (None, "127.0.0.1", "::1", "::ffff:127.0.0.1"):
            self.assertTrue(app_info.is_loopback(ip), ip)
        for ip in ("10.0.0.5", "::ffff:34.12.1.9", "2001:db8::1", "not an ip"):
            self.assertFalse(app_info.is_loopback(ip), ip)

    def test_repo_override(self):
        with mock.patch.dict(os.environ, {"R6_GITHUB_REPO": "someone/r6-stats"}):
            self.assertEqual(app_info.github_repo(), "someone/r6-stats")


if __name__ == "__main__":
    unittest.main()
