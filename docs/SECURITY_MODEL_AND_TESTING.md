# EgoAgent security model and verification

EgoAgent uses two independent boundaries:

1. **Policy and approval** decides whether an Agent may attempt an action.
2. **Execution isolation** limits the damage if approved or model-generated code behaves badly.

An approval dialog is not a sandbox. The default `Workspace guard` confines built-in file tools to
the active workspace, hides common credential files, sanitizes subprocess environments, and asks
before host commands, but an approved host command still has the permissions of the current Windows
user. Select container mode when untrusted code needs a stronger operating-system boundary.

## User controls

Open **Settings → 安全、审批与沙箱** in Studio/Void. Settings are saved per workspace in
`.egoagent/security.json` and apply to new runs.

| Profile | Intended use | Important defaults |
|---|---|---|
| Strict | Untrusted repository or Harness | writes/process/mutation ask; network and secrets deny |
| Balanced | Normal coding (recommended) | workspace writes allowed; host commands, network, mutation, unknown Tools, and dangerous actions ask; secrets deny |
| Trusted | A repository and Harness you reviewed | ordinary operations allowed; dangerous/critical intent remains controlled |
| Unrestricted | Temporary expert-only escape hatch | boundaries may be disabled; the UI keeps a warning visible |

The high-risk approval switch controls destructive commands, dependency installation, encoded or
nested shells, network-capable commands, reusable Agent mutations, and other high-risk intent.
System/disk/user/registry/credential operations are classified separately as critical. An approval
is valid only for the displayed operation and approval ID; ordinary chat messages cannot approve it.

Harness permission rules may narrow a workspace policy but cannot silently widen its minimums.
Downloaded Tool modules are parsed without importing them and are loaded only after the runtime
permission decision. Declared permissions are combined with dynamic intent, so a Tool cannot call
`curl` or read an environment key merely by declaring itself `process`-only.

## Execution boundaries

### Workspace guard

- Built-in file paths are resolved and must stay below the current workspace.
- Absolute-path, `..`, and resolved symlink escapes are denied.
- `.env*`, private keys, common cloud/SSH/Docker credential paths, and credential files are denied
  unless the user explicitly enables sensitive-file access.
- Model-authored subprocesses receive a reduced environment with secret-looking variables removed.
- Host commands are clearly labelled **not strongly isolated** and are approval-gated by default.

This mode provides the best Windows compatibility, but it is not an OS sandbox.

### Docker/Podman container

Each command runs in an ephemeral container with these default controls:

- network disabled;
- Linux capabilities dropped and `no-new-privileges` enabled;
- read-only container root;
- only the active workspace mounted (`rw` or `ro` as selected);
- bounded CPU, memory, process count, and temporary filesystem;
- reduced environment with no implicit API keys;
- no automatic image download by default.

Container mode is always **fail closed**. If Docker/Podman, the daemon, or the selected image is not
available, the command is blocked and never retried on the host. The in-process Python DAG node is
also blocked in container mode because it would otherwise bypass the selected isolation; use a typed
DAG node or Process node instead.

Docker Desktop is installed on the current development machine, but its daemon was not running
during the implementation audit. EgoAgent therefore reports container isolation as unavailable
instead of claiming that strong isolation is active.

## User-visible run termination

The IDE now keeps a stable run state: `running`, `waiting_approval`, `completed`, `failed`, or
`cancelled`. It shows actionable cards for:

- model output truncation (`finish_reason=length`);
- context-window, token, tool-call, node-step, and model-call limits;
- timeout, DNS, rate-limit, authentication, cancellation, and permission failures;
- pending approval after reconnect/reload.

When output is cut off, the partial response remains visible and is explicitly marked incomplete.
The UI suggests continuing from the same Session rather than leaving the spinner running forever.

## Local API boundary

The backend and unified proxy reject browser requests from untrusted origins. Trusted loopback and
VS Code webview origins are reflected exactly; wildcard CORS is not used. Browser mutation requests
must be JSON, request bodies and WebSocket frames are bounded, client frames must be masked, and
responses include no-sniff/referrer/cache protections. Originless local scripts remain supported.

This protects the local service from a malicious public webpage, but it is not authentication
against another process already running as the same OS user. Do not expose ports 8765/8766/8880 to
an untrusted network.

## Threat model and remaining limits

- Prompt injection is treated as untrusted input, but no classifier can make approved host execution
  safe. Review the exact command and target shown by an approval card.
- A writable workspace mount means approved container code can change that workspace. Use `ro` for
  analysis-only tasks and keep source control/checkpoints enabled.
- The Docker daemon itself is privileged infrastructure. EgoAgent only invokes it; it does not secure
  a misconfigured daemon or malicious local image.
- Named secrets are scoped to one approved Process node. A service legitimately receiving a secret
  can still leak it if its own code is malicious.
- Unrestricted mode is intentionally unsafe and should not be a default or shared-project setting.

## Automated verification

Run from the repository root with project dependencies available:

```powershell
python -m unittest discover -s tests -p "test_security*.py" -v
python -m unittest discover -s tests -p "test_permissions.py" -v
python -m unittest discover -s tests -p "test_run_command_skill.py" -v
python -m unittest discover -s tests -p "test_pipeline_runtime.py" -v
python -m unittest discover -s tests -p "test_browser_ego.py" -v
python -m unittest discover -s tests -v
```

The adversarial suite covers destructive/critical command classification, permission-declaration
spoofing, credential access, workspace traversal and sensitive paths, dotenv search leakage,
lazy Tool loading, approval/rejection side effects, container hardening arguments, non-disableable
fail-closed behavior, in-process Python bypass prevention, malicious browser origins, WebSocket/HTTP
request constraints, termination reasons, and output truncation.

Browser integration tests start a disposable local HTTP server and headless Chrome profile, then
exercise navigation, form input, semantic/coordinate clicks, dialogs, downloads, screenshots,
CAPTCHA detection, human handoff, cleanup, and workspace-scoped evidence storage.

## Design references

The split between approvals and OS isolation follows the same defense-in-depth pattern documented by
[OpenAI Codex](https://developers.openai.com/codex/agent-approvals-security), whose
[sandbox documentation](https://developers.openai.com/codex/sandboxing) distinguishes filesystem,
network, and platform enforcement. Claude Code documents permission modes, command review, reduced
credential exposure, and OS-level sandboxing in its
[security guide](https://code.claude.com/docs/en/security). Cursor exposes explicit allow/deny rules
for shell, file, MCP, and network access in its
[CLI permissions](https://docs.cursor.com/cli/reference/permissions). GitHub Copilot documents
ephemeral environments and controlled customization in
[agent sandboxes](https://docs.github.com/en/copilot/concepts/about-cloud-and-local-sandboxes)
and describes prompt-injection, credential, branch, review, and network mitigations in its
[risk guidance](https://docs.github.com/en/copilot/concepts/agents/cloud-agent/risks-and-mitigations).
