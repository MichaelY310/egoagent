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
        self.assertEqual(manifest["version"], "0.21.24")
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
        session_create_dialog = (ROOT / "harness_editor" / "src" / "components" / "SessionCreateDialog.tsx").read_text(encoding="utf-8")
        branch_dialog = (ROOT / "harness_editor" / "src" / "components" / "SessionBranchDialog.tsx").read_text(encoding="utf-8")
        extension = (EXTENSION / "extension-v21.js").read_text(encoding="utf-8")

        # More is a real route instead of a clipped/disappearing popup. Every
        # click now produces a persistent page with explicit destinations.
        self.assertIn("function MoreWorkbench", app)
        self.assertIn("{tab === 'more' &&", app)
        self.assertIn("更多 EgoAgent 工作台", app)
        self.assertNotIn("showAdvancedNavigation", app)
        self.assertIn('aria-label="Workbench 主题"', app)
        self.assertIn("Project = workspace 文件夹", sessions)
        self.assertIn("＋ Project", sessions)
        self.assertIn("＋ Session", sessions)
        self.assertIn("onDoubleClick", sessions)
        self.assertIn("onContextMenu", sessions)
        self.assertIn('role="menu"', sessions)
        self.assertIn("checkedSessions", sessions)
        self.assertIn("Move session to trash", sessions)
        self.assertIn("createPortfolioSession", session_create_dialog)
        self.assertIn("此 Session 的 Agent 配置", session_create_dialog)
        self.assertIn("agent_config:", session_create_dialog)
        self.assertIn("listHarnesses", session_create_dialog)
        self.assertIn("mergeManySessions", branch_dialog)
        self.assertIn("Agent Communication", branch_dialog)
        self.assertIn("选择已有文件夹", project_dialog)
        self.assertIn("创建新文件夹", project_dialog)
        self.assertIn("pick-project-folder", extension)
        self.assertIn("SessionBranchDialog", heart_flow)
        self.assertIn("⑂ Fork", heart_flow)
        self.assertIn("⇄ Merge", heart_flow)

    def test_packaging_updates_the_extension_directory_void_actually_serves(self):
        package_script = (ROOT / "harness_editor" / "scripts" / "package-extension.mjs").read_text(encoding="utf-8")
        self.assertIn("canonicalWorkbench", package_script)
        self.assertIn("runtimeWorkbench", package_script)
        self.assertIn("runtimeMedia", package_script)
        self.assertIn("'void-web', 'extensions', 'egoagent-dag-chat'", package_script)
        self.assertIn("await syncDirectory(source, runtimeWorkbench)", package_script)
        self.assertIn("await syncDirectory(canonicalMedia, runtimeMedia)", package_script)

    def test_explicit_dark_theme_does_not_inherit_light_ide_tokens(self):
        css = (ROOT / "harness_editor" / "src" / "index.css").read_text(encoding="utf-8")
        dark_block = css[css.index(':root[data-theme="dark"]'):css.index(':root[data-theme="light"]')]
        self.assertIn("--bg: #1e1e1e", dark_block)
        self.assertIn("--surface-1: #181818", dark_block)
        self.assertIn("--surface-raised: #252526", dark_block)
        self.assertIn("--input-background: #242424", dark_block)
        self.assertNotIn("var(--vscode-", dark_block)

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

    def test_workbench_projects_real_child_runs_and_flow_mutations(self):
        app = (ROOT / "harness_editor" / "src" / "App.tsx").read_text(encoding="utf-8")
        task_bench = (ROOT / "harness_editor" / "src" / "components" / "TaskBench.tsx").read_text(encoding="utf-8")
        topology = (ROOT / "harness_editor" / "src" / "runtimeTopology.ts").read_text(encoding="utf-8")
        live = (ROOT / "harness_editor" / "src" / "components" / "LiveAgentArchitecture.tsx").read_text(encoding="utf-8")
        node = (ROOT / "harness_editor" / "src" / "nodes" / "PipelineNode.tsx").read_text(encoding="utf-8")
        css = (ROOT / "harness_editor" / "src" / "index.css").read_text(encoding="utf-8")

        self.assertIn("runtimeEventBelongsToRoot", app)
        self.assertIn("reduceRuntimeRunEvent", app)
        self.assertIn("normalizeMutationPayload", app)
        self.assertIn("diffFlowGraphs", app)
        self.assertIn("<LiveAgentArchitecture", app)
        self.assertIn("deriveRuntimeRuns", task_bench)
        self.assertIn("live-story", live)
        self.assertIn("live-mutation-story", live)
        self.assertIn("parent_run_id", topology)
        self.assertIn("subagent_spawned", topology)
        self.assertIn("harness_mutation", topology)
        self.assertIn("_mutationState", node)
        self.assertIn("mutation-${mutationState}", node)
        self.assertIn(".live-run-children", css)
        self.assertIn(".node-mutation-badge", css)

    def test_task_replay_normalizes_legacy_chat_messages_before_rendering(self):
        app = (ROOT / "harness_editor" / "src" / "App.tsx").read_text(encoding="utf-8")
        projection = (ROOT / "harness_editor" / "src" / "executionProjection.ts").read_text(encoding="utf-8")
        main = (ROOT / "harness_editor" / "src" / "main.tsx").read_text(encoding="utf-8")
        boundary = (ROOT / "harness_editor" / "src" / "components" / "WorkbenchErrorBoundary.tsx").read_text(encoding="utf-8")

        self.assertIn("normalizeChatMessages(taskRun.outputs)", app)
        self.assertIn("normalizeChatMessages(state.outputs)", app)
        self.assertIn("export function normalizeChatMessages", projection)
        self.assertIn("Array.isArray(item.tools)", projection)
        self.assertIn("Array.isArray(item.blocked)", projection)
        self.assertIn("<WorkbenchErrorBoundary>", main)
        self.assertIn("getDerivedStateFromError", boundary)

    def test_casual_greeting_skips_repo_context_retrieval(self):
        chat = (EXTENSION / "media" / "chat.js").read_text(encoding="utf-8")
        harness = json.loads((ROOT / "harness" / "adaptive_code_agent" / "config.json").read_text(encoding="utf-8"))
        discovery = json.loads((ROOT / "harness" / "component_capability_discovery" / "config.json").read_text(encoding="utf-8"))

        self.assertIn("function casualTurnText(text, pastedContexts = [])", chat)
        self.assertIn("contexts.length === 1 && contexts[0]?.kind === 'clipboard'", chat)
        self.assertIn("const requestText = casualText || text", chat)
        self.assertIn("state.contextPlan = casualText ? null : await buildContextPlan", chat)
        self.assertIn("initialInput: submittedText", chat)
        self.assertIn("runBody({ text: submittedText })", chat)
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
        self.assertIn("egoagent.attachTerminalSelectionToChat", commands)
        self.assertIn("egoagent.attachFileToChat", commands)
        self.assertIn("egoagent.attachSelectionToChat", commands)
        keybindings = {item["command"]: item for item in manifest["contributes"]["keybindings"]}
        self.assertEqual(keybindings["egoagent.copyEditorContext"]["key"], "ctrl+c")
        self.assertIn("editorHasSelection", keybindings["egoagent.copyEditorContext"]["when"])
        self.assertEqual(keybindings["egoagent.copyTerminalContext"]["key"], "ctrl+shift+c")
        self.assertIn("terminalTextSelected", keybindings["egoagent.copyTerminalContext"]["when"])
        self.assertNotIn("terminal/context", manifest["contributes"]["menus"])
        terminal_title_actions = [
            item for item in manifest["contributes"]["menus"]["view/title"]
            if item["command"] == "egoagent.attachTerminalSelectionToChat"
        ]
        self.assertEqual(len(terminal_title_actions), 1)
        self.assertIn("view == terminal", terminal_title_actions[0]["when"])
        self.assertIn("terminalTextSelected", terminal_title_actions[0]["when"])
        self.assertEqual(terminal_title_actions[0]["group"], "navigation@0")

        self.assertIn("function selectionLineRange(selection)", extension)
        self.assertIn("function clipboardLineCount(value)", extension)
        self.assertIn("async function readClipboardAfterCopy(previousText", extension)
        self.assertIn("已将终端选区加入 EgoAgent 对话", extension)
        self.assertIn("type: 'externalContextsAttached', contexts: [terminalContext]", extension)
        self.assertIn("resolveContextPaste(message)", extension)
        self.assertIn("openContextLocation(context)", extension)
        self.assertIn("workbench.action.terminal.copySelection", extension)
        self.assertIn('data-attach-kind="terminal"', extension)
        self.assertIn("attachTerminalContext", chat)

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
        self.assertIn("kind: 'folder'", extension)
        self.assertIn("vscode.workspace.fs.readDirectory(directory)", extension)
        self.assertIn("revealInExplorer", extension)
        self.assertIn("attachResourcesToChat(uri, selectedUris, selectionOnly = false)", extension)
        self.assertIn('data-attach-kind="file"', extension)
        self.assertIn('data-attach-kind="selection"', extension)
        self.assertIn('data-attach-kind="workspace"', extension)
        self.assertIn("requestedKind === 'workspace'", chat)
        self.assertIn("item.kind === 'folder' ? 'folder'", chat)
        self.assertIn("context?.kind === 'folder' ? '文件夹附件'", chat)
        self.assertIn(".inline-attachment", css)
        self.assertIn(".attachment-editor", css)
        self.assertIn("white-space: pre", css)

        launcher = (ROOT / "start-all.py").read_text(encoding="utf-8")
        self.assertIn("const transfer=event.dataTransfer", launcher)
        self.assertIn("DataTransfer.prototype.setData=function(type,value)", launcher)
        self.assertIn("this===capturingTransfer", launcher)
        self.assertIn("queueMicrotask(capture)", launcher)
        self.assertIn("setTimeout(capture,0)", launcher)
        self.assertIn("const live=snapshot(event.dataTransfer)", launcher)
        self.assertIn("insideTarget(event.clientX,event.clientY)", launcher)
        self.assertIn("event.preventDefault()", launcher)
        self.assertIn("event.dataTransfer.dropEffect='copy'", launcher)

    def test_flow_versions_and_editable_directed_edges_are_visible_in_the_ide(self):
        extension = (EXTENSION / "extension-v21.js").read_text(encoding="utf-8")
        chat = (EXTENSION / "media" / "chat.js").read_text(encoding="utf-8")
        app = (ROOT / "harness_editor" / "src" / "App.tsx").read_text(encoding="utf-8")
        edge = (ROOT / "harness_editor" / "src" / "edges" / "ConditionEdge.tsx").read_text(encoding="utf-8")
        inspector = (ROOT / "harness_editor" / "src" / "components" / "RightPanel.tsx").read_text(encoding="utf-8")
        self.assertIn('id="harnessVersionSelect"', extension)
        self.assertIn("harness_version: state.harnessVersion", chat)
        self.assertIn("harnessVersionCreated", chat)
        self.assertIn("MarkerType.ArrowClosed", app)
        self.assertIn("edge.id === selectedEdgeId", app)
        self.assertIn("平滑贝塞尔（推荐）", inspector)
        self.assertIn("reroutes", inspector)
        self.assertIn("curvature", inspector)
        self.assertIn("sourceStub", edge)
        self.assertIn("targetStub", edge)
        self.assertIn("sourceDirection", edge)
        self.assertIn("targetDirection", edge)
        self.assertIn("buildCurves", edge)
        self.assertIn("edge-reroute-socket", edge)
        self.assertIn("insertAt", edge)
        self.assertIn("edge-terminal-chevron", edge)
        self.assertIn("strokeLinecap: 'round'", edge)
        self.assertIn("labelOffset", edge)

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
        self.assertIn("activeBackendChanges.filter(needsReview).map(backendChangeHtml)", chat)
        self.assertIn("function backendChangesForActiveReview()", chat)
        self.assertIn("当前 Session 没有待审查改动", chat)
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
assert.equal(helpers.needsReview({{status:'conflict', hunks:[]}}), false);
"""
        result = subprocess.run(
            ["node", "-e", script], cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_changes_tab_never_mixes_review_transactions_between_sessions(self):
        chat = (EXTENSION / "media" / "chat.js").read_text(encoding="utf-8")
        start = chat.index("  function activeReviewTransactionId")
        end = chat.index("  function postBackendReviewSnapshot", start)
        helper_source = chat[start:end]
        script = f"""
const assert = require('node:assert/strict');
const build = new Function('state', {json.dumps(helper_source)} + '\\nreturn {{ activeReviewTransactionId, backendChangesForActiveReview }};');
const state = {{
  changeTransactionId: 'run-current', running: false, waitingForInput: false,
  backendChanges: [
    {{id:'stale-conflict', transaction_id:'run-old', status:'conflict', hunks:[{{status:'rejected'}}]}},
    {{id:'current', transaction_id:'run-current', status:'pending', hunks:[{{status:'pending'}}]}},
  ],
}};
const helpers = build(state);
assert.equal(helpers.activeReviewTransactionId(), 'run-current');
assert.deepEqual(helpers.backendChangesForActiveReview().map((item) => item.id), ['current']);
state.changeTransactionId = '';
assert.equal(helpers.activeReviewTransactionId(), '');
assert.deepEqual(helpers.backendChangesForActiveReview(), []);
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
        self.assertIn("const scopedChanges = this.activeBackendTransactionId ? this.activeBackendChanges() : []", extension)
        self.assertIn("for (const change of this.activeBackendChanges())", extension)
        self.assertIn("reviewManager.selectBackendTransaction(transactionId)", extension)
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
        self.assertIn("const DEFAULT_CODE_HARNESS = 'code_agent_auto'", chat)
        self.assertIn("const DEFAULT_CODE_IDENTITY = 'adaptive_deepseek_coder'", chat)

    def test_chat_has_no_duplicate_run_tab_and_keeps_compact_stop_control(self):
        extension = (EXTENSION / "extension-v21.js").read_text(encoding="utf-8")
        chat = (EXTENSION / "media" / "chat.js").read_text(encoding="utf-8")
        self.assertNotIn('data-tab="run"', extension)
        self.assertNotIn('id="runTab"', extension)
        self.assertIn('id="stopCurrentRun"', extension)
        self.assertIn("stop.hidden = !state.running", chat)
        self.assertIn("['chat', 'changes', 'context'].includes(name)", chat)

    def test_unified_launcher_supervises_a_crashed_backend(self):
        launcher = (ROOT / "start-all.py").read_text(encoding="utf-8")
        self.assertIn("def _supervise_backend(process_holder, stop_event):", launcher)
        self.assertIn("start_backend_supervisor(backend_process)", launcher)
        self.assertIn("stop_backend_supervisor(backend_supervisor)", launcher)

    def test_default_agent_configuration_is_the_flagship_code_stack(self):
        chat = (EXTENSION / "media" / "chat.js").read_text(encoding="utf-8")
        extension = (EXTENSION / "extension-v21.js").read_text(encoding="utf-8")
        create_dialog = (ROOT / "harness_editor" / "src" / "components" / "SessionCreateDialog.tsx").read_text(encoding="utf-8")
        background_runs = (ROOT / "harness_editor" / "src" / "components" / "BackgroundRuns.tsx").read_text(encoding="utf-8")
        harness = json.loads((ROOT / "harness" / "adaptive_code_agent" / "config.json").read_text(encoding="utf-8"))
        self.assertIn("state.mode = nextConfig.mode", chat)
        self.assertIn("Never silently escalate Chat/Plan into Agent mode", chat)
        self.assertIn("useState('code_agent_auto')", create_dialog)
        self.assertIn("useState('adaptive_deepseek_coder')", create_dialog)
        self.assertIn('harness: "code_agent_auto", identity: "adaptive_deepseek_coder"', background_runs)
        self.assertEqual(harness["slots"]["agent"]["identity"], "deepseek_operator")
        self.assertEqual(harness["slots"]["governor"]["identity"], "deepseek_operator")
        self.assertIn("initialInput: submittedText", chat)
        self.assertIn("Number(error?.status) !== 404", chat)
        self.assertIn("function markConfigurationChange()", chat)
        self.assertGreaterEqual(chat.count("markConfigurationChange();"), 4)
        self.assertIn("下一条消息会在当前 Session 中使用新配置", chat)
        self.assertIn("resume_session: resumeSession", chat)
        self.assertIn("initial_input: String(initialInput || '')", chat)
        self.assertIn("configuration: resolvedConfiguration", chat)
        self.assertIn("function agentConfigSnapshot()", chat)
        self.assertIn("sessionConfigs: saved.sessionConfigs", chat)
        self.assertIn("rememberCurrentAgentConfig();", chat)
        self.assertIn("const savedConfig = state.sessionConfigs[sessionConfigKey(runId)]", chat)
        self.assertIn("同一 Session 可逐轮切换", extension)
        self.assertIn("String(event.result || '').trim().includes(errorText)", chat)
        self.assertIn("state.bindings = {};", chat)
        self.assertIn("if (slots.length === 1) state.bindings[slots[0]] = state.identity", chat)
        self.assertIn("const singleSlot = Object.keys(slots).length === 1", chat)

    def test_builder_and_chat_runs_are_explicitly_isolated_and_sessions_can_be_observed(self):
        app = (ROOT / "harness_editor" / "src" / "App.tsx").read_text(encoding="utf-8")
        client = (ROOT / "harness_editor" / "src" / "api" / "client.ts").read_text(encoding="utf-8")
        chat = (EXTENSION / "media" / "chat.js").read_text(encoding="utf-8")
        extension = (EXTENSION / "extension-v21.js").read_text(encoding="utf-8")
        self.assertIn("surface: 'builder'", client)
        self.assertIn("surface: 'chat'", chat)
        self.assertIn("listExecutionRuns", client)
        self.assertIn("type BuilderMode = 'build' | 'locked' | 'linked'", app)
        self.assertIn("LINKED TO SESSION", app)
        self.assertIn("toggleBuilderLock", app)
        self.assertIn("退出观察模式并编辑这个 Flow？", app)
        self.assertIn("setLeaveLinkedDialogOpen(true)", app)
        self.assertIn("正在运行的 Session 仍使用启动时的 Flow 快照", app)
        self.assertNotIn("window.confirm(`退出与", app)
        self.assertNotIn("Chat 改配置会创建新的 Session", app)
        self.assertIn("<FlowRunViewer rootId={linkedRunId}", app)
        self.assertIn("readFlowObservation", client)
        self.assertIn("useState<BuilderMode>('build')", app)
        self.assertIn("if (!state?.harness) throw new Error('Session 没有记录 Harness')", app)
        self.assertIn("const target = String(runId || '').trim()", app)
        self.assertNotIn("refreshExecutionRuns", app)
        self.assertIn("String(run.harness || '').trim()", chat)
        self.assertIn("session-pill draft active", chat)
        self.assertIn("nodesDraggable={builderMode === 'build'}", app)
        self.assertIn("运行控制在原 Chat Session 中", app)
        self.assertIn("runtimeEventBelongsToRoot", app)
        self.assertIn("incomingRunId !== targetRunId", app)
        self.assertIn("reduceRuntimeRunEvent", app)
        self.assertIn('id="linkSessionWorkbench"', extension)
        self.assertIn("type: 'link-session'", extension)
        self.assertIn("linkRunId: targetRunId", chat)
        self.assertIn("await startExecution(true)", chat)
        self.assertIn("后端已恢复这个 Session", chat)
        self.assertIn("beginSessionRename", chat)
        self.assertIn("data-session-more", chat)
        self.assertIn("重命名、Fork、观察或删除", chat)
        self.assertIn("/api/projects/session/update", chat)
        self.assertIn("/api/execution/dismiss", chat)
        self.assertIn("deleteSession", chat)
        self.assertIn("showBuilderPalette", app)
        self.assertIn("showBuilderInspector", app)
        self.assertIn("toggleBuilderPanel", app)

    def test_native_chat_uses_bounded_offline_reconnect_backoff(self):
        chat = (EXTENSION / "media" / "chat.js").read_text(encoding="utf-8")
        self.assertIn("scheduleWebSocketReconnect", chat)
        self.assertIn("Math.min(30000, 1000 * (2 ** Math.min(state.wsRetryAttempt, 5)))", chat)
        self.assertIn("document.addEventListener('visibilitychange'", chat)
        self.assertIn("if (document.hidden) return;", chat)
        self.assertNotIn("setTimeout(connectWebSocket, 1800)", chat)
        self.assertNotIn("setTimeout(connectWebSocket, 2200)", chat)

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
        self.assertGreaterEqual(engine.count("_clone_agent_for_slot("), 3)
        self.assertIn("cloned.name = str(slot_name)", engine)

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
