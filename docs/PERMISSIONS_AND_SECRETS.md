# Runtime permissions and secret handling

For the interactive profiles, approval UI, container boundary, threat model, and adversarial test
matrix, see [SECURITY_MODEL_AND_TESTING.md](SECURITY_MODEL_AND_TESTING.md).

EgoAgent applies one typed runtime policy to Agent tools, DAG Tool nodes, Process nodes, Workspace
nodes, and Task Bench runs. The policy is owned by the run, so parallel and nested runs do not
share approvals.

## Permission classes

| Class | Examples |
|---|---|
| `read` | read/search/list workspace files |
| `write` | write, patch, and multi-edit workspace files |
| `process` | start commands and subprocesses |
| `network` | browser, URL fetch, and web search |
| `mutation` | create or modify Identity, Ego, Knowledge, Skill, or Harness resources |
| `secret` | resolve a named secret for one authorized call |

Decisions are `allow`, `ask`, or `deny`. If a tool needs more than one class, the most restrictive
decision wins. Rules are evaluated in order and the last matching rule for each class wins.

## Harness policy example

Put the policy under `pipeline.permissions` in a Harness config:

```json
{
  "pipeline": {
    "mode": "agent",
    "permissions": {
      "defaults": {
        "read": "allow",
        "write": "ask",
        "process": "ask",
        "network": "deny",
        "mutation": "deny"
      },
      "allow_sensitive_files": false,
      "allow_global_mutation": false,
      "rules": [
        {
          "permission_class": "network",
          "tool": "web_search",
          "arguments": {"query": "docs:*"},
          "decision": "ask",
          "reason": "Documentation searches require approval"
        },
        {
          "permission_class": "write",
          "tool": "write_file",
          "arguments": {"file_path": "generated/*"},
          "decision": "allow",
          "reason": "Generated output is an approved target"
        }
      ]
    }
  }
}
```

A rule may also include a workspace glob and a list of modes. Every denial event contains the
matching/default reason, so the debugger can explain why execution stopped.

## Modes and Task Bench

- `plan` and `ask` deny writes and global mutation by default.
- `evaluate` and `task` deny global mutation by default.
- Task Bench also denies network when the task declares `network: disabled`.
- Task Bench enables Identity/Harness mutation only when evolution is explicitly enabled and at
  least one evolution target is declared.

These rules are backend enforcement. Hiding a tool in the frontend is only a usability improvement,
not the security boundary.

## Named secrets

Never put a key in a Harness, task, command argument, or `env` field. Authorize the environment
variable name when creating the run, then reference it from a Process node:

```json
{
  "id": "call-private-service",
  "op": "进程",
  "command": "python",
  "args": ["scripts/call_service.py"],
  "secret_env": {
    "SERVICE_TOKEN": "MY_SERVICE_API_KEY"
  }
}
```

`MY_SERVICE_API_KEY` is resolved only for that subprocess and exposed there as `SERVICE_TOKEN`.
Secret-looking keys in the ordinary `env` field are rejected. Authorized secret values are redacted
from node results, event streams, debugger output, and run logs. Usage fields such as
`prompt_tokens` remain visible.

## Workspace boundary

Relative paths are resolved from the run workspace. Absolute paths, `..` traversal, and symlinks
whose resolved target leaves the workspace are denied. Sensitive files such as `.env.local`, private
keys, and credential files are denied in Task/Evaluate mode unless the policy explicitly enables
sensitive reads.

## Verification

From the repository root:

```powershell
python .\tests\test_permissions.py
python -m unittest discover -s tests -p "test_agent_workspace_boundary.py"
python -m unittest discover -s tests -p "test_task_bench*.py"
python -m unittest discover -s tests -p "test_process_backends.py"
```

The Windows symlink-escape test is skipped when the current account cannot create symlinks; absolute
path and traversal checks still run, and the same resolved-path guard handles symlinks in production.
