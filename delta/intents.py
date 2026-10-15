"""Deterministic rule-based intent parser. Works offline with no LLM.

parse_commands("open chrome and spotify") -> [Intent(open_app, {name: chrome}), Intent(open_app, {name: spotify})]
Returns [] when it doesn't recognise the text (the brain then falls back to the LLM, or says it didn't understand).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from .timeparse import parse_duration, parse_when


@dataclass
class Intent:
    tool: str
    args: dict = field(default_factory=dict)


_POLITE = re.compile(
    r"^(?:(?:hey|hi|ok|okay)[, ]+)?(?:delta[,:]?\s+)?(?:please[, ]+)?"
    r"(?:(?:can|could|would|will) you\s+(?:please\s+)?|i (?:want|need) you to\s+|i'd like you to\s+|go ahead and\s+)?(?:please\s+)?", re.I)
TLDS = {"com", "org", "net", "io", "in", "co", "dev", "app", "ai", "edu", "gov", "me", "tv", "ly", "xyz", "info", "uk", "us", "gg", "so", "sh"}
FOLDER_WORDS = r"downloads|documents|desktop|pictures|music|videos"
ENGINE_WORDS = r"google|youtube|bing|duckduckgo|amazon|wikipedia"
SECTION_WORDS = {"cpu": "cpu", "processor": "cpu", "ram": "memory", "memory": "memory", "disk": "disk", "storage": "disk",
                 "battery": "battery", "network": "network", "wifi": "network", "wi-fi": "network", "ip": "network", "ip address": "network", "internet": "network"}


def clean(text: str) -> str:
    t = text.strip()
    t = _POLITE.sub("", t, count=1)
    t = re.sub(r"[\s?.!]+$", "", t)
    t = re.sub(r"\s+(please|for me)$", "", t, flags=re.I)
    return t.strip()


def _looks_url(s: str) -> bool:
    s = s.strip()
    if re.match(r"^https?://\S+$", s, re.I):
        return True
    m = re.fullmatch(r"(?:www\.)?[\w-]+(?:\.[\w-]+)*\.([a-z]{2,})(?:/\S*)?", s, re.I)
    return bool(m and m.group(1).lower() in TLDS)


def _looks_path(s: str) -> bool:
    return bool(re.search(r"[\\/]|^[a-zA-Z]:|^~", s) or re.search(r"\.\w{1,5}$", s))


def _split_names(rest: str) -> list[str]:
    return [p.strip() for p in re.split(r"\s*(?:,|\band\b|&)\s*", rest) if p.strip()]


def _reminder(t: str, now: datetime) -> Intent | None:
    m = re.match(r"(?:remind me|reminder|set a reminder)\s*(?:to |about |that )?(.+)$", t, re.I)
    if not m:
        return None
    body = m.group(1)
    # "<what> <when>"  — try every split point where a time phrase begins; first whole-suffix parse wins
    for sp in re.finditer(r"\b(in|at|tomorrow|today|tonight|on|next|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", body, re.I):
        what, when = body[:sp.start()].strip(" ,"), body[sp.start():].strip()
        if what and parse_when(when, now):
            what = re.sub(r"^(to|about|that)\s+", "", what, flags=re.I)
            return Intent("set_reminder", {"text": what, "when": when})
    # "in 10 minutes to <what>"
    for sp in re.finditer(r"\s(?:to|about|that)\s", body, re.I):
        when, what = body[:sp.start()].strip(" ,"), body[sp.end():].strip()
        if what and parse_when(when, now):
            return Intent("set_reminder", {"text": what, "when": when})
    return None


def _routine_intent(t: str, routines) -> Intent | None:
    if not routines:
        return None
    m = re.fullmatch(r"(?:run|start|activate|enable|begin|launch|switch to|turn on)\s+(?:my |the )?(?:routine\s+)?(.+?)(?:\s+routine)?", t, re.I)
    for cand in ([m.group(1)] if m else []) + [t]:
        r = routines.find(cand)
        if r:
            return Intent("run_routine", {"name": r.name})
    return None


def parse_commands(text: str, routines=None, now: datetime | None = None) -> list[Intent]:
    now = now or datetime.now()
    raw = text.strip()
    t = clean(raw)
    tl = t.lower()
    if not tl:
        return []

    # ---- routines first (user-defined names win over generic verbs: "focus mode", "work mode")
    r = _routine_intent(t, routines)
    if r:
        return [r]
    m = re.fullmatch(r"(?:list|show|what are)(?: my)? routines", tl)
    if m:
        return [Intent("list_routines")]

    # ---- meta
    if re.fullmatch(r"(?:help|what can you do|commands|cheat ?sheet|capabilities)", tl):
        return [Intent("list_capabilities")]
    if re.fullmatch(r"(?:daily briefing|briefing|brief me|good morning|morning briefing|what'?s my day|my day|what'?s up|plan my day)(?: today)?", tl):
        return [Intent("daily_briefing")]
    if re.fullmatch(r"(?:what(?:'s| is) the time|what time is it|time|what(?:'s| is)(?: today'?s| the)? date|what day is it|date|today'?s date|what(?:'s| is) the date today)", tl):
        return [Intent("current_time")]

    # ---- reminders / timers / alarms
    if re.match(r"(?:remind me|reminder|set a reminder)\b", tl):
        rem = _reminder(t, now)
        return [rem] if rem else []
    m = re.fullmatch(r"(?:list|show|what are|view)(?: my| all)?(?: pending)? (?:reminders|alarms|timers)(?: and (?:reminders|alarms|timers))*", tl)
    if m or tl in ("reminders", "my reminders"):
        return [Intent("list_reminders")]
    m = re.fullmatch(r"(?:cancel|delete|remove|stop) (?:the )?(?:reminder|timer|alarm)\s*#?(\d+)", tl)
    if m:
        return [Intent("cancel_reminder", {"id": int(m.group(1))})]
    if re.search(r"\btimer\b", tl):
        rest = re.sub(r"\b(set|start|create|a|an|the|timer|for|of|me|put|on)\b|[-,]", " ", tl)
        d = parse_duration(" ".join(rest.split()))
        if d:
            return [Intent("set_timer", {"duration": " ".join(rest.split())})]
    m = re.fullmatch(r"(?:set|create)?\s*(?:an? )?alarm (?:for|at) (.+)", tl) or re.fullmatch(r"wake me(?: up)? (?:at|by) (.+)", tl)
    if m:
        return [Intent("set_alarm", {"time": m.group(1).strip()})]

    # ---- notes / todos / facts
    m = re.fullmatch(r"(?:add (?:a )?note|take (?:a )?note|note|new note)[:\s]+(.+)", t, re.I)
    if m:
        return [Intent("add_note", {"text": m.group(1).strip()})]
    if re.fullmatch(r"(?:show|list|read|view)(?: me)?(?: my)? notes", tl):
        return [Intent("list_notes")]
    if re.fullmatch(r"(?:show|list|what(?:'s| is) on)(?: me)?(?: my)? (?:todos?|to-?do list|tasks|todo list|task list)|(?:my )?(?:todos?|tasks)|(?:todo|to-do|task) list", tl):
        return [Intent("list_todos")]
    m = re.fullmatch(r"(?:add|new|create)(?: a)? (?:todo|to-do|task)[:\s]+(.+)", t, re.I) or re.fullmatch(r"(?:todo|to-do)[:\s]+(.+)", t, re.I)
    if m:
        return [Intent("add_todo", {"text": m.group(1).strip()})]
    m = re.fullmatch(r"add (.+?) to (?:my )?(?:todo|to-do|task)s?(?: list)?", t, re.I)
    if m:
        return [Intent("add_todo", {"text": m.group(1).strip()})]
    m = re.fullmatch(r"(?:done|complete|finish|check off|tick off)(?: with)?(?: todo| task)?\s*#?(\d+)", tl)
    if m:
        return [Intent("complete_todo", {"id": int(m.group(1))})]
    m = re.fullmatch(r"(?:delete|remove)(?: todo| task)\s*#?(\d+)", tl)
    if m:
        return [Intent("delete_todo", {"id": int(m.group(1))})]
    m = re.fullmatch(r"remember(?: that)?[:\s]+(.+)", t, re.I)
    if m:
        return [Intent("remember_fact", {"text": m.group(1).strip()})]
    if re.fullmatch(r"what do you (?:know|remember) about me|(?:show|list)(?: my)? (?:facts|memories)|my facts", tl):
        return [Intent("list_facts")]
    m = re.fullmatch(r"forget(?: fact| memory)?\s*#?(\d+)", tl)
    if m:
        return [Intent("forget_fact", {"id": int(m.group(1))})]

    # ---- media
    if re.fullmatch(r"(?:play|pause|resume|play/pause|toggle)(?: the)?(?: music| media| song| track| playback| video)?", tl):
        return [Intent("media_control", {"action": "play_pause"})]
    if re.fullmatch(r"(?:next|skip)(?: the)?(?: track| song)?", tl):
        return [Intent("media_control", {"action": "next"})]
    if re.fullmatch(r"(?:previous|prev|last|go back)(?: track| song)?", tl):
        return [Intent("media_control", {"action": "previous"})]
    if re.fullmatch(r"stop(?: the)?(?: music| media| song| playback)", tl):
        return [Intent("media_control", {"action": "stop"})]
    m = re.fullmatch(r"play (.+?) on youtube", tl)
    if m:
        return [Intent("web_search", {"query": m.group(1), "engine": "youtube"})]

    # ---- volume / brightness
    if re.fullmatch(r"(?:max|full|maximum) volume", tl):
        return [Intent("set_volume", {"percent": 100})]
    m = re.fullmatch(r"(?:set |change |put )?(?:the )?(?:master )?volume(?: to| at)? (\d{1,3})\s*(?:%|percent)?", tl)
    if m:
        return [Intent("set_volume", {"percent": min(100, int(m.group(1)))})]
    m = re.fullmatch(r"(?:turn |bring |make it |put )?(?:the )?(?:volume )?(up|down|louder|quieter|softer|lower|higher)(?: the)?(?: volume)?(?: by (\d{1,3}))?(?: percent| %)?", tl) \
        or re.fullmatch(r"(?:turn |bring )?(?:the )?volume (up|down)(?: by (\d{1,3}))?(?: percent| %)?", tl)
    if m and (("volume" in tl) or m.group(1) in ("louder", "quieter", "softer")):
        up = m.group(1) in ("up", "louder", "higher")
        step = int(m.group(2)) if m.group(2) else 10
        return [Intent("change_volume", {"delta": step if up else -step})]
    if re.fullmatch(r"(?:unmute|un-mute)(?: the)?(?: volume| sound| audio| pc| computer)?", tl):
        return [Intent("set_mute", {"state": "off"})]
    if re.fullmatch(r"mute(?: the)?(?: volume| sound| audio| pc| computer)?", tl):
        return [Intent("set_mute", {"state": "on"})]
    m = re.fullmatch(r"(?:set |change )?(?:the )?(?:screen )?brightness(?: to| at)? (\d{1,3})\s*(?:%|percent)?", tl)
    if m:
        return [Intent("set_brightness", {"percent": min(100, int(m.group(1)))})]
    m = re.fullmatch(r"(?:turn |make it |bring )?(?:the )?(?:screen )?(?:brightness )?(up|down|brighter|dimmer)(?: the)?(?: brightness)?(?: by (\d{1,3}))?", tl)
    if m and ("brightness" in tl or m.group(1) in ("brighter", "dimmer")):
        up = m.group(1) in ("up", "brighter")
        step = int(m.group(2)) if m.group(2) else 10
        return [Intent("change_brightness", {"delta": step if up else -step})]

    # ---- power
    if re.fullmatch(r"lock(?: my| the)?(?: pc| computer| screen| laptop| windows)?", tl):
        return [Intent("lock_screen")]
    if re.fullmatch(r"(?:cancel|abort|stop) (?:the |my )?(?:pending )?(?:shut ?down|restart|reboot)", tl):
        return [Intent("cancel_shutdown")]
    if re.fullmatch(r"(?:sleep|go to sleep|put (?:the |my )?(?:pc|computer|laptop) to sleep)", tl):
        return [Intent("sleep_pc")]
    if re.fullmatch(r"(?:shut ?down|power off|turn off|switch off)(?: my| the)?(?: pc| computer| laptop| system)?", tl):
        return [Intent("shutdown_pc")]
    if re.fullmatch(r"(?:restart|reboot)(?: my| the)?(?: pc| computer| laptop| system)?", tl):
        return [Intent("restart_pc")]

    # ---- screen / clipboard
    if re.fullmatch(r"(?:take (?:a )?)?screenshot|screen ?shot|capture(?: the)? screen", tl):
        return [Intent("screenshot")]
    if re.fullmatch(r"(?:read|ocr|scan)(?: my| the)?(?: whole)? screen(?: text)?|what(?:'s| is) on (?:my |the )?screen", tl):
        return [Intent("screen_ocr")]
    if re.fullmatch(r"(?:what(?:'s| is)|show|read|paste)(?: on| in)?(?: me)?(?: my| the)? clipboard(?: contents?)?", tl):
        return [Intent("clipboard_read")]
    m = re.fullmatch(r"copy (.+?) to (?:the |my )?clipboard", t, re.I) or re.fullmatch(r"(?:copy to|set) clipboard[:\s]+(.+)", t, re.I)
    if m:
        return [Intent("clipboard_write", {"text": m.group(1).strip().strip('"“”')})]

    # ---- system info
    if re.fullmatch(r"(?:system (?:info|status|stats|health)|how(?:'s| is) my (?:pc|computer|system|laptop)(?: doing)?|pc status)", tl):
        return [Intent("system_info", {"section": "all"})]
    m = re.fullmatch(r"(?:what(?:'s| is)(?: my| the)?|how much|check(?: my)?|show(?: me)?(?: my)?|my)?\s*(cpu|processor|ram|memory|disk|storage|battery|network|wi-?fi|ip(?: address)?|internet)"
                     r"(?:\s+(?:usage|status|info|left|space|level|percentage|percent|is|remaining|available|do i have))*", tl)
    if m:
        return [Intent("system_info", {"section": SECTION_WORDS[m.group(1)]})]
    m = re.fullmatch(r"(?:what(?:'s| is) (?:using|eating) (?:my )?(cpu|memory|ram)|(?:top|heavy|running|biggest) (?:processes|apps|programs)(?: by (cpu|memory))?|show (?:top )?processes)", tl)
    if m:
        which = m.group(1) or m.group(2) or "memory"
        return [Intent("top_processes", {"sort_by": "cpu" if which == "cpu" else "memory"})]
    m = re.fullmatch(r"(?:kill|terminate|force close|end)(?: the)?(?: process| task)?\s+(.+)", t, re.I)
    if m and not re.fullmatch(r"(?:routine|reminder).*", m.group(1), re.I):
        return [Intent("kill_process", {"target": m.group(1).strip()})]

    # ---- windows
    if re.fullmatch(r"(?:show|list|what are)(?: my)?(?: all)? (?:open )?windows|what(?:'s| is) open", tl):
        return [Intent("list_windows")]
    m = re.fullmatch(r"snap(?: the)?(?: window)?(?: (.+?))? (left|right)", tl) or re.fullmatch(r"(?:move|put)(?: the)?(?: window)? (?:(.+?) )?to the (left|right)", tl)
    if m:
        return [Intent("window_action", {"action": "snap_" + m.group(2), "title": (m.group(1) or "active")})]
    m = re.fullmatch(r"(minimi[sz]e|maximi[sz]e|restore)(?: (?:the )?(?:window|this|current|active))?(?: (.+))?", tl)
    if m:
        act = {"minimi": "minimize", "maximi": "maximize", "restor": "restore"}[m.group(1)[:6]]
        title = (m.group(2) or "active").strip()
        return [Intent("window_action", {"action": act, "title": "active" if title in ("window", "this", "it") else title})]
    m = re.fullmatch(r"(?:focus|switch to|go to|bring up|show me|alt tab to)(?: the)?(?: window)? (.+)", tl)
    if m and not _looks_url(m.group(1)):
        return [Intent("focus_window", {"title": m.group(1).strip()})]

    # ---- files
    if re.fullmatch(r"(?:organi[sz]e|tidy|clean up|sort)(?: up)?(?: my)?(?: the)?(?: downloads)?(?: folder)?", tl) and ("download" in tl or tl.startswith(("organi", "tidy"))):
        return [Intent("organize_downloads")]
    m = re.fullmatch(r"(?:find|show|list|look for|search for)(?: me)?(?: all)?(?: the)? duplicates?(?: files)?(?: in (.+))?", tl)
    if m:
        return [Intent("find_duplicates", {"folder": m.group(1).strip()} if m.group(1) else {})]
    m = re.fullmatch(r"(?:find|locate|search(?: for)?|look for)(?: me)?(?: the)? files?(?: named| called| matching| with)? (.+?)(?: in (?:my )?(.+))?", t, re.I) \
        or re.fullmatch(r"(?:find|locate)(?: me)? (?:my )?(.+?)(?: in (?:my )?(" + FOLDER_WORDS + r")(?: folder)?)?", t, re.I)
    if m and not _looks_url(m.group(1)):
        args = {"query": m.group(1).strip().strip('"')}
        if m.group(2):
            args["folder"] = m.group(2).strip()
        return [Intent("search_files", args)]
    m = re.fullmatch(r"(?:create|make|new)(?: a)?(?: new)? folder(?: named| called)? (.+?)(?: in (?:my )?(.+))?", t, re.I) or re.fullmatch(r"mkdir (.+)", t, re.I)
    if m:
        args = {"name": m.group(1).strip().strip('"')}
        if m.lastindex and m.lastindex >= 2 and m.group(2):
            args["parent"] = m.group(2).strip()
        return [Intent("create_folder", args)]
    m = re.fullmatch(r"(?:list|show)(?: me)?(?: the)? (?:files|contents|items)? ?(?:in|of) (?:my )?(.+?)(?: folder)?", t, re.I)
    if m:
        return [Intent("list_folder", {"path": m.group(1).strip().strip('"')})]
    m = re.fullmatch(r"move (.+?) to (.+)", t, re.I)
    if m:
        return [Intent("move_path", {"source": m.group(1).strip().strip('"'), "destination": m.group(2).strip().strip('"')})]
    m = re.fullmatch(r"copy (.+?) to (.+)", t, re.I)
    if m:
        return [Intent("copy_path", {"source": m.group(1).strip().strip('"'), "destination": m.group(2).strip().strip('"')})]
    m = re.fullmatch(r"(?:delete|remove|trash|recycle)(?: the)?(?: file| folder)? (.+)", t, re.I)
    if m:
        return [Intent("delete_path", {"path": m.group(1).strip().strip('"')})]

    # ---- shell / scripts
    m = re.fullmatch(r"(?:run |execute )?(?:the )?(?:shell |cmd |powershell )?command[:\s]+(.+)", t, re.I) or re.fullmatch(r"(?:cmd|shell|powershell|terminal)[:>]\s*(.+)", t, re.I) \
        or re.fullmatch(r"run command (.+)", t, re.I)
    if m:
        return [Intent("run_command", {"command": m.group(1).strip()})]
    m = re.fullmatch(r"run (?:the )?script (.+)", t, re.I)
    if m:
        return [Intent("run_script", {"name": m.group(1).strip()})]

    # ---- web
    m = re.fullmatch(r"(?:summari[sz]e|tl;?dr|read|digest)(?: me)?(?: this| the)?(?: page| article| link| url| site| website)? (https?://\S+)", t, re.I)
    if m:
        return [Intent("summarize_url", {"url": m.group(1)}) if re.match(r"(?:summari|tl;?dr|digest)", tl) else Intent("read_webpage", {"url": m.group(1)})]
    m = re.fullmatch(r"summari[sz]e(?: the)?(?: file| document)? (.+)", t, re.I)
    if m and not _looks_url(m.group(1)):
        return [Intent("summarize_file", {"path": m.group(1).strip().strip('"')})]
    m = re.fullmatch(r"(?:open|go to|visit|browse(?: to)?|launch)\s+(\S+)", t, re.I)
    if m and _looks_url(m.group(1)):
        return [Intent("open_url", {"url": m.group(1)})]
    m = re.fullmatch(r"(?:(?:web )?search(?: the web| online)?(?: for)?|google|look ?up|lookup|find out about|search)\s+(.+?)(?: on (" + ENGINE_WORDS + "))?", t, re.I)
    if m:
        args = {"query": m.group(1).strip().strip('"')}
        if m.group(2):
            args["engine"] = m.group(2).lower()
        return [Intent("web_search", args)]
    m = re.fullmatch(r"youtube (.+)", t, re.I)
    if m:
        return [Intent("web_search", {"query": m.group(1), "engine": "youtube"})]

    # ---- apps (last, because "open X" is the most generic)
    m = re.fullmatch(rf"open(?: my| the)? ({FOLDER_WORDS})(?: folder)?", tl)
    if m:
        return [Intent("open_path", {"path": m.group(1)})]
    m = re.fullmatch(r"open(?: the| my)? (?:file|folder|document) (.+)", t, re.I)
    if m:
        return [Intent("open_path", {"path": m.group(1).strip().strip('"')})]
    m = re.fullmatch(r"(?:open|launch|start|run|fire up)\s+(.+)", t, re.I)
    if m:
        rest = m.group(1).strip().strip('"')
        if _looks_path(rest) and not _looks_url(rest):
            return [Intent("open_path", {"path": rest})]
        names = _split_names(rest) if not _looks_path(rest) else [rest]
        return [Intent("open_app", {"name": n}) for n in names]
    m = re.fullmatch(r"(?:close|quit|exit|shut)(?: down)?(?: the)?(?: app| application| program)? (.+)", t, re.I)
    if m:
        return [Intent("close_app", {"name": n}) for n in _split_names(m.group(1))]
    return []
