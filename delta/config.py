"""Configuration: defaults -> config.yaml -> environment variables.

Secrets: the LLM API key is read ONLY from an environment variable (default DELTA_LLM_API_KEY).
It is never written to config files, the database or the audit log.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "user_name": "Praneet",
    "data_dir": "~/.delta",
    "adapter": "auto",  # auto | windows | mock
    "search_engine": "google",
    "server": {"host": "127.0.0.1", "port": 8765, "open_browser": True},
    "brain": {"mode": "auto"},  # auto = rules first, LLM for everything else | rules = never call an LLM
    "llm": {
        "base_url": "",  # e.g. http://localhost:11434/v1 (Ollama), https://api.openai.com/v1, https://api.groq.com/openai/v1
        "model": "",
        "api_key_env": "DELTA_LLM_API_KEY",
        "timeout_s": 60,
        "max_steps": 6,
        "temperature": 0.2,
        "history_messages": 12,
    },
    "safety": {
        "dry_run": False,
        "allowed_folders": ["~/Desktop", "~/Documents", "~/Downloads", "~/Pictures", "~/Music", "~/Videos"],
        "overrides": {},  # e.g. {close_app: safe}; cannot lower always-confirm tools, can always raise
        "blocked_tools": [],
        "confirm_timeout_s": 120,
        "redact_secrets": True,
        "kill_switch_hotkey": "ctrl+alt+shift+k",
        "shell_whitelist": [
            "ipconfig", "ipconfig /all", "hostname", "whoami", "systeminfo", "tasklist", "date /t", "time /t",
            "git status", "git log --oneline -n 10", "ping -n 4 *", "nslookup *",
        ],
        "shell_blocked_patterns": [
            r"\bformat\b", r"\bdiskpart\b", r"\bbcdedit\b", r"\bcipher\s+/w\b", r"\breg\s+(delete|add|import)\b",
            r"\bdel\s+/[sfq]", r"\brd\s+/s", r"\brmdir\s+/s", r"\brm\s+-rf?\b", r"\bRemove-Item\b.*-Recurse",
            r"\bnet\s+user\b", r"\bnetsh\s+advfirewall\b", r"\bSet-ExecutionPolicy\b", r"\bInvoke-Expression\b|\biex\b",
            r"\bpowershell\b.*-enc", r"\bvssadmin\b", r"\bschtasks\s+/create\b", r"\bsc\s+(delete|config)\b",
            r"\bdowngrade\b", r"curl[^|]*\|\s*(sh|bash|powershell)", r"\bmkfs\b", r"\bdd\s+if=",
        ],
    },
    "vibe": {
        "projects_root": "",  # "" = D:/Vibe on Windows, ~/DeltaProjects elsewhere. MUST be inside safety.allowed_folders.
        "use_llm": True,
        "max_steps": 16,  # tool-calling steps per run
        "llm_timeout_s": 120,
        "command_timeout_s": 180,
        "max_read_chars": 12000,
        "max_file_bytes": 400000,
        "max_changes_per_run": 80,
        "require_git": True,  # refuse to run the agent when no git snapshot is possible
        "python": "",  # e.g. "py -3.12"; "" = find one (py launcher / python3 / python)
        "command_whitelist": None,  # None = built-in list (see delta/vibe/commands.py); a list REPLACES it
        "command_blocked_patterns": None,  # extra regexes that are always refused (added to the built-in ones, never replacing them)
    },
    "scripts": {},  # name -> path of a .bat/.cmd/.ps1/.py you trust; "run script <name>" is then allowed without a prompt
    "apps": {},  # extra app aliases, e.g. {obsidian: "C:/Users/me/AppData/Local/Obsidian/Obsidian.exe"}
    "routines_file": "routines.yaml",
    "voice": {
        "enabled": False,
        "hotkey": "ctrl+alt+space",
        "stt_backend": "auto",  # auto | faster-whisper | google
        "whisper_model": "base.en",
        "speak_replies": True,
        "max_record_s": 15,
    },
}


def deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


class Config:
    def __init__(self, data: dict | None = None, path: Path | None = None):
        self.data: dict[str, Any] = deep_merge(DEFAULTS, data or {})
        self.path = path

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        cur = self.data
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = value

    @property
    def data_dir(self) -> Path:
        p = Path(os.path.expanduser(str(self.get("data_dir")))).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def allowed_folders(self) -> list[Path]:
        return [Path(os.path.expanduser(str(p))) for p in self.get("safety.allowed_folders", [])]

    @property
    def dry_run(self) -> bool:
        return bool(self.get("safety.dry_run"))

    @property
    def llm_api_key(self) -> str:
        return os.environ.get(str(self.get("llm.api_key_env") or "DELTA_LLM_API_KEY"), "")

    @property
    def routines_path(self) -> Path:
        p = Path(os.path.expanduser(str(self.get("routines_file"))))
        if p.is_absolute():
            return p
        for base in (Path.cwd(), self.data_dir):
            if (base / p).exists():
                return base / p
        return self.data_dir / p


def find_config_file(explicit: str | None = None) -> Path | None:
    if explicit:
        return Path(explicit)
    for cand in (Path.cwd() / "config.yaml", Path(os.path.expanduser("~/.delta/config.yaml"))):
        if cand.exists():
            return cand
    return None


def load_config(path: str | Path | None = None, overrides: dict | None = None,
                env: dict | None = None) -> Config:
    env = os.environ if env is None else env
    p = find_config_file(str(path) if path else None)
    data: dict = {}
    if p and Path(p).exists():
        with open(p, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{p}: top level must be a mapping")
    cfg = Config(data, Path(p) if p else None)
    mapping = {
        "DELTA_LLM_BASE_URL": "llm.base_url",
        "DELTA_LLM_MODEL": "llm.model",
        "DELTA_DATA_DIR": "data_dir",
        "DELTA_ADAPTER": "adapter",
    }
    for var, key in mapping.items():
        if env.get(var):
            cfg.set(key, env[var])
    if str(env.get("DELTA_DRY_RUN", "")).lower() in ("1", "true", "yes"):
        cfg.set("safety.dry_run", True)
    for k, v in (overrides or {}).items():
        cfg.set(k, v)
    return cfg
