import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

from pydantic import ValidationError

from business_logic import DataError, Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.db = Path(self.folder.name) / "test.db"
        self.store = Store(self.db)
        self.today = date.today()

    def tearDown(self):
        self.store.engine.dispose()
        self.folder.cleanup()

    def make(self, kind="counter", target=8, period="daily"):
        return self.store.create_tracker("Вода", kind, target, period, "ед.").id

    def log(self, tracker_id, value, offset=0):
        return self.store.add_log(tracker_id, value, (self.today - timedelta(days=offset)).isoformat())

    def test_create_logs_history_progress_and_restart(self):
        self.assertEqual(self.store.get_trackers(), [])
        tracker_id = self.make()
        for _ in range(5):
            current = self.log(tracker_id, 1)
        self.assertEqual(current["current_value"], 5)
        self.assertEqual(current["completion_percent"], 62.5)
        stats = self.store.get_stats(tracker_id)
        self.assertEqual(len(stats["history"]), 5)
        self.assertEqual(stats["by_date"][0]["value"], 5)
        restarted = Store(self.db)
        self.assertEqual(restarted.get_trackers()[0]["current_value"], 5)
        restarted.engine.dispose()
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM log").fetchone()[0], 5)
            self.assertEqual(connection.execute("PRAGMA table_info(log)").fetchall()[0][2], "FLOAT")

    def test_duration_numeric_scale_and_weekly_progress(self):
        duration = self.make("duration", target=30, period="weekly")
        monday = self.today - timedelta(days=self.today.weekday())
        self.store.add_log(duration, 100, (monday - timedelta(days=1)).isoformat())
        self.store.add_log(duration, 30, monday.isoformat())
        self.log(duration, 30)
        self.assertEqual(self.store.get_stats(duration)["current_value"], 60)
        self.assertEqual(self.store.get_stats(duration)["period_target"], 210)
        self.assertEqual(self.store.get_stats(duration)["completion_percent"], 28.57)
        self.assertIsNone(self.store.get_stats(duration)["streak"])
        numeric = self.make("numeric", target=8)
        self.log(numeric, 7.5)
        self.assertEqual(self.store.get_stats(numeric)["completion_percent"], 93.75)
        scale = self.make("scale", target=10)
        self.log(scale, 8)
        self.assertEqual(self.store.get_stats(scale)["completion_percent"], 80)

    def test_boolean_streak_gap_and_cap(self):
        boolean = self.make("boolean", target=1)
        self.log(boolean, 1, offset=4)
        self.log(boolean, 1, offset=2)
        self.log(boolean, 1, offset=1)
        self.assertEqual(self.store.get_stats(boolean)["streak"], 2)
        self.log(boolean, 1)
        self.assertEqual(self.store.get_stats(boolean)["streak"], 3)
        self.log(boolean, 1)
        self.assertEqual(self.store.get_stats(boolean)["completion_percent"], 100)

    def test_reject_invalid_inputs_without_database_writes(self):
        cases = [
            ("", "counter", 8, "daily", "ед."),
            ("Я" * 51, "counter", 8, "daily", "ед."),
            ("Вода", "unknown", 8, "daily", "ед."),
            ("Вода", "counter", 0, "daily", "ед."),
            ("Вода", "counter", "nan", "daily", "ед."),
            ("Вода", "counter", 8, "monthly", "ед."),
            ("Вода", "counter", 8, "daily", "е" * 21),
            ("Чтение", "boolean", 2, "daily", "раз"),
        ]
        for args in cases:
            with self.assertRaises((ValueError, ValidationError)):
                self.store.create_tracker(*args)
        self.assertEqual(self.store.get_trackers(), [])
        tracker_id = self.make()
        for value, day in [("nan", self.today.isoformat()), (-1, self.today.isoformat()), (1, "2026-02-30"), (1, "20261007")]:
            with self.assertRaises((ValueError, ValidationError)):
                self.store.add_log(tracker_id, value, day)
        with self.assertRaises(ValueError):
            self.store.add_log(99999, 1, self.today.isoformat())
        with self.assertRaises(ValueError):
            self.store.get_stats(99999)
        self.assertEqual(self.store.get_stats(tracker_id)["history"], [])

    def test_corrupt_database_shows_error(self):
        broken = Path(self.folder.name) / "broken.db"
        broken.write_bytes(b"not a SQLite database")
        with self.assertRaises(DataError):
            Store(broken)


if __name__ == "__main__":
    unittest.main()
