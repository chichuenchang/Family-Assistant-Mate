# tests/test_build.py — build snapshot (Agent_Runtime/build.py).
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import build


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True,
                          capture_output=True, text=True).stdout


def _write(root: Path, rel: str, text: str = "") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    _write(root, ".codewhale/skills/X/cli.py", "print('hi')\n")
    _write(root, ".codewhale/skills/X/.env", "KEY=1\n")
    _write(root, ".codewhale/skills/X/__pycache__/a.pyc", "junk")
    _write(root, "config.json", '{"data_root": "data"}')
    _write(root, "tests/t.py", "")
    _write(root, ".gitignore", "data/\n__pycache__/\n*.pyc\n**/X/.env\n")
    _write(root, "data/f.txt", "live")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


# ── Task 1: selection / git / gate ──────────────────────────

def test_files_include_untracked_and_ignored_env(repo):
    _write(repo, ".codewhale/skills/X/new.py", "")
    files = build.files_to_copy(repo)
    for want in (".codewhale/skills/X/cli.py", ".codewhale/skills/X/new.py",
                 ".codewhale/skills/X/.env", "config.json"):
        assert want in files
    assert "tests/t.py" not in files
    assert ".gitignore" not in files
    assert "data/f.txt" not in files
    assert not [f for f in files if "__pycache__" in f]


def test_files_keep_non_ascii_names(repo):
    _write(repo, ".codewhale/skills/X/备忘.md", "")
    assert ".codewhale/skills/X/备忘.md" in build.files_to_copy(repo)


def test_git_state_clean_then_dirty(repo):
    st = build.git_state(repo)
    assert st["dirty"] is False and st["dirty_files"] == []
    assert st["commit"]
    _write(repo, ".codewhale/skills/X/cli.py", "print('edited')\n")
    st = build.git_state(repo)
    assert st["dirty"] is True
    assert ".codewhale/skills/X/cli.py" in st["dirty_files"]


def test_check_flags_syntax_error(repo):
    _write(repo, ".codewhale/skills/X/bad.py", "def(:\n")
    assert build.check(repo)


def test_check_flags_undefined_name(repo):
    _write(repo, ".codewhale/skills/X/bad.py", "print(nope)\n")
    assert any("undefined name" in line for line in build.check(repo))


def test_check_passes_clean_tree(repo):
    assert build.check(repo) == []


# ── Task 2: snapshot / latest / main ───────────────────────

STAMP = "20990101-120000"


@pytest.fixture
def builds(tmp_path) -> Path:
    return tmp_path / "builds"


def test_snapshot_layout(repo, builds):
    snap = build.make_snapshot(repo, builds, STAMP)
    assert snap == builds / STAMP
    assert (snap / ".codewhale/skills/X/cli.py").is_file()
    assert (snap / "config.json").is_file()
    assert not (snap / "tests").exists()
    meta = json.loads((snap / "BUILD.json").read_text(encoding="utf-8"))
    assert meta["id"] == STAMP and meta["commit"] and meta["dirty"] is False
    assert os.path.isjunction(snap / "data")
    assert (snap / "data" / "f.txt").read_text() == "live"


def test_snapshot_isolated_from_edits(repo, builds):
    snap = build.make_snapshot(repo, builds, STAMP)
    _write(repo, ".codewhale/skills/X/cli.py", "print('edited')\n")
    assert (snap / ".codewhale/skills/X/cli.py").read_text() == "print('hi')\n"


def test_existing_stamp_raises(repo, builds):
    snap = build.make_snapshot(repo, builds, STAMP)
    with pytest.raises(build.BuildError):
        build.make_snapshot(repo, builds, STAMP)
    assert (snap / "BUILD.json").is_file()


def test_missing_data_raises_no_leftover(repo, builds):
    shutil.rmtree(repo / "data")
    with pytest.raises(build.BuildError):
        build.make_snapshot(repo, builds, STAMP)
    assert not builds.exists() or not any(builds.iterdir())


def test_latest_ignores_tmp_and_incomplete(repo, builds):
    real = build.make_snapshot(repo, builds, STAMP)
    (builds / "20990101-130000.tmp").mkdir()
    (builds / "20990101-130001").mkdir()          # no BUILD.json
    assert build.latest(builds) == real


def test_latest_none_when_empty(builds):
    assert build.latest(builds) is None


def test_main_check_fail_no_snapshot(repo, builds, monkeypatch):
    monkeypatch.setattr(build, "ROOT", repo)
    monkeypatch.setenv("FA_BUILDS_DIR", str(builds))
    _write(repo, ".codewhale/skills/X/bad.py", "def(:\n")
    assert build.main([]) == 1
    assert build.latest(builds) is None


def test_main_builds_and_warns_dirty(repo, builds, monkeypatch, capsys):
    monkeypatch.setattr(build, "ROOT", repo)
    monkeypatch.setenv("FA_BUILDS_DIR", str(builds))
    _write(repo, ".codewhale/skills/X/cli.py", "print('edited')\n")
    assert build.main([]) == 0
    out = capsys.readouterr().out
    assert "WARNING dirty" in out and ".codewhale/skills/X/cli.py" in out
    assert build.latest(builds) is not None
    assert build.main(["--latest"]) == 0
    assert str(build.latest(builds)) in capsys.readouterr().out
