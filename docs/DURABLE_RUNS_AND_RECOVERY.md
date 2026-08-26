# Durable runs, checkpoints, and recovery

EgoAgent checkpoint format v3 makes long Agent runs recoverable without replaying nodes that have
already completed.

## What is saved

Every durable checkpoint contains:

- exact current and next node plus `in_flight` or `completed` phase;
- run/session data, full messages, typed node outputs, result, and usage/cost statistics;
- workspace, Harness, and per-slot Identity content revisions;
- permission policy, approved and pending approvals;
- change-transaction summary and stable transaction id;
- collected artifacts, completed-step ledger, and nested child-run tree.

Authorized secret values are redacted before the JSON file is written.

## Exact resume behavior

Durable Studio/API runs enable automatic checkpoints. Potentially side-effecting nodes first write an
`in_flight` checkpoint. When the node returns and its output is published, a `completed` checkpoint
points to the exact next node. A worker restart resumes from the latter and does not call the completed
model, tool, process, Map, Loop step, or child Harness again.

There is no honest way to infer whether an arbitrary external side effect completed if the process
dies during the call. Therefore an `in_flight` run becomes `interrupted` and requires inspection and
explicit confirmation. EgoAgent never silently guesses.

## Revision conflicts

The runtime compares current workspace, Harness, and Identity revisions with the checkpoint before
restoring it. A newer manual edit raises a structured `PipelineRevisionConflict`; no file is written.
The recovery API can override this only with explicit `allow_revision_conflicts`, and records the
accepted conflicts in run state.

## Studio workflow

When Studio starts, interrupted runs appear in a compact card at the upper-right:

1. expand a run to inspect the interrupted node, phase, pending approvals, completed steps, artifacts,
   child runs, and revisions;
2. choose **继续** for a safe completed checkpoint;
3. for an in-flight node, inspect its filesystem/external effects and confirm that re-execution is
   acceptable;
4. choose **丢弃记录** to cancel the run without deleting its existing files or artifacts.

## HTTP API

```text
GET  /api/runs/recovery
GET  /api/runs/{run_id}
POST /api/runs/{run_id}/resume
POST /api/runs/{run_id}/discard
```

Resuming an uncertain node requires:

```json
{"confirm_in_doubt": true}
```

## Verification

```powershell
python -m unittest discover -s tests -p "test_checkpoint_recovery.py" -v
python -m unittest discover -s tests -p "test_run_coordinator.py" -v
cd harness_editor
npm run build
```

The recovery integration test deliberately crashes after model, tool, process, Map, Loop, and child
Harness nodes and verifies that the completed operation is not replayed. It also verifies manual-edit
conflicts and the in-flight confirmation gate.
