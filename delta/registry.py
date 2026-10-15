"""Tool registry: every capability is a Tool with a JSON schema, a permission level and a handler."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Callable


class Level(str, enum.Enum):
    SAFE = "safe"        # runs immediately
    CONFIRM = "confirm"  # needs an explicit yes from the user (UI button, typed or spoken)
    BLOCKED = "blocked"  # never runs


@dataclass
class ToolResult:
    ok: bool
    text: str
    data: dict = field(default_factory=dict)


def ok(message: str, /, **data: Any) -> ToolResult:
    return ToolResult(True, message, data)


def fail(message: str, /, **data: Any) -> ToolResult:
    return ToolResult(False, message, data)


class ArgError(ValueError):
    pass


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict                       # JSON schema (type: object)
    handler: Callable[..., ToolResult]     # handler(ctx, **args) -> ToolResult
    level: Level = Level.SAFE
    category: str = "general"
    side_effects: bool = True              # False = read-only (still runs in dry-run mode)
    always_confirm: bool = False           # config can never lower this tool below CONFIRM
    untrusted_output: bool = False         # output is text from the outside world (web/files): it taints the context
    taint_sensitive: bool = False          # SAFE normally, but CONFIRM when the request came after untrusted content
    classify: Callable[[Any, dict], Level] | None = None   # per-call level (e.g. dangerous file types, shell commands)
    describe: Callable[[Any, dict], str] | None = None     # human sentence for the confirmation card
    audit_hide_args: tuple[str, ...] = ()  # args that are logged as "<n chars>" instead of their value
    expose_to_llm: bool = True

    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.parameters}}

    def describe_call(self, ctx: Any, args: dict) -> str:
        if self.describe:
            try:
                return self.describe(ctx, args)
            except PermissionError:   # e.g. SandboxError: the engine must see it and refuse the request
                raise
            except Exception:         # any other failure must never break the gate
                pass
        shown = ", ".join(f"{k}={v!r}" for k, v in args.items())
        return f"{self.name}({shown})"


def obj(props: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props or {}, "required": required or [], "additionalProperties": False}


S = {"type": "string"}
I = {"type": "integer"}
N = {"type": "number"}
B = {"type": "boolean"}


def validate_args(schema: dict, args: Any) -> dict:
    """Small JSON-schema subset validator + gentle coercion (LLMs often send "5" for 5)."""
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ArgError("arguments must be an object")
    props = schema.get("properties", {})
    out: dict = {}
    for k in schema.get("required", []):
        if k not in args:
            raise ArgError(f"missing required argument '{k}'")
    for k, v in args.items():
        if k not in props:
            raise ArgError(f"unknown argument '{k}'")
        t = props[k].get("type")
        try:
            if t == "string":
                if not isinstance(v, (str, int, float)):
                    raise ValueError
                v = str(v)
            elif t == "integer":
                if isinstance(v, bool):
                    raise ValueError
                v = int(float(v)) if isinstance(v, (str, int, float)) else (_ for _ in ()).throw(ValueError())
            elif t == "number":
                if isinstance(v, bool):
                    raise ValueError
                v = float(v)
            elif t == "boolean":
                if isinstance(v, str):
                    if v.lower() not in ("true", "false"):
                        raise ValueError
                    v = v.lower() == "true"
                elif not isinstance(v, bool):
                    raise ValueError
            elif t == "array" and not isinstance(v, list):
                raise ValueError
            elif t == "object" and not isinstance(v, dict):
                raise ValueError
        except (ValueError, TypeError):
            raise ArgError(f"argument '{k}' must be of type {t}")
        if "enum" in props[k] and v not in props[k]["enum"]:
            raise ArgError(f"argument '{k}' must be one of {props[k]['enum']}")
        if "minimum" in props[k] and isinstance(v, (int, float)) and v < props[k]["minimum"]:
            raise ArgError(f"argument '{k}' must be >= {props[k]['minimum']}")
        if "maximum" in props[k] and isinstance(v, (int, float)) and v > props[k]["maximum"]:
            raise ArgError(f"argument '{k}' must be <= {props[k]['maximum']}")
        out[k] = v
    return out


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool {tool.name}")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return sorted(self._tools.values(), key=lambda t: (t.category, t.name))

    def names(self) -> list[str]:
        return sorted(self._tools)

    def llm_schemas(self) -> list[dict]:
        return [t.schema() for t in self.all() if t.expose_to_llm]
