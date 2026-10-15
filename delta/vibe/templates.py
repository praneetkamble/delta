"""Project templates. Plain dicts of file -> text; nothing is downloaded when a project is created."""
from __future__ import annotations

TEMPLATES: dict[str, dict] = {}


def _t(key: str, title: str, blurb: str, kind: str, files: dict[str, str], hint: str) -> None:
    TEMPLATES[key] = {"key": key, "title": title, "blurb": blurb, "kind": kind, "files": files, "hint": hint}


_STATIC_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{name}}</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header class="top"><strong>{{name}}</strong></header>
  <main>
    <h1>{{name}}</h1>
    <p class="lead">Describe what you want in the Delta chat and this page will grow.</p>
  </main>
  <script src="script.js"></script>
</body>
</html>
"""
_STATIC_CSS = """:root { --bg: #0e1116; --ink: #e8eef2; --accent: #4fd6f2; --muted: #93a4ae; }
* { box-sizing: border-box; margin: 0; }
body { font: 16px/1.6 system-ui, "Segoe UI", sans-serif; background: var(--bg); color: var(--ink); min-height: 100vh; }
.top { padding: 16px 24px; border-bottom: 1px solid #ffffff1a; letter-spacing: .08em; }
main { max-width: 760px; margin: 0 auto; padding: 64px 24px; }
h1 { font-size: clamp(2rem, 5vw, 3.2rem); line-height: 1.1; margin-bottom: 12px; }
.lead { color: var(--muted); }
a { color: var(--accent); }
"""
_t("static", "Static site", "HTML, CSS and a little JavaScript. Opens instantly, no install.", "static",
   {"index.html": _STATIC_HTML, "style.css": _STATIC_CSS, "script.js": "// JavaScript for the page goes here.\n"},
   "index.html, style.css, script.js")

_t("react-vite", "React + Vite", "React 18 with the Vite dev server. Needs Node.js (npm install runs on first preview).", "node",
   {
       "package.json": """{
  "name": "{{slug}}",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.1",
    "vite": "^5.4.0"
  }
}
""",
       "vite.config.js": "import { defineConfig } from 'vite';\nimport react from '@vitejs/plugin-react';\n\nexport default defineConfig({ plugins: [react()] });\n",
       "index.html": """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{{name}}</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
""",
       "src/main.jsx": "import React from 'react';\nimport { createRoot } from 'react-dom/client';\nimport App from './App.jsx';\nimport './styles.css';\n\ncreateRoot(document.getElementById('root')).render(<App />);\n",
       "src/App.jsx": """import { useState } from 'react';

export default function App() {
  const [count, setCount] = useState(0);
  return (
    <main className="app">
      <h1>{{name}}</h1>
      <p>Edit <code>src/App.jsx</code> or ask Delta to change it.</p>
      <button onClick={() => setCount(count + 1)}>Clicked {count} times</button>
    </main>
  );
}
""",
       "src/styles.css": ":root { color-scheme: dark; }\nbody { margin: 0; font: 16px/1.6 system-ui, 'Segoe UI', sans-serif; background: #0e1116; color: #e8eef2; }\n.app { max-width: 720px; margin: 0 auto; padding: 64px 24px; }\nbutton { padding: 10px 16px; border-radius: 8px; border: 1px solid #4fd6f2; background: #11202a; color: #bff3ff; cursor: pointer; }\n",
   }, "package.json, vite.config.js, src/App.jsx")

_t("fastapi", "Python FastAPI", "A small FastAPI app served by uvicorn. Dependencies go into a private .venv.", "python-web",
   {
       "main.py": """from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="{{name}}")


@app.get("/", response_class=HTMLResponse)
def home():
    return "<h1>{{name}}</h1><p>FastAPI is running. Try <a href='/api/hello'>/api/hello</a>.</p>"


@app.get("/api/hello")
def hello(name: str = "world"):
    return {"message": f"Hello, {name}!"}
""",
       "requirements.txt": "fastapi>=0.110\nuvicorn>=0.27\n",
       "README.md": "# {{name}}\n\nRun with: `python -m uvicorn main:app --reload`\n",
   }, "main.py, requirements.txt")

_t("express", "Node Express", "An Express server (PORT env var). Needs Node.js.", "node",
   {
       "package.json": """{
  "name": "{{slug}}",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "start": "node server.js",
    "dev": "node server.js"
  },
  "dependencies": {
    "express": "^4.19.2"
  }
}
""",
       "server.js": """const express = require('express');
const app = express();
const port = process.env.PORT || 3000;

app.use(express.json());
app.use(express.static('public'));

app.get('/api/hello', (req, res) => {
  res.json({ message: 'Hello from {{name}}!' });
});

app.listen(port, '127.0.0.1', () => {
  console.log(`{{name}} listening on http://127.0.0.1:${port}`);
});
""",
       "public/index.html": "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><title>{{name}}</title></head>\n<body style=\"font:16px system-ui;background:#0e1116;color:#e8eef2;padding:48px\">\n<h1>{{name}}</h1><p>Express is running. API: <a style=\"color:#4fd6f2\" href=\"/api/hello\">/api/hello</a></p></body></html>\n",
   }, "package.json, server.js, public/index.html")

_t("python-script", "Python script", "A plain Python script you run and read the output of.", "script",
   {
       "main.py": '"""{{name}}"""\n\n\ndef main():\n    print("Hello from {{name}}!")\n\n\nif __name__ == "__main__":\n    main()\n',
       "README.md": "# {{name}}\n\nRun with: `python main.py`\n",
   }, "main.py")

_t("blank", "Blank", "An empty folder with a README. Let Delta decide the structure.", "blank",
   {"README.md": "# {{name}}\n\nDescribe what you want to build in the Delta chat.\n"}, "README.md")


def render(template: str, name: str) -> dict[str, str]:
    t = TEMPLATES[template]
    slug = "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-") or "app"
    return {p: txt.replace("{{name}}", name).replace("{{slug}}", slug) for p, txt in t["files"].items()}


def public_list() -> list[dict]:
    return [{k: t[k] for k in ("key", "title", "blurb", "kind", "hint")} for t in TEMPLATES.values()]
