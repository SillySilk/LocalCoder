import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import lc_launch  # noqa: E402
from fakes import FakeOllama, show  # noqa: E402


class CheckTests(unittest.TestCase):
    def run_with(self, models, version="0.40.16"):
        fake = FakeOllama(models=models, version=version)
        old = lc_launch.OLLAMA
        lc_launch.OLLAMA = fake.url
        try:
            return {name: (status, detail) for name, status, detail in lc_launch.run_checks()}
        finally:
            lc_launch.OLLAMA = old
            fake.close()

    def test_check_reports_ollama_version(self):
        rows = self.run_with({})
        status, detail = rows["Ollama"]
        self.assertEqual(status, "ok")
        self.assertIn("0.40.16", detail)

    def test_check_flags_old_ollama(self):
        status, detail = self.run_with({}, version="0.30.1")["Ollama"]
        self.assertEqual(status, "fail")
        self.assertIn("0.40", detail)

    def test_check_flags_model_without_tools(self):
        status, detail = self.run_with({"chatty": show(caps=("completion",))})["model chatty"]
        self.assertEqual(status, "warn")
        self.assertIn("no tool use", detail)

    def test_check_flags_small_context(self):
        status, detail = self.run_with({"small": show(num_ctx=4096)})["model small"]
        self.assertEqual(status, "warn")
        self.assertIn("4k", detail)

    def test_check_passes_ready_model(self):
        status, _ = self.run_with({"ready": show()})["model ready"]
        self.assertEqual(status, "ok")

    def test_check_relay_roundtrip(self):
        status, detail = self.run_with({})["relay"]
        self.assertEqual(status, "ok", detail)

    def test_check_exit_ignores_warnings(self):
        self.assertTrue(lc_launch.checks_passed([("a", "ok", ""), ("b", "warn", "")]))
        self.assertFalse(lc_launch.checks_passed([("a", "ok", ""), ("b", "fail", "")]))


if __name__ == "__main__":
    unittest.main()
