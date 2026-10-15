import pytest

from delta.cli import main


@pytest.fixture
def cfgfile(tmp_path):
    home = tmp_path / "h"
    (home / "Downloads").mkdir(parents=True)
    p = tmp_path / "config.yaml"
    p.write_text(f"data_dir: {tmp_path / 'data'}\nsafety:\n  allowed_folders: ['{home / 'Downloads'}']\n")
    return str(p)


def test_say_runs_a_command(cfgfile, capsys):
    assert main(["--config", cfgfile, "say", "volume", "20"]) == 0
    assert "Volume set to 20%" in capsys.readouterr().out


def test_say_dry_run(cfgfile, capsys):
    main(["--config", cfgfile, "--dry-run", "say", "mute"])
    assert "[dry-run]" in capsys.readouterr().out


def test_say_confirmation_prompt_default_is_no(cfgfile, capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: "")
    main(["--config", cfgfile, "say", "restart"])
    out = capsys.readouterr().out
    assert "Needs your approval" in out and "cancelled" in out.lower()


def test_say_confirmation_yes(cfgfile, capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: "y")
    main(["--config", cfgfile, "say", "restart"])
    assert "Restarting in 30 seconds" in capsys.readouterr().out


def test_tools_and_audit_and_doctor(cfgfile, capsys):
    main(["--config", cfgfile, "say", "volume 10"])
    capsys.readouterr()
    assert main(["--config", cfgfile, "tools"]) == 0
    assert "shutdown_pc" in capsys.readouterr().out
    assert main(["--config", cfgfile, "audit", "--tail", "5"]) == 0
    assert "intact" in capsys.readouterr().out
    assert main(["--config", cfgfile, "doctor"]) == 0
    assert "Adapter" in capsys.readouterr().out
    assert main(["--config", cfgfile, "selftest"]) == 0


def test_audit_command_reports_tampering(cfgfile, capsys, tmp_path):
    main(["--config", cfgfile, "say", "volume 10"])
    main(["--config", cfgfile, "say", "volume 20"])
    log = tmp_path / "data" / "audit.jsonl"
    log.write_text(log.read_text().replace("Volume set to 10", "Volume set to 99"))
    capsys.readouterr()
    assert main(["--config", cfgfile, "audit"]) == 2
    assert "BROKEN" in capsys.readouterr().out


def test_config_env_overrides(tmp_path, monkeypatch):
    from delta.config import load_config
    monkeypatch.setenv("DELTA_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("DELTA_LLM_MODEL", "llama3.1:8b")
    monkeypatch.setenv("DELTA_DRY_RUN", "1")
    cfg = load_config(overrides={"data_dir": str(tmp_path)})
    assert cfg.get("llm.base_url") == "http://localhost:11434/v1" and cfg.get("llm.model") == "llama3.1:8b" and cfg.dry_run
