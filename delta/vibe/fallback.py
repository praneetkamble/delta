"""Offline rule-based coding (no LLM): a small set of useful edits on the project templates. Every edit still goes through the
same tools, so it is staged as a diff for review exactly like an AI edit."""
from __future__ import annotations

import html
import json
import re

HELP = ("I'm in offline mode (no language model is connected), so I only understand a few simple requests:\n"
        "• static site: “set the title to My Cafe”, “set the heading to …”, “background color #0b1020”, “accent color orange”, "
        "“dark theme” / “light theme”, “add a section called Pricing saying …”, “add a button saying Book now linking to https://…”, "
        "“add a page called About”, “add a counter”, “add a todo list”, “add a theme toggle”\n"
        "• FastAPI: “add an endpoint /status returning ok” • Express: “add a route /status returning ok” • React: “set the heading to …”, “add a button saying …”\n"
        "• any project: “create file notes.txt with hello”.\n"
        "Connect a model (Groq / Ollama, see the README) for free-form requests like “build a booking page with a form”.")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "section"


def _clean_value(v: str) -> str:
    return v.strip().strip("\"'“”‘’").rstrip(".!").strip()


CSS_SECTION = "\nsection { margin: 40px 0; padding-top: 24px; border-top: 1px solid #ffffff1a; }\nsection h2 { margin-bottom: 8px; }\n"
CSS_BTN = "\n.btn { display: inline-block; margin: 12px 12px 0 0; padding: 10px 18px; border-radius: 8px; border: 1px solid var(--accent); color: var(--accent); text-decoration: none; background: transparent; font: inherit; cursor: pointer; }\n.btn:hover { background: color-mix(in srgb, var(--accent) 18%, transparent); }\n"


class Rules:
    def __init__(self, runner):
        self.r = runner
        self.mgr = runner.mgr
        self.run = runner.run
        self.done: list[str] = []
        self.failed: list[str] = []

    def text(self, path: str) -> str | None:
        try:
            return self.mgr.current_text(self.run.project, path)
        except Exception:
            return None

    def write(self, path: str, content: str, what: str) -> bool:
        ok_, out = self.r.dispatch("write_file", {"path": path, "content": content})
        (self.done if ok_ else self.failed).append(what if ok_ else f"{what} ({out[:80]})")
        return ok_

    # ---- static site helpers
    def set_css_var(self, name: str, value: str) -> bool:
        css = self.text("style.css")
        if css is None:
            self.failed.append("no style.css to edit")
            return False
        if re.search(rf"--{name}\s*:", css):
            new = re.sub(rf"(--{name}\s*:\s*)[^;]+;", lambda m: f"{m.group(1)}{value};", css, count=1)
        else:
            new = f":root {{ --{name}: {value}; }}\n" + css
        return self.write("style.css", new, f"set --{name} to {value}")

    def add_css(self, snippet: str, marker: str) -> None:
        css = self.text("style.css") or ""
        if marker not in css:
            self.write("style.css", css.rstrip("\n") + "\n" + snippet, f"added {marker} styles")

    def insert_in_main(self, block: str, what: str) -> bool:
        src = self.text("index.html")
        if src is None:
            self.failed.append("no index.html")
            return False
        if "</main>" in src:
            new = src.replace("</main>", block + "  </main>", 1)
        elif "</body>" in src:
            new = src.replace("</body>", block + "</body>", 1)
        else:
            new = src + block
        return self.write("index.html", new, what)

    def apply(self, prompt: str) -> bool:
        p = prompt.strip()
        low = p.lower()
        kind = self.mgr.detect_kind(self.mgr.project_path(self.run.project))
        matched = False
        m = re.search(r"(?:create|make|add)\s+(?:a\s+|an\s+)?(?:new\s+)?file\s+(?:called\s+|named\s+)?([\w./-]+)(?:\s+(?:with|containing)\s+(?:the\s+)?(?:content\s+|text\s+)?(.+))?$", p, re.I | re.S)
        if m:
            matched = True
            self.write(m.group(1), (_clean_value(m.group(2)) + "\n") if m.group(2) else "", f"created {m.group(1)}")
        if kind in ("fastapi", "express"):
            m = re.search(r"add\s+(?:an?\s+)?(?:endpoint|route)\s+(/[\w/{}.-]*)(?:\s+(?:that\s+)?(?:returns?|returning|saying|responds? with)\s+(.+))?$", p, re.I)
            if m:
                matched = True
                self.add_route(kind, m.group(1), _clean_value(m.group(2) or "ok"))
        if kind in ("static", "blank"):
            matched |= self.static_rules(p, low)
        elif kind in ("react-vite",):
            matched |= self.react_rules(p, low)
        return matched

    def add_route(self, kind: str, path: str, msg: str) -> None:
        name = re.sub(r"[^a-z0-9_]", "_", path.strip("/").lower()) or "root"
        if kind == "fastapi":
            src = self.text("main.py") or ""
            if f'"{path}"' in src:
                self.failed.append(f"{path} already exists")
                return
            self.write("main.py", src.rstrip("\n") + f'\n\n\n@app.get("{path}")\ndef {name}():\n    return {{"message": {json.dumps(msg)}}}\n', f"added GET {path}")
        else:
            src = self.text("server.js") or ""
            if f"'{path}'" in src:
                self.failed.append(f"{path} already exists")
                return
            route = f"app.get('{path}', (req, res) => {{\n  res.json({{ message: {json.dumps(msg)} }});\n}});\n\n"
            new = src.replace("app.listen(", route + "app.listen(", 1) if "app.listen(" in src else src + "\n" + route
            self.write("server.js", new, f"added GET {path}")

    def react_rules(self, p: str, low: str) -> bool:
        matched = False
        m = re.search(r"(?:set|change|make)\s+(?:the\s+)?(?:heading|title)\s+(?:to|as)\s+(.+)$", p, re.I)
        if m and self.text("src/App.jsx"):
            matched = True
            v = html.escape(_clean_value(m.group(1)))
            src = self.text("src/App.jsx")
            new = re.sub(r"<h1>.*?</h1>", lambda _m: f"<h1>{v}</h1>", src, count=1, flags=re.S)
            self.write("src/App.jsx", new, f"set the heading to {v}")
        m = re.search(r"add\s+(?:a\s+)?button\s+(?:saying|that says|called|with text)\s+(.+)$", p, re.I)
        if m and self.text("src/App.jsx"):
            matched = True
            v = html.escape(_clean_value(m.group(1)))
            src = self.text("src/App.jsx")
            new = src.replace("    </main>", f"      <button onClick={{() => alert({json.dumps(_clean_value(m.group(1)))})}}>{v}</button>\n    </main>", 1)
            self.write("src/App.jsx", new, f"added a “{v}” button")
        return matched

    def static_rules(self, p: str, low: str) -> bool:
        matched = False
        m = re.search(r"(?:set|change|make|rename)\s+(?:the\s+)?(?:(page|site|website)\s+)?(title|heading|name)\s+(?:to|as|=)\s+(.+)$", p, re.I)
        if m and self.text("index.html"):
            matched = True
            which, v = m.group(2).lower(), html.escape(_clean_value(m.group(3)))
            src = self.text("index.html")
            new = src
            if which in ("title", "name"):
                new = re.sub(r"<title>.*?</title>", lambda _m: f"<title>{v}</title>", new, count=1, flags=re.S)
                new = re.sub(r"(<header[^>]*>\s*<strong>).*?(</strong>)", lambda _m: f"{_m.group(1)}{v}{_m.group(2)}", new, count=1, flags=re.S)
            if which in ("heading", "title", "name"):
                new = re.sub(r"(<h1[^>]*>).*?(</h1>)", lambda _m: f"{_m.group(1)}{v}{_m.group(2)}", new, count=1, flags=re.S)
            self.write("index.html", new, f"set the {which} to “{v}”")
        m = re.search(r"\b(background|bg)(?:\s+colou?r)?(?:\s+(?:to|is)\s+|\s*[=:]\s*|\s+)(#[0-9a-fA-F]{3,8}|[a-zA-Z]+)", p, re.I)
        if m:
            matched = True
            self.set_css_var("bg", m.group(2))
        m = re.search(r"\b(accent|highlight|brand)(?:\s+colou?r)?(?:\s+(?:to|is)\s+|\s*[=:]\s*|\s+)(#[0-9a-fA-F]{3,8}|[a-zA-Z]+)", p, re.I)
        if m:
            matched = True
            self.set_css_var("accent", m.group(2))
        if re.search(r"\bdark\s+(mode|theme)\b", low) and "toggle" not in low:
            matched = True
            self.set_css_var("bg", "#0e1116")
            self.set_css_var("ink", "#e8eef2")
        elif re.search(r"\blight\s+(mode|theme)\b", low) and "toggle" not in low:
            matched = True
            self.set_css_var("bg", "#f7f8fa")
            self.set_css_var("ink", "#14181d")
        m = re.search(r"add\s+(?:a\s+|an\s+)?section\s+(?:called\s+|named\s+|for\s+|about\s+)?(.+?)(?:\s+(?:saying|with text|that says|with the text)\s+(.+))?$", p, re.I)
        if m:
            matched = True
            title = html.escape(_clean_value(m.group(1)))
            body = html.escape(_clean_value(m.group(2) or "Write something here."))
            if self.insert_in_main(f'    <section id="{_slug(title)}">\n      <h2>{title}</h2>\n      <p>{body}</p>\n    </section>\n', f"added the “{title}” section"):
                self.add_css(CSS_SECTION, "section {")
        m = re.search(r"add\s+(?:a\s+)?button\s+(?:saying|that says|called|labell?ed|with text)?\s*(.+?)(?:\s+(?:linking|that links|going|which links|linked)\s+to\s+(\S+))?$", p, re.I)
        if m and "toggle" not in low:
            matched = True
            label = html.escape(_clean_value(m.group(1)))
            url = html.escape(_clean_value(m.group(2) or "#"), quote=True)
            if re.match(r"(?i)\s*(javascript|data):", url):
                url = "#"
            if self.insert_in_main(f'    <a class="btn" href="{url}">{label}</a>\n', f"added a “{label}” button"):
                self.add_css(CSS_BTN, ".btn {")
        m = re.search(r"add\s+(?:a\s+)?page\s+(?:called\s+|named\s+|for\s+)?(.+)$", p, re.I)
        if m:
            matched = True
            self.add_page(_clean_value(m.group(1)))
        if re.search(r"add\s+(?:a\s+)?(?:click\s+)?counter\b", low):
            matched = True
            if self.insert_in_main('    <section id="counter">\n      <h2>Counter</h2>\n      <button class="btn" id="count-btn">Clicked 0 times</button>\n    </section>\n', "added a counter"):
                self.add_css(CSS_BTN, ".btn {")
                js = self.text("script.js") or ""
                self.write("script.js", js.rstrip("\n") + "\n\nlet clicks = 0;\nconst countBtn = document.getElementById('count-btn');\nif (countBtn) countBtn.addEventListener('click', () => {\n  clicks += 1;\n  countBtn.textContent = `Clicked ${clicks} times`;\n});\n", "counter script")
        if re.search(r"add\s+(?:a\s+)?(?:to-?do|task)\s+list\b", low):
            matched = True
            block = ('    <section id="todos">\n      <h2>To-do list</h2>\n      <form id="todo-form"><input id="todo-in" placeholder="Add a task" aria-label="Add a task"> '
                     '<button class="btn" type="submit">Add</button></form>\n      <ul id="todo-list"></ul>\n    </section>\n')
            if self.insert_in_main(block, "added a to-do list"):
                self.add_css(CSS_BTN, ".btn {")
                self.add_css("\n#todo-in { padding: 9px 12px; border-radius: 8px; border: 1px solid #ffffff33; background: transparent; color: inherit; font: inherit; }\n#todo-list { margin-top: 12px; padding-left: 20px; }\n#todo-list li { cursor: pointer; padding: 3px 0; }\n#todo-list li.done { text-decoration: line-through; opacity: .55; }\n", "#todo-in")
                js = self.text("script.js") or ""
                self.write("script.js", js.rstrip("\n") + "\n\nconst todoForm = document.getElementById('todo-form');\nconst todoList = document.getElementById('todo-list');\nif (todoForm) todoForm.addEventListener('submit', (e) => {\n  e.preventDefault();\n  const input = document.getElementById('todo-in');\n  if (!input.value.trim()) return;\n  const li = document.createElement('li');\n  li.textContent = input.value.trim();\n  li.addEventListener('click', () => li.classList.toggle('done'));\n  todoList.append(li);\n  input.value = '';\n});\n", "to-do script")
        if re.search(r"add\s+(?:a\s+)?(?:dark\s*mode|theme)\s+toggle|add\s+(?:a\s+)?(?:light|dark)\s*/?\s*(?:dark|light)\s+toggle", low):
            matched = True
            if self.insert_in_main('    <button class="btn" id="theme-btn" type="button">Toggle theme</button>\n', "added a theme toggle"):
                self.add_css(CSS_BTN, ".btn {")
                self.add_css("\nbody.light { --bg: #f7f8fa; --ink: #14181d; --muted: #4a5760; }\n", "body.light")
                js = self.text("script.js") or ""
                self.write("script.js", js.rstrip("\n") + "\n\nconst themeBtn = document.getElementById('theme-btn');\nif (themeBtn) themeBtn.addEventListener('click', () => document.body.classList.toggle('light'));\n", "theme script")
        return matched

    def add_page(self, name: str) -> None:
        slug = _slug(name)
        fn = f"{slug}.html"
        if self.text(fn) is not None:
            self.failed.append(f"{fn} already exists")
            return
        title = html.escape(name)
        page = (f'<!doctype html>\n<html lang="en">\n<head>\n  <meta charset="utf-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
                f'  <title>{title}</title>\n  <link rel="stylesheet" href="style.css">\n</head>\n<body>\n  <header class="top"><a href="index.html">Home</a></header>\n'
                f'  <main>\n    <h1>{title}</h1>\n    <p class="lead">This page is empty. Ask Delta to fill it.</p>\n  </main>\n  <script src="script.js"></script>\n</body>\n</html>\n')
        if self.write(fn, page, f"created {fn}"):
            self.insert_in_main(f'    <p><a href="{fn}">{title}</a></p>\n', f"linked {fn} from the home page")


def run_rules(runner) -> str:
    run = runner.run
    run.add("info", "No language model is connected: using the built-in rule-based helper.", status="warn")
    rules = Rules(runner)
    matched = rules.apply(run.prompt)
    if not matched:
        run.add("result", "I didn't recognise that request in offline mode.", status="warn")
        return HELP
    pend = len(runner.mgr.pending_ids(run.project))
    parts = []
    if rules.done:
        parts.append("Done (offline rules): " + "; ".join(rules.done) + ".")
    if rules.failed:
        parts.append("Couldn't do: " + "; ".join(rules.failed) + ".")
    if pend:
        parts.append(f"{pend} file(s) are staged: review the diffs in the Changes tab and accept them.")
    return " ".join(parts) or HELP
