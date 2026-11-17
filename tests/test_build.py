# tests/test_build.py — build snapshot (Agent_Runtime/build.py).
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
