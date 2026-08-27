import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "void_extension" / "egoagent-dag-chat"


class VoidWorkbenchIntegrationTests(unittest.TestCase):
    def test_manifest_loads_the_versioned_native_extension(self):
        manifest = json.loads((EXTENSION / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "0.21.11")
        self.assertEqual(manifest["main"], "./extension-v21.js")
        self.assertEqual(manifest["browser"], manifest["main"])
        self.assertEqual(manifest["extensionKind"][0], "workspace")
        self.assertTrue((EXTENSION / manifest["main"][2:]).is_file())

    def test_packaged_workbench_uses_relative_assets(self):
        html = (EXTENSION / "workbench" / "index.html").read_text(encoding="utf-8")
        assets = re.findall(r'(?:src|href)="([^"]+)"', html)
        self.assertTrue(any(value.startswith("./assets/") for value in assets), assets)
        self.assertFalse(any(value.startswith("/") for value in assets), assets)
        for value in assets:
            if value.startswith("./"):
                self.assertTrue((EXTENSION / "workbench" / value[2:]).is_file(), value)

    def test_native_bridge_supports_routes_context_and_hunk_review(self):
        source = (EXTENSION / "extension-v21.js").read_text(encoding="utf-8")
        self.assertIn("route-change", source)
        self.assertIn("context-handoff", source)
        self.assertIn("review-change", source)
        self.assertIn("open-file", source)
        self.assertIn("window.__EGOAGENT_WORKBENCH__", source)
        self.assertRegex(
            source,
            r"createWebviewPanel\('egoagent\.workbench'[\s\S]{0,400}retainContextWhenHidden: false",
        )

    def test_workbench_navigation_projects_branching_and_themes_are_discoverable(self):
        app = (ROOT / "harness_editor" / "src" / "App.tsx").read_text(encoding="utf-8")
        sessions = (ROOT / "harness_editor" / "src" / "components" / "SessionExplorer.tsx").read_text(encoding="utf-8")
        heart_flow = (ROOT / "harness_editor" / "src" / "heartflow" / "HeartFlowDemo.tsx").read_text(encoding="utf-8")
        project_dialog = (ROOT / "harness_editor" / "src" / "components" / "ProjectDialog.tsx").read_text(encoding="utf-8")
        extension = (EXTENSION / "extension-v21.js").read_text(encoding="utf-8")

        # The popup must be a toolbar sibling, not a child of the scrolling
        # nav that used to clip it and make More look unresponsive.
        self.assertRegex(app, r"</nav> : <div[\s\S]{0,300}EMBEDDED_IN_IDE && showAdvancedNavigation")
        self.assertIn('aria-label="Workbench 主题"', app)
        self.assertIn("Project = workspace 文件夹", sessions)
        self.assertIn("＋ Project", sessions)
        self.assertIn("选择已有文件夹", project_dialog)
        self.assertIn("创建新文件夹", project_dialog)
        self.assertIn("pick-project-folder", extension)
        self.assertIn("SessionBranchDialog", heart_flow)
        self.assertIn("⑂ Fork", heart_flow)
        self.assertIn("⇄ Merge", heart_flow)

    def test_editor_review_has_visible_per_block_accept_and_refuse_actions(self):
        source = (EXTENSION / "extension-v21.js").read_text(encoding="utf-8")
        manifest = json.loads((EXTENSION / "package.json").read_text(encoding="utf-8"))
        self.assertIn("registerCodeLensProvider(DOCUMENT_SELECTOR, this)", source)
        self.assertIn("registerInlayHintsProvider(DOCUMENT_SELECTOR, this)", source)
        self.assertIn("provideInlayHints(document)", source)
        self.assertNotIn("provideInlayHints(document, requestedRange)", source)
        self.assertIn("pendingBackendChangesForDocument(document)", source)
        self.assertIn("for (const change of this.pendingBackendChangesForDocument(document))", source)
        self.assertIn("filter(isMaterializedReviewChange)", source)
        self.assertIn("getConfiguration('editor', document.uri).get('codeLens', true)", source)
        self.assertIn("$(diff) Review Diff", source)
        self.assertIn("✓ Accept", source)
        self.assertIn("↶ Refuse", source)
        self.assertIn("this.localHunkLine(proposal, hunk)", source)
        self.assertIn("openBackendDiff(changeSelector, hunkId, options = {})", source)
        self.assertTrue(manifest["contributes"]["configuration"]["properties"]["egoagent.review.inlineActions"]["default"])
        self.assertTrue(manifest["contributes"]["configuration"]["properties"]["egoagent.review.preferInlineDiff"]["default"])
        self.assertTrue(manifest["contributes"]["configurationDefaults"]["diffEditor.codeLens"])
        self.assertIn("affectsConfiguration('diffEditor.codeLens')", source)
        self.assertIn("getConfiguration('diffEditor', document.uri).get('codeLens', true)", source)

    def test_startup_flattens_native_diff_word_highlights(self):
        launcher = (ROOT / "start-all.py").read_text(encoding="utf-8")
        self.assertIn("egoagent-flat-review-diff-v2", launcher)
        self.assertIn(".monaco-diff-editor .char-delete", launcher)
        self.assertIn(".monaco-diff-editor .char-insert", launcher)
        self.assertIn("background-color: transparent !important", launcher)
        self.assertIn("configure_native_review_styles()", launcher)
        self.assertIn("workbench.css?{WORKBENCH_CACHE_KEY}", launcher)
        self.assertIn("'/workbench/workbench.css'", launcher)
        self.assertIn("egoagent-review-toolbar", launcher)
        self.assertIn("justify-content: flex-end", launcher)
        self.assertIn("enhanceReviewToolbar", launcher)
        self.assertIn("text.includes('Accept')", launcher)
        self.assertIn("text.includes('Refuse')", launcher)

    def test_change_file_names_open_the_real_workspace_file(self):
        extension = (EXTENSION / "extension-v21.js").read_text(encoding="utf-8")
        chat = (EXTENSION / "media" / "chat.js").read_text(encoding="utf-8")
        css = (EXTENSION / "media" / "chat.css").read_text(encoding="utf-8")
        self.assertGreaterEqual(chat.count('data-open-change-file='), 2)
        self.assertIn("type: 'openChangeFile'", chat)
        self.assertIn("message.type === 'openChangeFile'", extension)
        self.assertIn("absolutePath: message.path", extension)
        self.assertIn(".change-file-link", css)

    def test_native_chat_distinguishes_waiting_for_input_from_running(self):
        extension = (EXTENSION / "extension-v21.js").read_text(encoding="utf-8")
        chat = (EXTENSION / "media" / "chat.js").read_text(encoding="utf-8")
        self.assertIn("execution.waiting_for_input", extension)
        self.assertIn("snapshot.waitingForInput ? ' · 等待输入'", extension)
        self.assertIn("status.waitingForInput ? '等待输入'", chat)
        self.assertIn("type === 'input_required'", chat)
        self.assertIn("return state.waitingForInput ||", chat)
        self.assertRegex(
            chat,
            r"state\.running \? 1 : 0,\s*state\.waitingForInput \? 1 : 0,",
        )
        self.assertIn("|| execution.waiting_for_input", chat)
        self.assertIn("model_output_truncated", chat)

        app = (ROOT / "harness_editor" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("waitingForInput: Boolean(execState.waiting_for_input || waitingNodeId)", app)
        self.assertIn("本轮已完成 · 等待输入", app)

    def test_native_chat_collapses_routine_agent_process_and_shows_live_activity(self):
        extension = (EXTENSION / "extension-v21.js").read_text(encoding="utf-8")
        chat = (EXTENSION / "media" / "chat.js").read_text(encoding="utf-8")
        css = (EXTENSION / "media" / "chat.css").read_text(encoding="utf-8")

        self.assertIn('id="agentActivity"', extension)
        self.assertIn("function setAgentActivity(text, kind = 'running')", chat)
        self.assertIn("type === 'model_request'", chat)
        self.assertIn("正在生成回答", chat)
        self.assertIn("function isRoutineProcess(message)", chat)
        self.assertIn("const isInternalWorker = publicAgents.size > 0", chat)
        self.assertIn('class="bubble process-bubble"', chat)
        self.assertNotIn("event-card' + (blocked ? ' blocked' : '') + '\" open", chat)
        self.assertIn(".agent-activity.running", css)
        self.assertIn(".process-card", css)

    def test_casual_greeting_skips_repo_context_retrieval(self):
        chat = (EXTENSION / "media" / "chat.js").read_text(encoding="utf-8")
        harness = json.loads((ROOT / "harness" / "adaptive_code_agent" / "config.json").read_text(encoding="utf-8"))
        discovery = json.loads((ROOT / "harness" / "component_capability_discovery" / "config.json").read_text(encoding="utf-8"))

        self.assertIn("function casualTurnText(text, pastedContexts = [])", chat)
        self.assertIn("contexts.length === 1 && contexts[0]?.kind === 'clipboard'", chat)
        self.assertIn("const requestText = casualText || text", chat)
        self.assertIn("state.contextPlan = casualText ? null : await buildContextPlan", chat)
        self.assertIn("runBody({ text: requestText + contextBlock })", chat)
        self.assertIn("needs_workflow", harness["pipeline"]["nodes"])
        self.assertFalse(harness["pipeline"]["nodes"]["discover"]["share_session"])
        self.assertFalse(discovery["component"]["share_session"])

    def test_pasted_plain_greeting_is_semantically_the_same_as_typed_greeting(self):
        chat = (EXTENSION / "media" / "chat.js").read_text(encoding="utf-8")
        start = chat.index("  const casualPrompts")
        end = chat.index("  const persist", start)
        helper_source = chat[start:end]
        script = f"""
const assert = require('node:assert/strict');
const source = {json.dumps(helper_source)};
const helpers = new Function(source + '\\nreturn {{ isCasualPrompt, casualTurnText }}')();
const reference = '[文本附件: Clipboard · 1 line]';
assert.equal(helpers.casualTurnText('你好', []), '你好');
assert.equal(helpers.casualTurnText('说话啊', []), '说话啊');
assert.equal(helpers.casualTurnText(reference, [{{kind:'clipboard', content:'你好', reference}}]), '你好');
assert.equal(helpers.casualTurnText(reference, [{{kind:'clipboard', content:'请修复 bug', reference}}]), '');
assert.equal(helpers.casualTurnText('[代码附件: garden.py:1-4]', [{{kind:'selection', content:'你好', reference:'[代码附件: garden.py:1-4]'}}]), '');
"""
        result = subprocess.run(
            ["node", "-e", script], cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_chat_keeps_string_run_ids_and_respects_backend_turn_boundaries(self):
        chat = (EXTENSION / "media" / "chat.js").read_text(encoding="utf-8")
        self.assertIn("const runId = String(execution.run_id || state.runId || '')", chat)
        self.assertIn("Boolean(output.sealed)", chat)
        self.assertIn("item.sealed && item.text === snapshotText", chat)
        self.assertIn("message ||= state.messages.find", chat)
        self.assertNotIn("Number(execution.run_id", chat)

    def test_editor_and_terminal_selections_paste_as_structured_chat_context(self):
        manifest = json.loads((EXTENSION / "package.json").read_text(encoding="utf-8"))
        extension = (EXTENSION / "extension-v21.js").read_text(encoding="utf-8")
        chat = (EXTENSION / "media" / "chat.js").read_text(encoding="utf-8")
        css = (EXTENSION / "media" / "chat.css").read_text(encoding="utf-8")

        commands = {item["command"] for item in manifest["contributes"]["commands"]}
        self.assertIn("egoagent.copyEditorContext", commands)
        self.assertIn("egoagent.copyTerminalContext", commands)
        self.assertIn("egoagent.attachFileToChat", commands)
        self.assertIn("egoagent.attachSelectionToChat", commands)
        keybindings = {item["command"]: item for item in manifest["contributes"]["keybindings"]}
        self.assertEqual(keybindings["egoagent.copyEditorContext"]["key"], "ctrl+c")
        self.assertIn("editorHasSelection", keybindings["egoagent.copyEditorContext"]["when"])
        self.assertEqual(keybindings["egoagent.copyTerminalContext"]["key"], "ctrl+c")
        self.assertIn("terminalTextSelected", keybindings["egoagent.copyTerminalContext"]["when"])

        self.assertIn("function selectionLineRange(selection)", extension)
        self.assertIn("resolveContextPaste(message)", extension)
        self.assertIn("openContextLocation(context)", extension)
        self.assertIn("workbench.action.terminal.copySelection", extension)
        self.assertIn("startLine: range.startLine", extension)
        self.assertIn("endLine: range.endLine", extension)

        self.assertIn("pastedContexts: []", chat)
        self.assertNotIn("function contextCardHtml(context, removable)", chat)
        self.assertIn("plainPasteArmed", chat)
        self.assertIn("event.preventDefault()", chat)
        self.assertIn("type: 'resolveContextPaste'", chat)
        self.assertIn("message.type === 'contextPasteResolved'", chat)
        self.assertIn("pendingContextPastes: new Map()", chat)
        self.assertIn("function attachmentReference(context)", chat)
        self.assertIn("function insertComposerAttachmentPlaceholder(requestId)", chat)
        self.assertIn("function resolveComposerAttachmentPlaceholder(requestId, context = null)", chat)
        self.assertIn("className = 'inline-attachment'", chat)
        self.assertIn("function composerText()", chat)
        self.assertIn("event.key === 'Backspace'", chat)
        self.assertIn("state.lastComposerMutation?.kind === 'attachment'", chat)
        self.assertIn("reference: item.reference || ''", chat)
        self.assertIn("附件仍在识别", chat)
        self.assertIn("inline-attachment[data-context-id]", chat)
        self.assertIn("start_line: item.startLine", chat)
        self.assertIn("end_line: item.endLine", chat)
        self.assertIn("data-open-context", chat)
        self.assertIn("type: 'resolveContextDrop'", chat)
        self.assertIn("document.addEventListener('drop', handleContextDrop, true)", chat)
        self.assertIn("ResourceURLs / CodeEditors", chat)
        self.assertIn("egoagent-drop-target-register", chat)
        self.assertIn("egoagent-workbench-resource-drop", chat)
        self.assertIn("message.type === 'externalContextsAttached'", chat)
        self.assertIn("message.type === 'resolveContextDrop'", extension)
        self.assertIn("contextForDroppedResource", extension)
        self.assertIn("attachResourcesToChat(uri, selectedUris, selectionOnly = false)", extension)
        self.assertIn('data-attach-kind="file"', extension)
        self.assertIn('data-attach-kind="selection"', extension)
        self.assertIn('data-attach-kind="workspace"', extension)
        self.assertIn("requestedKind === 'workspace'", chat)
        self.assertIn(".inline-attachment", css)
        self.assertIn(".attachment-editor", css)
        self.assertIn("white-space: pre", css)

    def test_clipboard_context_is_not_duplicated_and_can_be_edited_in_place(self):
        extension = (EXTENSION / "extension-v21.js").read_text(encoding="utf-8")
        chat = (EXTENSION / "media" / "chat.js").read_text(encoding="utf-8")
        self.assertIn('id="attachmentEditor"', extension)
        self.assertIn("function openAttachmentEditor(context, editable)", chat)
        self.assertIn("function saveAttachmentEditor()", chat)
        self.assertIn("点击查看并编辑", chat)
        self.assertIn("$('contextChips').innerHTML = chips.join('');", chat)
        self.assertNotIn("state.pastedContexts.filter((context) => context.kind === 'clipboard').map", chat)

    def test_removed_review_lines_use_native_diff_instead_of_layout_hacks(self):
        extension = (EXTENSION / "extension-v21.js").read_text(encoding="utf-8")
        self.assertIn("const removedOption = (line, oldLines, label, oldStart)", extension)
        self.assertIn("gutterIconPath", extension)
        self.assertIn("contentText: `  −${deletedCount} 行已删除`", extension)
        self.assertIn("backgroundColor: new vscode.ThemeColor('diffEditor.removedTextBackground')", extension)
        self.assertIn("hover.appendCodeblock", extension)
        self.assertIn("toggle.diff.renderSideBySide", extension)
        self.assertNotIn("display: block; white-space: pre", extension)
        self.assertNotIn("join(' ⏎ ')", extension)
        self.assertNotIn("rejectedDecoration", extension)

    def test_changes_tab_contains_only_unresolved_review_items(self):
        chat = (EXTENSION / "media" / "chat.js").read_text(encoding="utf-8")
        self.assertIn("state.localProposals.filter(needsReview).map(localProposalHtml)", chat)
        self.assertIn("state.backendChanges.filter(needsReview).map(backendChangeHtml)", chat)
        self.assertIn("const reviewHunks = pendingReviewHunks(proposal)", chat)
        self.assertIn("const hunks = pendingReviewHunks(change)", chat)

        start = chat.index("  function pendingReviewHunks")
        end = chat.index("  function renderDiffLines", start)
        helper_source = chat[start:end]
        script = f"""
const assert = require('node:assert/strict');
const helpers = new Function({json.dumps(helper_source)} + '\\nreturn {{ pendingReviewHunks, needsReview }};')();
const partial = {{status:'partial', hunks:[
  {{id:'accepted', status:'accepted'}},
  {{id:'pending', status:'pending'}},
]}};
assert.deepEqual(helpers.pendingReviewHunks(partial).map((item) => item.id), ['pending']);
assert.equal(helpers.needsReview(partial), true);
assert.equal(helpers.needsReview({{status:'accepted', hunks:[{{status:'accepted'}}]}}), false);
assert.equal(helpers.needsReview({{status:'rejected', hunks:[{{status:'rejected'}}]}}), false);
assert.equal(helpers.needsReview({{status:'conflict', hunks:[]}}), true);
"""
        result = subprocess.run(
            ["node", "-e", script], cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_native_diff_reconstructs_a_pure_deletion_without_collapsing_lines(self):
        extension = (EXTENSION / "extension-v21.js").read_text(encoding="utf-8")
        start = extension.index("function splitLines(text)")
        end = extension.index("function fullDocumentRange", start)
        helper_source = extension[start:end]
        script = f"""
const assert = require('node:assert/strict');
const source = {json.dumps(helper_source)};
const reconstruct = new Function(source + '\\nreturn reconstructTrackedOriginal;')();
const current = 'head\\ntail\\n';
const change = {{hunks:[{{old_start:1, old_lines:['old one\\n','old two\\n'], new_lines:[], status:'pending'}}]}};
assert.equal(reconstruct(current, change, () => 1), 'head\\nold one\\nold two\\ntail\\n');
const accepted = {{hunks:[{{old_start:1, old_lines:['old\\n'], new_lines:['new\\n'], status:'accepted'}}]}};
assert.equal(reconstruct('head\\nnew\\ntail\\n', accepted, () => 1), 'head\\nnew\\ntail\\n');
const rejected = {{hunks:[{{old_start:1, old_lines:['old\\n'], new_lines:['new\\n'], status:'rejected'}}]}};
assert.equal(reconstruct('head\\nold\\ntail\\n', rejected, () => 1), 'head\\nold\\ntail\\n');
"""
        result = subprocess.run(
            ["node", "-e", script], cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pending_agent_change_auto_opens_editable_inline_diff(self):
        source = (EXTENSION / "extension-v21.js").read_text(encoding="utf-8")
        self.assertIn("openPendingReviewForEditor(editor)", source)
        self.assertIn("void this.openPendingReviewForEditor(vscode.window.activeTextEditor)", source)
        self.assertIn("const after = useLiveEditor ? fileUri", source)
        self.assertIn("await this.preferInlineDiff()", source)
        self.assertIn("reconcileBackendReview(changeSelector, options = {})", source)
        self.assertIn("await this.reviewManager.reconcileBackendReview", source)

    def test_inline_review_is_scoped_to_the_selected_run_transaction(self):
        extension = (EXTENSION / "extension-v21.js").read_text(encoding="utf-8")
        chat = (EXTENSION / "media" / "chat.js").read_text(encoding="utf-8")
        self.assertIn("activeBackendTransactionId", extension)
        self.assertIn("activeBackendChanges()", extension)
        self.assertIn("selectBackendTransaction(transactionId)", extension)
        self.assertIn("latestPendingReviewTransaction(changes)", extension)
        self.assertIn("execution.change_transaction_id", extension)
        self.assertIn("execution.pipeline_run_id", extension)
        self.assertIn("activeTransactionId,", chat)
        self.assertIn("changeTransactionId", chat)
        self.assertIn("data-review-transaction", chat)
        self.assertIn("shouldAdoptExecutionSnapshot(state.runId, execution)", chat)
        self.assertNotIn("return runId.startsWith('run-')", chat)
        self.assertIn("type === 'run_started'", chat)
        self.assertIn("data.change_transaction_id", chat)

        transaction_start = extension.index("function changesForReviewTransaction")
        transaction_end = extension.index("function fullDocumentRange", transaction_start)
        transaction_source = extension[transaction_start:transaction_end]
        snapshot_start = chat.index("  function shouldAdoptExecutionSnapshot")
        snapshot_end = chat.index("  function resetConversationForWorkspace", snapshot_start)
        snapshot_source = chat[snapshot_start:snapshot_end]
        script = f"""
const assert = require('node:assert/strict');
const transactionHelpers = new Function({json.dumps(transaction_source)} + '\\nreturn {{ changesForReviewTransaction, latestPendingReviewTransaction }};')();
const select = transactionHelpers.changesForReviewTransaction;
const adopt = new Function({json.dumps(snapshot_source)} + '\\nreturn shouldAdoptExecutionSnapshot;')();
const changes = [
  {{id:'old', transaction_id:'run-old'}},
  {{id:'current', transaction_id:'run-current'}},
  {{id:'unscoped'}},
];
assert.deepEqual(select(changes, ''), []);
assert.deepEqual(select(changes, 'run-current').map((item) => item.id), ['current']);
assert.equal(transactionHelpers.latestPendingReviewTransaction([
  {{transaction_id:'run-old', timestamp:1, hunks:[{{status:'pending'}}]}},
  {{transaction_id:'run-resolved', timestamp:3, hunks:[{{status:'accepted'}}]}},
  {{transaction_id:'run-new', timestamp:2, hunks:[{{status:'pending'}}]}},
]), 'run-new');
assert.equal(adopt('', {{running:false, waiting_for_input:false, run_id:'completed-history'}}), false);
assert.equal(adopt('', {{running:true, waiting_for_input:false}}), true);
assert.equal(adopt('', {{running:false, waiting_for_input:true}}), true);
assert.equal(adopt('selected-run', {{running:false, waiting_for_input:false}}), true);
"""
        result = subprocess.run(
            ["node", "-e", script], cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_startup_installs_cross_iframe_explorer_drag_bridge(self):
        launcher = (ROOT / "start-all.py").read_text(encoding="utf-8")
        self.assertIn("egoagent-resource-drop-bridge-v1", launcher)
        self.assertIn("ResourceURLs", launcher)
        self.assertIn("CodeEditors", launcher)
        self.assertIn("event.ports[0]", launcher)

    def test_chat_config_markdown_and_run_identity_are_explicit(self):
        extension = (EXTENSION / "extension-v21.js").read_text(encoding="utf-8")
        chat = (EXTENSION / "media" / "chat.js").read_text(encoding="utf-8")
        css = (EXTENSION / "media" / "chat.css").read_text(encoding="utf-8")
        self.assertIn('id="agentConfigDetails"', extension)
        self.assertIn("configExpanded: saved.configExpanded === true", chat)
        self.assertIn("function renderMarkdown(value)", chat)
        self.assertIn("renderMarkdown(message.text)", chat)
        self.assertIn(".markdown-body", css)
        self.assertIn("state.runId = String(result.run_id", chat)
        self.assertIn("/api/execution/state' + runQuery()", chat)
        self.assertIn("runBody({ text: requestText + contextBlock })", chat)
        self.assertIn("Number(error?.status) !== 404", chat)
        self.assertIn("function detachFromExecutionSelection()", chat)
        self.assertGreaterEqual(chat.count("detachFromExecutionSelection();"), 4)

    def test_review_decisions_use_ctrl_z_without_visible_undo_buttons(self):
        manifest = json.loads((EXTENSION / "package.json").read_text(encoding="utf-8"))
        extension = (EXTENSION / "extension-v21.js").read_text(encoding="utf-8")
        chat = (EXTENSION / "media" / "chat.js").read_text(encoding="utf-8")
        bindings = {item["command"]: item for item in manifest["contributes"]["keybindings"]}
        binding = bindings["egoagent.undoLatestReviewDecision"]
        self.assertEqual(binding["key"], "ctrl+z")
        self.assertIn("egoagent.reviewDecisionAvailable", binding["when"])
        self.assertIn("backendHunkLine(change, targetHunk)", extension)
        self.assertIn("this.backendHunkLine(change, hunk)", extension)
        self.assertIn("latestUndoTarget(document)", extension)
        self.assertIn("undoLatestReviewDecision()", extension)
        self.assertIn("reconcileBackendReview(changeSelector, options = {})", extension)
        self.assertIn("reopenPending: endpoint === 'undo'", extension)
        self.assertIn("hunk.status === 'pending' && String(hunk.id) === String(options.hunkId || '')", extension)
        self.assertNotIn("↶ Undo ${entry.status", extension)
        self.assertNotIn("撤销决定</button>", chat)

    def test_subflow_agent_clones_are_renamed_to_the_child_slot(self):
        engine = (ROOT / "pipeline_engine.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(engine.count("cloned_agent.name = slot_name"), 2)

    def test_embedded_workbench_and_sessions_remain_operable_when_narrow(self):
        session_explorer = (ROOT / "harness_editor" / "src" / "components" / "SessionExplorer.tsx").read_text(encoding="utf-8")
        css = (ROOT / "harness_editor" / "src" / "index.css").read_text(encoding="utf-8")

        self.assertIn('className="session-explorer"', session_explorer)
        self.assertIn('className="session-explorer-list"', session_explorer)
        self.assertIn('className="session-explorer-detail"', session_explorer)
        self.assertIn(".workbench-route-tabs::-webkit-scrollbar", css)
        self.assertIn(".session-explorer { flex-direction: column", css)
        self.assertIn(".session-explorer-list { width: 100% !important", css)

    def test_packaged_bootstrap_marks_the_workbench_as_ide_embedded(self):
        runtime = (ROOT / "harness_editor" / "src" / "api" / "runtime.ts").read_text(encoding="utf-8")
        app = (ROOT / "harness_editor" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("Boolean(window.__EGOAGENT_WORKBENCH__)", runtime)
        self.assertIn("import { EMBEDDED_IN_IDE,", app)
        self.assertNotIn("const EMBEDDED_IN_IDE = new URLSearchParams", app)


if __name__ == "__main__":
    unittest.main()
