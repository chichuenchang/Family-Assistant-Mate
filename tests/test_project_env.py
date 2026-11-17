"""project_env：.codewhale/.env 读入 os.environ（文件优先）、upsert、Windows 迁移。"""
import os

import pytest

import project_env


@pytest.fixture(autouse=True)
def _restore_environ():
    """load/set_key/import_windows 写 os.environ：每测后还原，键不漏进别的测试。"""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


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


def test_load_missing_file_noop(tmp_path):
    assert project_env.load(tmp_path / "nope.env") == []


def test_set_key_creates_file(tmp_path):
    f = tmp_path / "sub" / ".env"
    assert project_env.set_key("FAM_T_NEW", "v1", f) == f
    assert project_env.parse(f.read_text(encoding="utf-8")) == {"FAM_T_NEW": "v1"}
    assert os.environ["FAM_T_NEW"] == "v1"


def test_set_key_replaces_in_place(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# head\nA=1\nFAM_T_X=old\nB=2\n", encoding="utf-8")
    project_env.set_key("FAM_T_X", "new", f)
    assert f.read_text(encoding="utf-8") == "# head\nA=1\nFAM_T_X=new\nB=2\n"


def test_env_path_override(tmp_path, monkeypatch):
    monkeypatch.setenv(project_env.ENV_FILE_VAR, str(tmp_path / "x.env"))
    assert project_env.env_path() == tmp_path / "x.env"
    monkeypatch.delenv(project_env.ENV_FILE_VAR)
    assert project_env.env_path().parts[-2:] == (".codewhale", ".env")


def test_import_selects_known_and_suffix(tmp_path):
    f = tmp_path / ".env"
    hkcu = {"DEEPSEEK_API_KEY": "sk", "LLM_EFFORT": "max", "ALICE_GMAIL_REFRESH_TOKEN": "rt",
            "Path": "C:/x", "TEMP": "C:/t", "OneDrive": "C:/o", "EMPTY_API_KEY": "", "OTHER_AGENT_API_KEY": "x"}
    names = project_env.import_windows(f, read=lambda: hkcu)
    assert sorted(names) == ["ALICE_GMAIL_REFRESH_TOKEN", "DEEPSEEK_API_KEY", "LLM_EFFORT"]
    assert project_env.parse(f.read_text(encoding="utf-8")) == {
        "DEEPSEEK_API_KEY": "sk", "LLM_EFFORT": "max", "ALICE_GMAIL_REFRESH_TOKEN": "rt"}


def test_import_keeps_existing_file_value(tmp_path):
    f = tmp_path / ".env"
    f.write_text("DEEPSEEK_API_KEY=mine\nZHIPU_API_KEY=\n", encoding="utf-8")
    names = project_env.import_windows(
        f, read=lambda: {"DEEPSEEK_API_KEY": "old", "ZHIPU_API_KEY": "z"})
    assert names == ["ZHIPU_API_KEY"]
    assert project_env.parse(f.read_text(encoding="utf-8")) == {
        "DEEPSEEK_API_KEY": "mine", "ZHIPU_API_KEY": "z"}
