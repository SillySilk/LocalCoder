"""Version and update checks (from the hardening work; Ollama dropped)."""

import lc_update

TESTED = {"claude": "2.1.325", "opencode": "1.19.5"}


def by_name(rows):
    return {name: (status, detail) for name, status, detail in rows}


def rows(have, newest, tested=TESTED, git_has=lambda c: False):
    return by_name(lc_update.rows(have, newest, tested, git_has=git_has))


def test_update_available_is_a_note():
    status, detail = rows({"claude": "2.1.300"}, {"claude": "2.1.325"})["claude version"]
    assert status == "warn" and "2.1.300 → 2.1.325" in detail


def test_up_to_date_is_ok():
    assert rows({"opencode": "1.19.5"}, {"opencode": "1.19.5"})["opencode version"][0] == "ok"


def test_newer_than_tested_is_a_note():
    status, detail = rows({"claude": "2.1.400"}, {"claude": "2.1.400"})["claude version"]
    assert status == "warn" and "not yet tested with LocalCoder" in detail


def test_offline_is_not_a_failure():
    got = lc_update.rows({"claude": "2.1.325"}, {"claude": None}, TESTED, git_has=lambda c: False)
    assert all(status != "fail" for _, status, _ in got)
    assert "couldn't check" in by_name(got)["claude version"][1]


def test_missing_tool_is_skipped():
    assert "opencode version" not in rows({"opencode": None}, {"opencode": "1.19.5"})


def test_unreadable_tested_version_does_not_crash():
    got = rows({"claude": "2.1.325"}, {"claude": "2.1.325"}, tested={"claude": "garbage"})
    assert got["claude version"][0] == "ok"


def test_localcoder_behind_github_is_a_note():
    got = rows({"localcoder": "abc1234"}, {"localcoder": "def5678"}, git_has=lambda c: False)
    assert got["localcoder version"][0] == "warn"


def test_localcoder_ahead_of_github_is_not_told_to_update():
    status, detail = rows({"localcoder": "abc1234"}, {"localcoder": "def5678"},
                          git_has=lambda c: True)["localcoder version"]
    assert status == "ok" and "ahead" in detail


def test_last_line_strips_colour_codes_and_blanks():
    assert lc_update._last_line("Upgrading\n\x1b[32mdone 1.19.5\x1b[0m\n\x1b[0m\n") == "done 1.19.5"


def test_version_parse_handles_prefixes_and_suffixes():
    assert lc_update.parse("v2.1.325") == lc_update.parse("2.1.325")
    assert lc_update.parse("2.1.325 (Claude Code)") == (2, 1, 325)
    assert lc_update.parse("2.1.400") > lc_update.parse("2.1.325")
    assert lc_update.parse("unknown") is None


def test_latest_uses_injected_fetch_and_survives_errors():
    def fetch(url):
        if "claude-code" in url:
            return {"version": "2.1.330"}
        raise OSError("offline")
    got = lc_update.latest(fetch=fetch, git_remote=lambda: None)
    assert got["claude"] == "2.1.330" and got["opencode"] is None
    assert "ollama" not in got
