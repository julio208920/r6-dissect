import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest
from metrics_engine import compute_match_metrics
from parser import normalize_from_r6_dissect, ReplayParseError
from replay_watch import source_signature
from sample_data import SAMPLE_MATCH
from season_stats import StatsManager


class TeamStorageTest(unittest.TestCase):
    def test_all_counters_persist_and_reimport_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'stats.db'
            with StatsManager(db, 'NECC') as sm:
                sm.add_players([p['name'] for p in SAMPLE_MATCH['players']], 'College')
                sm.log_match(SAMPLE_MATCH)
            with StatsManager(db, 'NECC') as sm:
                self.assertEqual(sm.log_match(SAMPLE_MATCH).rounds_logged, 0)
                self.assertEqual(len(sm.match_history()), 1)
                for name, ps in compute_match_metrics(SAMPLE_MATCH).items():
                    stored = sm.get_player_stats(name).totals
                    for key in ('kills', 'deaths', 'assists', 'headshots', 'trade_kills', 'multikill_rounds', 'plants', 'defuses', 'rounds_played'):
                        self.assertEqual(stored[key], getattr(ps, key), (name, key))
                sm.rebuild_totals()
                self.assertEqual(sm.get_team_stats('College').totals['kills'], sum(p.kills for p in compute_match_metrics(SAMPLE_MATCH).values()))

    def test_old_database_migrates_without_losing_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'old.db'
            with StatsManager(db) as sm:
                sm.add_player('Fabian', 'College')
                sm.log_match(SAMPLE_MATCH)
            with sqlite3.connect(db) as conn:
                conn.execute('ALTER TABLE player_totals DROP COLUMN trade_kills')
                conn.execute('ALTER TABLE player_totals DROP COLUMN multikill_rounds')
                conn.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
            conn.close()
            with StatsManager(db) as sm:
                self.assertGreater(sm.get_player_stats('Fabian').totals['kills'], 0)
                self.assertIn('trade_kills', sm.get_player_stats('Fabian').totals)
                self.assertEqual(len(sm.match_history()), 1)

    def test_nested_replay_change_invalidates_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'match').mkdir()
            rec = root / 'match' / 'R01.rec'
            rec.write_bytes(b'round')
            before = source_signature(root)
            rec.write_bytes(b'completed round')
            self.assertNotEqual(source_signature(root), before)

    def test_mixed_matches_and_duplicate_rounds_rejected(self):
        for rounds in ([{'matchID': 'a', 'roundNumber': 0}, {'matchID': 'b', 'roundNumber': 1}],
                       [{'matchID': 'a', 'roundNumber': 0}, {'matchID': 'a', 'roundNumber': 0}]):
            with self.assertRaises(ReplayParseError):
                normalize_from_r6_dissect({'rounds': rounds})


class HubPageTest(unittest.TestCase):
    def test_select_roster_save_match_and_view_totals(self):
        with mock.patch('app_info.is_loopback', return_value=True):
            at = AppTest.from_file(str(Path(__file__).with_name('app.py')), default_timeout=60).run()
            at.session_state['active_match'] = copy.deepcopy(SAMPLE_MATCH)
            at.session_state['active_match_demo'] = True
            at.switch_page('team_hub.py').run()
            self.assertFalse(at.exception)
            next(x for x in at.text_input if x.label == 'Team name').set_value('NECC Test')
            next(x for x in at.multiselect if x.label.startswith('Select players')).set_value(['Fabian', 'Kanto'])
            next(x for x in at.button if x.label == 'Save roster').click().run()
            self.assertFalse(at.exception)
            next(x for x in at.button if x.label == 'Save match stats').click().run()
            self.assertFalse(at.exception)
            self.assertTrue(any('Saved ' in s.value for s in at.success))
            next(x for x in at.button if x.label == 'Save match stats').click().run()
            self.assertFalse(at.exception)
            self.assertTrue(any('already saved' in s.value for s in at.info))
            self.assertTrue(any(m.value == '2' for m in at.metric if m.label == 'Players'))


if __name__ == '__main__':
    unittest.main()
