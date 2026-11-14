import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import lc_update  # noqa: E402


def by_name(rows):
    return {name: (status, detail) for name, status, detail in rows}


TESTED = {"claude": "2.1.325", "opencode": "1.19.5", "ollama": "0.40.16"}


class UpdateRowTests(unittest.TestCase):
    def test_update_available_is_a_note(self):
        rows = by_name(lc_update.rows({"claude": "2.1.300"}, {"claude": "2.1.325"}, TESTED))
        status, detail = rows["claude version"]
        self.assertEqual(status, "warn")
        self.assertIn("2.1.300 → 2.1.325", detail)

    def test_up_to_date_is_ok(self):
        rows = by_name(lc_update.rows({"ollama": "0.40.16"}, {"ollama": "0.40.16"}, TESTED))
        self.assertEqual(rows["ollama version"][0], "ok")

    def test_newer_than_tested_is_a_note(self):
        rows = by_name(lc_update.rows({"claude": "2.1.400"}, {"claude": "2.1.400"}, TESTED))
        status, detail = rows["claude version"]
        self.assertEqual(status, "warn")
        self.assertIn("not yet tested with LocalCoder", detail)

    def test_offline_is_not_a_failure(self):
        rows = lc_update.rows({"claude": "2.1.325", "ollama": "0.40.16"},
                              {"claude": None, "ollama": None}, TESTED)
        for name, status, detail in rows:
            self.assertNotEqual(status, "fail", name)
        self.assertIn("couldn't check", by_name(rows)["claude version"][1])

    def test_missing_tool_is_skipped(self):
        rows = by_name(lc_update.rows({"opencode": None}, {"opencode": "1.19.5"}, TESTED))
        self.assertNotIn("opencode version", rows)

    def test_localcoder_behind_remote_is_a_note(self):
        rows = by_name(lc_update.rows({"localcoder": "abc1234"}, {"localcoder": "def5678"}, TESTED))
        self.assertEqual(rows["localcoder version"][0], "warn")


class OutputTests(unittest.TestCase):
    def test_last_line_strips_colour_codes_and_blanks(self):
        self.assertEqual(lc_update._last_line("Upgrading\n\x1b[32mdone 1.19.5\x1b[0m\n\x1b[0m\n"),
                         "done 1.19.5")


class VersionParseTests(unittest.TestCase):
    def test_version_compare_handles_v_prefix_and_suffixes(self):
        self.assertEqual(lc_update.parse("v0.40.16"), lc_update.parse("0.40.16"))
        self.assertEqual(lc_update.parse("2.1.325 (Claude Code)"), (2, 1, 325))
        self.assertEqual(lc_update.parse("ollama version is 0.40.16"), (0, 40, 16))
        self.assertGreater(lc_update.parse("2.1.400"), lc_update.parse("2.1.325"))
        self.assertIsNone(lc_update.parse("unknown"))

    def test_latest_uses_injected_fetch_and_survives_errors(self):
        def fetch(url):
            if "claude-code" in url:
                return {"version": "2.1.330"}
            if "opencode-ai" in url:
                raise OSError("offline")
            return {"tag_name": "v0.41.0"}
        got = lc_update.latest(fetch=fetch, git_remote=lambda: None)
        self.assertEqual(got["claude"], "2.1.330")
        self.assertIsNone(got["opencode"])
        self.assertEqual(got["ollama"], "0.41.0")


if __name__ == "__main__":
    unittest.main()
