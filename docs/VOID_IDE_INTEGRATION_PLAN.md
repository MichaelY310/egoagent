# EgoAgent in Void: one product shell

## Product decision

Void is the only user-facing product shell. "Studio" is not a second product
and should not require a separate browser tab, title bar, navigation model, or
workspace choice. Its capabilities become the **Agent Workbench** inside the
Void editor area.

The IDE has three complementary surfaces:

1. **Chat side bar** — ask, plan, run and inspect the current coding task.
2. **Agent Workbench editor** — build DAGs, evaluate agents, evolve identities,
   inspect evidence and manage reusable assets.
3. **Code editor** — review and undo agent changes at hunk level.

Putting every control in the narrow Chat side bar would make daily coding worse.
The Workbench therefore uses an ordinary editor tab: it has room for graphs and
tables, participates in Void tab/layout behavior, and never covers source code
unless the user chooses to open it.

## Information architecture

The Workbench is organized by the user's lifecycle rather than by backend
modules:

| User goal | Workbench route | Existing capabilities |
| --- | --- | --- |
| Understand current state | `home` | recent runs, evolution signals, promotion status |
| Create or edit an agent | `harness` | visual DAG, Identity binding, prompts, execution trace |
| Test an agent | `tasks` | tasks, datasets, environments, scoring, replay |
| Improve from evidence | `evolution` | proposals, bounded mutations, validation, promotion |
| Reuse or ship it | `packages` | versioned capability packages |
| Manage building blocks | `identity`, `environment`, `ir` | Identity/EGO, tools, knowledge, EgoIR |
| Inspect history and safety | `sessions`, `background`, `changes`, `checkpoints` | runs, diffs, recovery |
| Explore research/play | `research`, `coc` | experiments and tabletop harnesses |

Daily routes are visible. Advanced routes stay in a compact overflow menu.
Chat exposes contextual shortcuts to Build, Evaluate and Evolve so users do not
need to learn a separate application.

## Migration stages

### Stage 1 — one entry point (completed)

- Replace "Open Studio" with a singleton **Agent Workbench** editor.
- Support `embed=1&tab=<route>&workspace=<path>` deep links.
- Hide the nested Studio title/activity chrome in embedded mode.
- Add Chat shortcuts for Workbench, Build, Evaluate and Evolve.
- Pass the active Void workspace to Workbench execution and workspace APIs.
- Keep the old `egoagent.openStudio` command as an internal compatibility alias.

Acceptance: one Workbench tab is reused; every shortcut opens the expected
route; the displayed workspace is the folder open in Void.

### Stage 2 — shared navigation and state (completed)

- Persist Workbench route, selected harness/identity and draft state per Void
  workspace.
- Navigate an already-open Workbench without reloading its React application.
- Expose running status, pending reviews and evolution proposals in the native
  Void status bar and Chat.
- Replace global execution state with workspace/run keyed subscriptions at the
  UI boundary.

Acceptance: switching between code, Chat and Workbench never loses a draft or
creates duplicate executions.

### Stage 3 — IDE-native handoffs (completed)

- Open changed files and source locations from Workbench in the Void editor.
- Send selected files/ranges from Explorer and editor into tasks and datasets.
- Open session artifacts, task outputs and checkpoint diffs as editor tabs.
- Route all accept/reject actions through the existing hunk review manager.

Acceptance: Workbench never shows a fake file viewer when Void already has a
better native editor/diff surface.

### Stage 4 — package the frontend with the extension (completed)

- Build the React Workbench as relative static assets.
- Package those assets with the EgoAgent extension instead of serving a visible
  standalone website.
- Keep port 8765 as the local API/runtime only, with a health/recovery screen in
  the Workbench when it is unavailable.
- Share Void theme tokens, zoom, keyboard focus and accessibility settings.

Acceptance: users start Void once; there is no Studio URL they need to know.

### Stage 5 — remove legacy product seams (completed)

- Rename remaining user-facing "Studio" copy to Agent Workbench or EgoAgent.
- Remove standalone-only navigation and launch documentation.
- Add migration tests for deep links, workspace isolation, route restoration,
  WebSocket reconnects and extension upgrades.
- Keep a standalone development preview only for frontend contributors.

Acceptance: all product docs describe one IDE, while development remains easy.

## Implemented acceptance evidence

- Workbench route, builder draft, evaluation selection and evolution state are
  scoped to the canonical Void workspace and restored after a Webview reload.
- Route changes use Webview messages instead of replacing the React document.
- Builder, evaluation, review and evolution status are consolidated in the
  native status bar and Chat summary.
- Explorer/editor commands send immutable file or selection copies into a Task
  Bench run; limits are enforced before the run is created.
- Workbench file links open the native editor, and review decisions use the
  native hunk manager so Accept, Reject and decision Undo retain one history.
- Vite emits relative assets and `npm run package:extension` installs them under
  the native extension. Port `8765` is API-only from the product's perspective.
- Hidden Workbench Webviews release their React graph; lazy routes, visibility-
  aware polling and WebSocket-first runtime updates keep background work small.
- Migration coverage lives in `tests/test_void_workbench_integration.py`,
  `tests/test_task_bench.py`, `tests/test_change_review_api.py`, and
  `tests/test_workspace_api.py`.

## Performance rules

- Lazy-load each Workbench route.
- Subscribe only to the active route or a currently running job.
- Prefer WebSocket deltas; poll only as a disconnected recovery path.
- Never stream full trace history in routine state updates.
- Do not retain hidden webviews unless they contain an unsaved draft or run.
- Exclude runtime, experiment archives, dependencies and generated assets from
  file watching and search.

## Non-goals

- Do not squeeze DAG graphs, datasets or evolution evidence into the narrow Chat
  pane.
- Do not duplicate Void's editor, terminal, diff view, notifications or command
  palette inside React.
- Do not remove Identity, EGO, research or CoC capabilities; reorganize them
  around user workflows.
