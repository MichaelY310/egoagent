# EgoAgent DAG Chat for Void

This local extension integrates EgoAgent into Void's native Chat container. It
does not create a floating overlay and never covers the editor.

## No-key IDE features

- Multi-line inline Tab suggestions and symbol completion
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
