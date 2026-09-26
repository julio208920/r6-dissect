"""Tests for the Streamlit pages (app.py, report.py, download.py) and app_info.py.
Run from the repo root:  python -m unittest discover -s scripts"""

from __future__ import annotations

import io
import json
import os
import unittest
from pathlib import Path
from unittest import mock

import streamlit as st
from streamlit.testing.v1 import AppTest

import app_info
import necc_data
import parser as replay_parser

APP = str(Path(__file__).with_name("app.py"))


def run_app(local_visitor: bool = True, **env: str) -> AppTest:
    # AppTest has no real visitor IP, and no replay folder is auto-detected,
    # so nothing gets parsed unless a test asks for it
    with mock.patch.dict(os.environ, env), \
            mock.patch.object(app_info, "is_loopback", return_value=local_visitor), \
            mock.patch.object(replay_parser, "find_replay_folders", return_value=[]):
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


class TestAnalyticsPages(unittest.TestCase):
    def test_new_navigation_pages_render_empty_states(self):
        for page in ("history.py", "operators.py", "teams.py", "schools.py"):
            with self.subTest(page=page):
                at = run_app(R6_HOSTED="1")
                at.switch_page(page).run()
                self.assertFalse(at.exception)

    @staticmethod
    def build_team(at: AppTest, team: str, players: list[str]) -> AppTest:
        at.switch_page("teams.py").run()
        at.text_input[0].set_value(team)
        for i, name in enumerate(players):
            at.text_input[1 + i].set_value(name)
        at.slider[0].set_value(2)
        return at.button[0].click().run()

    def test_build_a_team_needs_replays_loaded_first(self):
        at = self.build_team(run_app(R6_HOSTED="1"), "Liquid", ["Fabian"])
        self.assertFalse(at.exception)
        self.assertIn("Dashboard", at.info[0].value)

    def test_build_a_team_from_the_loaded_matches(self):
        from sample_data import SAMPLE_MATCH, TEAM0

        at = run_app(R6_HOSTED="1")
        # what Dashboard keeps for a loaded replay folder, with both matches already parsed
        players = {p["name"]: p["team"] for p in SAMPLE_MATCH["players"]}
        at.session_state["source"] = {"groups": {"m1": ["m1-R01.rec"], "m2": ["m2-R01.rec"]},
                                      "parsed": {n: (SAMPLE_MATCH, {}, []) for n in ("m1", "m2")},
                                      "players": {"m1": players, "m2": players}}
        at = self.build_team(at, "Liquid", TEAM0[:3] + ["Nobody"])
        self.assertFalse(at.exception)
        self.assertEqual({m.label: m.value for m in at.metric}["Matches"], "2")
        table = at.dataframe[0].value
        self.assertEqual(sorted(table["Player"]), sorted(TEAM0[:3]))
        self.assertEqual(set(table["Matches"]), {2})
        self.assertIn("EPS", table.columns)
        self.assertIn("Nobody", at.warning[0].value)

    def test_season_teams_have_an_eps_column(self):
        at = run_app(R6_HOSTED="1")
        at.switch_page("teams.py").run()
        self.assertFalse(at.exception)
        self.assertEqual([t.label for t in at.tabs], ["Build a team", "Season teams"])


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
            mock.patch.object(app_info, "latest_release", **lookup), \
            mock.patch.object(replay_parser, "find_replay_folders", return_value=[]):
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
