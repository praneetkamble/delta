# Delta: safety model

Delta can control your computer, so the design goal is: **even if the language model is fooled, the worst outcome is a
request on your screen asking for permission.** This document says exactly what is enforced, where, and what is *not* protected.

## 1. Three permission levels

| Level | Meaning | Examples |
|---|---|---|
| **safe** | runs immediately | open a known app, volume, brightness, lock, screenshot, reminders, notes, system info, search the web, whitelisted shell commands, read-only file search |
| **confirm** | needs an explicit yes (UI button, typed, or spoken) | close an app, delete (always), shut down / restart (always), kill a process (always), organize Downloads, run a non-whitelisted command, launch an unknown program or a `.exe/.bat/.ps1…`, close a window |
| **blocked** | never runs, even if you say yes | destructive/security-sensitive shell patterns (`format`, `diskpart`, `reg delete`, `del /s`, `rm -rf`, encoded PowerShell, `curl … \| sh` …), killing critical Windows processes (`csrss.exe`, `lsass.exe`, `svchost.exe` …), anything under `safety.blocked_tools`, any path outside the allowed folders |

The level is decided **per call** (`PermissionPolicy.decide`), from the tool, its arguments and the context.
`safety.overrides` can raise any tool, or lower an ordinary one (e.g. `close_app: safe`). Tools flagged **always asks**
(`shutdown_pc`, `restart_pc`, `delete_path`, `kill_process`) can never be lowered by config, and neither can a tool whose level depends on its arguments
(`open_app`, `open_path`, `run_command`, `window_action`): config may only raise those.
Approvals expire (default 120 s), can't be replayed, and are re-checked against the policy at approval time.

## 2. The folder sandbox

All file tools resolve paths with `Sandbox.resolve`:

* symlinks/junctions are resolved with `realpath` *before* the check (a link inside Downloads pointing at `C:\Windows` is refused);
* `..` traversal, absolute paths outside the allowed folders, UNC paths (`\\server\share`), `C:\…` strings on non-Windows, null bytes, `~` outside allowed folders and sibling folders with the same prefix (`Downloads-evil`) are refused;
* `%VAR%` / `$VAR` are **not** expanded;
* comparison is case-insensitive on Windows;
* the allowed folders themselves can't be moved or deleted;
* moves/copies **never overwrite** (`name (1).ext`); delete = Recycle Bin via `send2trash`, only after confirmation;
* a refused path is written to the audit log as `sandbox_violation`.

Tested in `tests/test_sandbox.py` (including Windows path rules via `ntpath`) and `tests/test_files.py`.

## 3. Audit log

Every user message (first 80 characters), confirmation request, approval, denial, block, tool result, dry-run, kill and routine start is appended to
`%USERPROFILE%\.delta\audit.jsonl` as one JSON object per line. Each line includes the SHA-256 of the previous line, so editing or deleting a line is detected by
`python -m delta audit` (and the UI shows "Audit log intact / TAMPERED"). Passwords, API keys, tokens and card-like numbers are redacted; clipboard text is logged only as a character count.
**Limit:** this is tamper-*evident*, not tamper-*proof*: someone who can rewrite the whole file can rebuild the chain.

## 4. Kill switch, dry-run, pause

* **Kill switch:** the global hotkey (default `Ctrl+Alt+Shift+K`), the red button in the UI, or typing `kill`, `kill switch`, `emergency stop` or `panic`. It cancels all pending approvals, blocks every action, stops routines and the scheduler, and stays on until you press Resume or type `resume`.
* **Dry-run:** `python -m delta --dry-run serve` or the toggle in the UI. Every side-effecting tool describes what it *would* do and does nothing (read-only tools still work). Even an approved action is only simulated.

## 5. No network exposure

* The server binds to **127.0.0.1 only** (`assert_loopback` refuses anything else).
* Every request needs a random 192-bit token generated at start-up. It reaches the browser via the printed link, which sets an `HttpOnly; SameSite=Strict` cookie.
* `Host` must be `127.0.0.1`/`localhost` (DNS-rebinding protection); `Origin` of POSTs must be Delta's own origin (CSRF protection); strict CSP and `X-Frame-Options: DENY`; no `/docs` or OpenAPI.
* The link (with token) is also written to `~/.delta/session_url.txt` so "Delta (open)" can open it, and deleted when Delta exits. Anyone who can read your user profile can read it: it is the same trust boundary as the rest of your files.

## 6. Passwords and secrets

* Delta never asks for, stores or types passwords. `remember …` refuses anything that looks like a password, key, PIN, OTP, card or bank detail (`tests/test_memory.py`).
* The LLM key is read from an environment variable only; it is never written to `config.yaml`, the database or the audit log.
* Secret-looking text is redacted before tool results are sent to the LLM and before anything is audited. **With a cloud LLM, what Delta reads for you (clipboard, files, pages, command output) leaves your PC** to that provider: use a local model (Ollama) if that matters.
* The conversation history is stored in plain text in `~/.delta/delta.db`.

## 7. Prompt-injection guard

Web pages, files, the clipboard, OCR text and command output are **untrusted data**:

1. Those tools are flagged `untrusted_output`. Their text reaches the model only inside `<<<UNTRUSTED_CONTENT … >>>` fences (fake fence markers and control/bidi characters are stripped), and the system prompt says it is data, not instructions.
2. The summariser call runs **with no tools at all**, so text inside a page cannot trigger an action during summarisation.
3. After untrusted text is read, the session is *tainted* for the next 3 turns. During that time (a) taint-sensitive tools that are normally safe (open URL, web search, clipboard write, move/copy, remember, run script, run routine, sleep) become **confirm**, (b) any confirm-level request is flagged "requested after reading untrusted text" in the UI, and (c) a bare "yes" is **not accepted** for it: you must press Approve or say `yes <id>`.
4. Confirm-level actions can only be approved by *your* input (button / your typed or spoken reply). The model can't approve its own request; its text is never parsed as a confirmation.
5. Phrases that look like instructions to an AI ("ignore previous instructions…") are detected and shown as a warning next to the content.
6. Fetching a web page refuses `localhost`, private/link-local/loopback addresses and non-http(s) schemes, re-checking every redirect hop (SSRF), and caps the download size.

Tested in `tests/test_injection.py` with a simulated LLM that *obeys* a malicious page: the file survives, the request waits for approval, and a bare "yes" does not release it.
**Limit:** this lowers risk; it is not a guarantee. An LLM can still be talked into asking for something plausible. That is why destructive actions always show you the exact thing they will do before they run.

## 8. What Delta does *not* protect against

* Malware or another user already running as you (Delta runs with your permissions and is not a security boundary against them).
* You approving a dangerous request without reading it.
* A cloud LLM provider seeing the data you ask Delta to process.
* Mistakes in the **Windows adapter**, which has not been run on a real PC yet (see README → "What was tested"). The *policy* layer is OS-independent and tested; a bug in `windows.py` would be a functional bug (a command not working), not a way around the gate.
* `send2trash` on a network drive may delete permanently: keep the allowed folders on local disks.

## 9. Vibe Coding (AI-written code)

Vibe Coding lets a language model edit files and run commands in a project folder. It reuses the gate (validation, permission levels, confirm cards, dry-run, kill switch, audit hash chain); these are the extra rules and the honest limits.

**What is enforced (and covered by tests)**

* **The model can only call 7 tools** through a fixed name table (`list_files`, `read_file`, `search_code`, `write_file`, `apply_patch`, `delete_file`, `run_command`). Unknown names (`shutdown_pc`, `vibe_undo`, any Delta tool) are ignored; arguments the table does not list (`run`, `project`, ...) are dropped. All 13 `vibe_*` gate tools have `expose_to_llm=False`, so the normal chat model never sees them either. Undo, auto-accept and every non-whitelisted command are `CONFIRM`; "always asks" cannot be lowered by config.
* **Path jail.** Every path is relative to one project folder and validated twice: lexically (no absolute, drive `C:`, UNC `\\server`, `..`, `:` / alternate data streams, reserved names such as `CON`/`NUL`, trailing dots/spaces, `.git`, and for writes `node_modules`, `.venv`, `dist`, `build`) and by `realpath` containment (symlinks and junctions that point out are refused). The projects root must be inside `safety.allowed_folders`, or Vibe Coding refuses to start. Project names allow letters, digits, `.` `-` `_` only.
* **Review before apply.** Writes are staged in memory as diffs; the disk changes only when *you* accept (a user-origin gate call from the dashboard). Accept refuses if the file changed on disk since. Pending changes are not persisted: a restart discards them.
* **Commands never touch a shell.** The command is tokenised, matched against a whitelist (`vibe.command_whitelist`; defaults are `npm install/run build/dev/test`, `pip install -r requirements.txt`, `python <file>.py`, `pytest`, `node <file>.js`, safe `git` subcommands), run with `shell=False` in the project folder, with a timeout and output cap, and the process **tree** is killed on timeout / cancel / kill switch. Pipes, `&&`, `;`, redirects, `%VAR%`, `$(...)`, `cmd`/`powershell`/`bash` launchers and a long list of dangerous patterns (`rm`, `del`, `git reset --hard`, `git clean`, `git push --force`, `curl | sh`, `taskkill`, `format X:` ...) are refused outright. Anything else (including `npm install <package>`, `pip install <package>`, `python -c`, any path argument that leaves the project) shows the exact command and **asks**. Config can add blocked patterns but never remove the built-in ones. Windows `.cmd` shims (`npm.cmd`) are launched only after rejecting `& | < > ^ % "` in arguments.
* **Text from files, logs and command output is data.** It is fenced as untrusted, secret-redacted (including `gsk_...` keys) and scanned for instruction-like text; if found, the run is *tainted*: auto-accept pauses and every command asks, even whitelisted ones. The "Fix this error" log goes through the same fence.
* **The LLM API key is never given to children.** The key lives only in the environment variable named by `llm.api_key_env`; it is removed from the environment of every command, install and preview process, and never written to files, audit log, or the model prompt.
* **Undo is itself recoverable.** Every run starts with a git snapshot; "Undo last run" commits the current state first and tells you how to return to it. Undo never runs while a run is active.
* **Audit.** Run start/end, every staged/accepted/rejected change (path and counts, **not contents**), command results, undo, preview start/stop, taint events and approvals are in the hash-chained audit log and shown in the Activity view.
* **Dashboard isolation from the preview.** The preview (a static server, or `npm`/`uvicorn` running AI-written code) listens on `127.0.0.1` on its own port and is shown in a sandboxed iframe on the *other* loopback host name, because browser cookies ignore ports: on the same host name the browser would send your Delta session cookie to that program. On top of that, the API now rejects any request whose `Sec-Fetch-Site` is not `same-origin`/`none` (so a page on another local port cannot use Delta even if it had the cookie), and the CSP only allows framing loopback pages. A headless-Chrome test checks both. Browsers that do not send `Sec-Fetch-Site` get only the host-name separation, and non-browser programs running on your PC (any program of yours) are outside this model, as before.

**What it does NOT protect against (read this)**

* **AI-written code runs with your permissions.** `python main.py`, `npm run build`, `npm install` (lifecycle scripts of dependencies!), the Preview, and the dev servers all *execute code the model wrote or pulled in*, and the whitelist cannot know what that code does. A malicious or merely buggy program can read your files, use the network, or delete things outside the project; the path jail and command policy apply to the *agent's tools*, not to what a program it started does. Mitigations: you review every diff first (that is the point of review-before-apply), commands from a tainted run always ask, the key is stripped from the child environment, and Undo restores the project folder (not anything the program changed elsewhere). If that risk is not acceptable, set `vibe.command_whitelist: []` and do not use Preview for untrusted projects; for real isolation run Delta in a VM / Windows Sandbox.
* A prompt injection can still make the model write *bad code into a file you then accept*. The injection scan is a heuristic, not a guarantee; read diffs.
* **Updates are polling** (chat/run every 0.7 s, preview log every 0.7 s while open), not a stream; a closed tab means nobody sees an approval card, which then expires after `safety.confirm_timeout_s`.
* **Not tested on Windows**: junctions/`mklink`, long paths, `npm.cmd`, `Code.exe` discovery, `py -3`, `.venv\Scripts`, process-tree kill via `psutil`, Git for Windows (CRLF, `core.autocrlf` is forced off for Delta's own commits), antivirus interaction. The lexical Windows path rules are unit-tested with `ntpath` semantics, nothing else is proven on Windows.

## 10. Reporting / hardening checklist for the owner

- [ ] Keep `allowed_folders` as small as you can.
- [ ] Leave `shell_whitelist` short; never whitelist `powershell`, `cmd`, `python`, `curl`, `del`.
- [ ] Use a local model, or accept that file/clipboard text is sent to your LLM provider.
- [ ] Run `python -m delta audit` now and then.
- [ ] After the first real-PC run, test the kill switch hotkey and `--dry-run` before trusting it.
- [ ] Vibe Coding: keep the projects folder separate from anything valuable, leave Auto-accept off, read the diffs, and read the exact command in every approval card.
