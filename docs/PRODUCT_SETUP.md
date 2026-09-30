# EgoAgent product setup

EgoAgent runs locally and exposes one browser URL: `http://127.0.0.1:8880/`.
The launcher owns the local EgoAgent runtime API on `8765` and Void on `8869`, installs the
native DAG Chat extension, and stops child processes when it exits.

## Windows

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm --prefix harness_editor ci
npm --prefix harness_editor run build
.\.venv\Scripts\python.exe start-all.py
```

The complete IDE requires a matching **Void Web server runtime** in `void-web/`.
It is not included in Git and there is no verified automatic installer yet.
Without it, run `.\.venv\Scripts\python.exe harness_editor/server.py` and open
`http://127.0.0.1:8765/` for the standalone Workbench (no native IDE Chat/editor).
See the [README](../README.md) for desktop prerequisites. The legacy dependency
installer `scripts/install.ps1` uses `.runtime/venv`, whereas the desktop launcher
requires `.venv`; the commands above work for both browser and desktop modes.
Do not change an organization's script policy just to run the desktop installer.

## macOS and Linux

```sh
chmod +x scripts/install.sh scripts/egoagent.py
./scripts/install.sh
./.runtime/venv/bin/python scripts/egoagent.py start
```

Use `./scripts/install.sh --offline` for a cache-only dependency install.
The bundled Void runtime must match the operating system; `egoagent doctor`
reports a missing or incompatible runtime rather than downloading one silently.

## Provider and network setup

The Agent Workbench Settings page contains a first-run wizard. API keys are sent once to
the local backend, written only to the gitignored `.env.local`, and never
returned to the browser or stored in model profile JSON. The equivalent CLI is:

```sh
python scripts/egoagent.py configure-provider --provider deepseek \
  --model deepseek-v4-flash --api-key "YOUR_KEY"
```

For networks that need a proxy or China-hosted package mirrors, configure them
in Settings or with:

```sh
python scripts/egoagent.py network \
  --https-proxy http://127.0.0.1:7890 \
  --pip-index https://pypi.tuna.tsinghua.edu.cn/simple \
  --npm-registry https://registry.npmmirror.com
```

Empty settings inherit the shell environment. Strict offline mode excludes all
remote model profiles at the model router, even if an API key is configured:

```sh
python scripts/egoagent.py network --offline on
```

## Diagnostics and privacy

```sh
python scripts/egoagent.py doctor
python scripts/egoagent.py diagnostics
```

The diagnostics ZIP contains dependency/runtime status, privacy settings, and
optional local logs. Environment secrets and common `sk-*` values are redacted.
Prompts are excluded by default and telemetry is disabled by default.

## Local updates and rollback

EgoAgent never downloads or applies an update implicitly. An update ZIP must
contain `.egoagent-update.json`:

```json
{ "format": "ego.update.v1", "version": "2.0.0" }
```

All other files are paths relative to the repository. Runtime state, `.git`,
secrets, dependencies, and the bundled Void runtime are protected targets.
Before replacement EgoAgent creates a rollback snapshot; partial updates are
restored automatically.

```sh
python scripts/egoagent.py update C:\path\to\egoagent-update.zip
python scripts/egoagent.py rollbacks
python scripts/egoagent.py rollback rollback-YYYYMMDD-HHMMSS-abcdef
```

Restart the local services after an update or rollback.
