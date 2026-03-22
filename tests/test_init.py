from __future__ import annotations

import json
from pathlib import Path

import pytest

from kore.init import cmd_init, cmd_migrate


@pytest.fixture
def kore_home(tmp_path, monkeypatch):
    """Override KORE_HOME to a temp dir for all init tests."""
    import kore.init as init_mod
    import kore.config as config_mod
    home = tmp_path / ".kore"
    monkeypatch.setattr(init_mod, "KORE_HOME", home)
    monkeypatch.setattr(config_mod, "KORE_HOME", home)
    return home


def test_init_creates_directory_structure(kore_home):
    cmd_init()
    assert (kore_home / "config.json").exists()
    assert (kore_home / "jobs.json").exists()
    assert (kore_home / ".env.example").exists()
    assert (kore_home / "workspace" / "skills").is_dir()
    assert (kore_home / "workspace" / "files").is_dir()


def test_init_config_is_valid_json(kore_home):
    cmd_init()
    data = json.loads((kore_home / "config.json").read_text())
    assert "version" in data
    assert "llm" in data


def test_init_jobs_json_is_empty_list(kore_home):
    cmd_init()
    data = json.loads((kore_home / "jobs.json").read_text())
    assert data == {"jobs": []}


def test_init_skips_existing_files(kore_home, capsys):
    """Running init twice warns about existing files but does not overwrite them."""
    cmd_init()
    # Modify config.json to a sentinel value
    (kore_home / "config.json").write_text('{"sentinel": true}')

    cmd_init()

    # File must not be overwritten
    data = json.loads((kore_home / "config.json").read_text())
    assert data == {"sentinel": True}

    # Warning must be printed
    captured = capsys.readouterr()
    assert "skipping" in captured.out.lower() or "exists" in captured.out.lower()


def test_init_workspace_dirs_safe_to_repeat(kore_home):
    """Running init multiple times on an existing ~/.kore never errors."""
    cmd_init()
    cmd_init()   # must not raise


def test_migrate_prints_nothing_to_migrate(kore_home, capsys):
    cmd_migrate()
    captured = capsys.readouterr()
    assert "nothing to migrate" in captured.out.lower()
