from __future__ import annotations

from ..registry import I, Level, Tool, ToolRegistry, fail, obj, ok, S
from ..safety import PROTECTED_PROCESSES
from ..util import fmt_bytes, fmt_duration

SECTIONS = ["all", "cpu", "memory", "disk", "battery", "network"]


def system_info(ctx, section: str = "all"):
    a = ctx.adapter
    lines: list[str] = []
    data: dict = {}
    if section in ("all", "cpu"):
        data["cpu"] = a.cpu_percent()
        lines.append(f"CPU: {data['cpu']:.0f}% in use")
    if section in ("all", "memory"):
        m = a.memory()
        data["memory"] = m
        lines.append(f"Memory: {fmt_bytes(m['used'])} of {fmt_bytes(m['total'])} ({m['percent']:.0f}%)")
    if section in ("all", "disk"):
        d = a.disks()
        data["disks"] = d
        for x in d[:4]:
            lines.append(f"Disk {x['mount']}: {fmt_bytes(x['used'])} of {fmt_bytes(x['total'])} used ({x['percent']:.0f}%)")
    if section in ("all", "battery"):
        b = a.battery()
        data["battery"] = b
        if b:
            left = f", about {fmt_duration(b['secs_left'])} left" if (not b['plugged'] and isinstance(b.get('secs_left'), int) and b['secs_left'] > 0) else ""
            lines.append(f"Battery: {b['percent']}% ({'charging' if b['plugged'] else 'on battery'}{left})")
        elif section == "battery":
            lines.append("No battery detected (desktop PC?).")
    if section in ("all", "network"):
        n = a.network()
        data["network"] = n
        ips = ", ".join(f"{x['ip']} ({x['interface']})" for x in n["addresses"][:3]) or "no network address"
        lines.append(f"Network: {ips}; sent {fmt_bytes(n['bytes_sent'])}, received {fmt_bytes(n['bytes_recv'])} since boot")
    return ok("\n".join(lines), **data)


def top_processes(ctx, sort_by: str = "memory", limit: int = 6):
    rows = ctx.adapter.processes(limit, sort_by)
    return ok(f"Top processes by {sort_by}:\n" + "\n".join(f"• {r['name']} (pid {r['pid']}): {r['memory']}% RAM, {r['cpu']}% CPU" for r in rows), processes=rows)


def _resolve_target(ctx, target: str) -> list[dict]:
    t = str(target).strip()
    if t.isdigit():
        return [{"pid": int(t), "name": ctx.adapter.process_name(int(t))}]
    return ctx.adapter.find_pids(t)


def _describe_kill(ctx, args):
    procs = _resolve_target(ctx, args["target"])
    names = ", ".join(sorted({str(p.get("name") or f"pid {p['pid']}") for p in procs})) or "no matching process"
    return f"Force-stop {args['target']} ({len(procs)} process(es): {names}); unsaved work in it is lost"


def _classify_kill(ctx, args):
    for p in _resolve_target(ctx, args["target"]):
        if (p.get("name") or "").lower() in PROTECTED_PROCESSES:
            return Level.BLOCKED
    if str(args["target"]).strip().lower() in PROTECTED_PROCESSES:
        return Level.BLOCKED
    return Level.CONFIRM


def kill_process(ctx, target: str):
    procs = _resolve_target(ctx, target)
    if not procs:
        return fail(f"No running process matches “{target}”.")
    killed = [ctx.adapter.kill_pid(p["pid"]) for p in procs[:20]]
    return ok(f"Stopped {len(killed)} process(es): {', '.join(sorted(set(killed)))}.")


def register(reg: ToolRegistry) -> None:
    reg.register(Tool("system_info", "CPU, memory, disk, battery and network status.", obj({"section": {**S, "enum": SECTIONS}}), system_info,
                      category="sysinfo", side_effects=False))
    reg.register(Tool("top_processes", "Which processes use the most memory or CPU.", obj({"sort_by": {**S, "enum": ["memory", "cpu"]}, "limit": {**I, "minimum": 1, "maximum": 25}}),
                      top_processes, category="sysinfo", side_effects=False))
    reg.register(Tool("kill_process", "Force-stop a process by name or pid (always asks; critical Windows processes are blocked).",
                      obj({"target": S}, ["target"]), kill_process, Level.CONFIRM, "sysinfo", always_confirm=True,
                      classify=_classify_kill, describe=_describe_kill))
