# Transactional editing and checkpoints

This guide describes the IDE-native edit review implemented in Void 0.14 and the durable checkpoint
timeline in Studio. Agent changes are applied to the real file immediately, but remain independently
reviewable after a backend or IDE restart.

## Start the product

Install the declared Python and frontend dependencies, then start all three local services from the
repository root:

```powershell
python -m pip install -r requirements.txt
python start-all.py
```

Open Void through `http://127.0.0.1:8880/?folder=/C:/absolute/path/to/project` and Studio through
`http://127.0.0.1:8765/`. If an older Void window was already open while the extension was upgraded,
restart `start-all.py` once so the versioned `extension-v14.js` entry is installed.

## Review an Agent edit in the file

1. Let a DAG Agent use a Workspace write/edit/move/delete operation, or run **EgoAgent: Generate AI
   Multi-Hunk Edit**.
2. Open the changed file. Added material is green and removed/replaced source is rendered in red at
   the corresponding line.
3. Use the CodeLens immediately above each changed block:
   - **接受 Agent 改动** keeps the already-applied content.
   - **拒绝并恢复** restores only that block's base content.
   - **撤销接受 / 撤销拒绝** reverses only the decision. It does not undo the complete Agent edit.
4. Use the status-bar **Agent 改动** item or Chat → **改动** for file/global actions. Studio →
   **Agent 改动** exposes the same durable journal.

If you manually edit a file after the Agent edit, a destructive Reject becomes a revision conflict
instead of overwriting your work. Rejecting an Agent-created file always asks for explicit deletion
confirmation. Binary replacements and moves are reviewed as whole-file transactions.

## Inline Edit

Press `Ctrl+I` (`Cmd+I` on macOS), or choose **EgoAgent: Inline Edit: Cursor, Selection, or File**.

1. Choose **光标所在行**, **选区**, or **整个文件**.
2. Describe the change. The edit role generates a preview without mutating the file.
3. Inspect the red/green diff and choose:
   - **应用并进入逐段审阅**;
   - **继续追问改进** to refine the current draft;
   - **重新生成** from the original text; or
   - **取消**, which leaves the file byte-for-byte unchanged.
4. Applying checks the file revision, writes atomically, and creates the same durable per-hunk review
   transaction used by DAG Workspace tools.

When no configured model is available, the command provides a bounded local fallback for common
formatting, documentation, and error-handling instructions. Unsupported model roles are rejected
before the request starts.

## Checkpoint timeline

Open Studio → **检查点**.

1. Confirm the workspace path, enter a label, and list one file per line. Paths may be relative to
   the workspace. Harness, Identity, and Environment files are classified automatically.
2. Select a checkpoint on the timeline. Studio calculates every file's current SHA-256 revision and
   shows **无变化 / 恢复旧内容 / 重新创建 / 删除**.
3. Select only the files you want and click **恢复所选**. A deletion requires an additional dialog.
4. If any file changes after the preview, that file is skipped with a revision conflict; other
   selected files can still restore safely.
5. Each materialized restore is itself written to **Agent 改动**, so it remains inspectable and
   reversible instead of becoming an invisible overwrite.

Void → 上下文 → **检查点** captures the currently active file and records the selected Harness and
Identity in checkpoint metadata.

## Automated verification

Run the focused data-safety suite:

```powershell
python -m unittest tests.test_change_tracker tests.test_change_review_api tests.test_checkpoint_manager -v
```

The tests cover create/update/delete/empty/binary/move, stable ids, restart persistence, revision
conflicts, delete confirmation, checkpoint persistence, selective restore, post-preview conflicts,
and Harness/Identity/Environment classification.
