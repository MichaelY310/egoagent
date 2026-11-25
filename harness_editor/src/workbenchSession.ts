import type { HarnessConfig } from './types';
import { WORKSPACE, canonicalWorkspace } from './api/runtime';
import { postToIde, readIdeWorkbenchSession, writeIdeWorkbenchSession, type IdeContextItem } from './ideBridge';

export type WorkbenchRoute = 'home' | 'observe' | 'harness' | 'ir' | 'tasks' | 'research' | 'background' | 'library' | 'tools' | 'packages' | 'changes' | 'checkpoints' | 'identity' | 'environment' | 'sessions' | 'settings' | 'evolution' | 'coc' | 'flow' | 'more';

export interface BuilderDraft {
  config: HarnessConfig;
  positions?: Record<string, { x: number; y: number }>;
  selectedNodeId?: string | null;
  selectedEdgeId?: string | null;
  showOutput?: boolean;
  outputView?: 'conversation' | 'timeline';
  harnessVersion?: string;
  viewport?: { x: number; y: number; zoom: number };
  showPalette?: boolean;
  showInspector?: boolean;
  panelLayoutVersion?: 1;
  showMinimap?: boolean;
  showLiveArchitecture?: boolean;
  locked?: boolean;
}

/** Migrate the old IDE-only collapsed defaults once, then remember user choices. */
export function builderPanelVisibility(draft?: BuilderDraft): { palette: boolean; inspector: boolean } {
  if (draft?.panelLayoutVersion !== 1) return { palette: true, inspector: true };
  return { palette: draft.showPalette ?? true, inspector: draft.showInspector ?? true };
}

export interface EvaluationSelection {
  taskId?: string;
  runner?: 'ego_flow' | 'codex_cli';
  harness?: string;
  harnessVersion?: string;
  identity?: string;
  environments?: string[];
  slotBindings?: Record<string, string>;
  runId?: string;
}

export interface EvolutionSelection {
  harness?: string;
  identity?: string;
  iterations?: number;
  mode?: 'v2_structural' | 'harness' | 'engine';
  taskId?: string | null;
  status?: string;
  observations?: string;
  report?: unknown;
}

export interface WorkbenchSession {
  version: 1;
  workspace: string;
  route?: WorkbenchRoute;
  builder?: BuilderDraft;
  observation?: { linkedRunId?: string; replayRunId?: string; albumRunId?: string };
  evaluation?: EvaluationSelection;
  evolution?: EvolutionSelection;
  handoff?: { items: IdeContextItem[]; updatedAt: number };
  updatedAt: number;
}

const STORAGE_PREFIX = 'egoagent.workbench.v1:';

function validSession(value: unknown): value is WorkbenchSession {
  if (!value || typeof value !== 'object') return false;
  const session = value as Partial<WorkbenchSession>;
  return session.version === 1 && canonicalWorkspace(session.workspace) === canonicalWorkspace(WORKSPACE);
}

export function hasRestoredIdeSession(): boolean {
  return validSession(readIdeWorkbenchSession());
}

function storageKey(): string {
  return `${STORAGE_PREFIX}${encodeURIComponent(canonicalWorkspace(WORKSPACE) || 'standalone')}`;
}

export function loadWorkbenchSession(): WorkbenchSession {
  const fallback: WorkbenchSession = {
    version: 1,
    workspace: WORKSPACE,
    updatedAt: 0,
  };
  let local: unknown;
  try { local = JSON.parse(window.localStorage.getItem(storageKey()) || 'null'); } catch { /* blocked/quota */ }
  const candidates = [readIdeWorkbenchSession(), window.__EGOAGENT_WORKBENCH__?.workbenchSession, local]
    .filter(validSession).sort((a, b) => (Number(b.updatedAt) || 0) - (Number(a.updatedAt) || 0));
  return { ...fallback, ...candidates[0], workspace: WORKSPACE };
}

export function updateWorkbenchSession(patch: Partial<Omit<WorkbenchSession, 'version' | 'workspace' | 'updatedAt'>>): WorkbenchSession {
  const current = loadWorkbenchSession();
  const next: WorkbenchSession = {
    ...current,
    ...patch,
    builder: patch.builder ? { ...current.builder, ...patch.builder } as BuilderDraft : current.builder,
    evaluation: patch.evaluation ? { ...current.evaluation, ...patch.evaluation } : current.evaluation,
    evolution: patch.evolution ? { ...current.evolution, ...patch.evolution } : current.evolution,
    version: 1,
    workspace: WORKSPACE,
    updatedAt: Date.now(),
  };
  try {
    window.localStorage.setItem(storageKey(), JSON.stringify(next));
  } catch {
    // Persistence is optional; a storage quota failure must never block a run.
  }
  writeIdeWorkbenchSession(next);
  return next;
}

export function publishWorkbenchEvent(type: string, detail: Record<string, unknown>): void {
  window.dispatchEvent(new CustomEvent('egoagent:workbench', { detail: { type, ...detail } }));
  postToIde(type, detail);
}
