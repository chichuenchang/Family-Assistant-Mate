"""project_env：.codewhale/.env 读入 os.environ（文件优先）、upsert、Windows 迁移。"""
import os

import project_env


def test_parse_bom_comments_quotes():
    text = "﻿A=1\r\n# c\nB = \"two\"\nC=\n\nnoequals\n"
    assert project_env.parse(text) == {"A": "1", "B": "two"}


def test_load_overrides_env(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("FAM_T_KEY=from_file\nFAM_T_EMPTY=\n", encoding="utf-8")
    monkeypatch.setenv("FAM_T_KEY", "from_windows")
    monkeypatch.setenv("FAM_T_EMPTY", "kept")
    assert project_env.load(f) == ["FAM_T_KEY"]
    assert os.environ["FAM_T_KEY"] == "from_file"
    assert os.environ["FAM_T_EMPTY"] == "kept"      # 空值不覆盖
    monkeypatch.delenv("FAM_T_KEY")


def test_load_missing_file_noop(tmp_path):
    assert project_env.load(tmp_path / "nope.env") == []


def test_set_key_creates_file(tmp_path, monkeypatch):
    f = tmp_path / "sub" / ".env"
    monkeypatch.delenv("FAM_T_NEW", raising=False)
    assert project_env.set_key("FAM_T_NEW", "v1", f) == f
    assert project_env.parse(f.read_text(encoding="utf-8")) == {"FAM_T_NEW": "v1"}
    assert os.environ["FAM_T_NEW"] == "v1"
    monkeypatch.delenv("FAM_T_NEW")


def test_set_key_replaces_in_place(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("# head\nA=1\nFAM_T_X=old\nB=2\n", encoding="utf-8")
    monkeypatch.delenv("FAM_T_X", raising=False)
    project_env.set_key("FAM_T_X", "new", f)
    assert f.read_text(encoding="utf-8") == "# head\nA=1\nFAM_T_X=new\nB=2\n"
    monkeypatch.delenv("FAM_T_X")


def test_env_path_override(tmp_path, monkeypatch):
    monkeypatch.setenv(project_env.ENV_FILE_VAR, str(tmp_path / "x.env"))
    assert project_env.env_path() == tmp_path / "x.env"
    monkeypatch.delenv(project_env.ENV_FILE_VAR)
    assert project_env.env_path().parts[-2:] == (".codewhale", ".env")
