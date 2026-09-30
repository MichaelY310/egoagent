# EgoAgent DAG Chat for Void

This local extension integrates EgoAgent into Void's native Chat container. It
does not create a floating overlay and never covers the editor.

## Code completion

The configured `autocomplete` model role powers native inline ghost text.
Pause typing (280 ms debounce), then **Tab** to accept, **Esc** to dismiss,
**Ctrl+Right** to accept the next word, or **Ctrl+Alt+Right** for the next line.
**Alt+Backslash** manually requests a suggestion. **Ctrl+Z** uses the editor's
normal undo stack. Click the EgoAgent Tab status item to pause/resume.

Requests are cancellable and bounded (8 seconds by default). Stale responses
are discarded. Content-based caching supports backspace and partial typing.
With no model, only identifiers already in the document can be suggested;
there are no fake TODO implementations. Optional open-file context is off by
default, scoped to the same workspace, and excludes sensitive files.

See [completion usage and settings](../../docs/AUTOCOMPLETE_ZH.md).
The retired interactive recording tutorial no longer intercepts user input.

## Other IDE features

- Model-backed multi-line Tab suggestions; offline same-file word completion
- `Ctrl+I` local inline edits
- Deterministic multi-hunk mock Agent (`Ctrl+Alt+M`)
- Per-hunk Accept/Reject in the Chat view and as editor CodeLens actions
- Native red/green Diff editor and accepted/rejected line decorations
- Local security/quality Quick Review diagnostics
- `@file` / `@selection` editor context, symbols, rules, memory, and checkpoints
- Local code map, application preview, terminal command approval, and Git commit-message drafts

The DAG backend remains available for real model-driven work. Its file writes
use the same per-hunk review surface.
It deliberately avoids floating overlays: chat and execution controls live in the
sidebar, while the complete Agent Workbench opens as an editor tab.

The view supports Harness and Identity selection, per-slot bindings, one-message
DAG startup, live node progress, tool and blocked-call cards, nested Harness
events, execution control, project memory/rules, checkpoints, and session history.
