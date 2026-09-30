import type { HarnessConfig } from './types';
import { WORKSPACE, canonicalWorkspace } from './api/runtime';
import { postToIde, type IdeContextItem } from './ideBridge';

export type WorkbenchRoute = 'home' | 'observe' | 'harness' | 'ir' | 'tasks' | 'research' | 'background' | 'library' | 'packages' | 'changes' | 'checkpoints' | 'identity' | 'environment' | 'sessions' | 'settings' | 'evolution' | 'coc' | 'flow' | 'more';

export interface BuilderDraft {
  config: HarnessConfig;
  positions?: Record<string, { x: number; y: number }>;
  selectedNodeId?: string | null;
  selectedEdgeId?: string | null;
  showOutput?: boolean;
  outputView?: 'conversation' | 'timeline';
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
  evaluation?: EvaluationSelection;
  evolution?: EvolutionSelection;
  handoff?: { items: IdeContextItem[]; updatedAt: number };
  updatedAt: number;
}

const STORAGE_PREFIX = 'egoagent.workbench.v1:';

function storageKey(): string {
  return `${STORAGE_PREFIX}${encodeURIComponent(canonicalWorkspace(WORKSPACE) || 'standalone')}`;
}

export function loadWorkbenchSession(): WorkbenchSession {
  const fallback: WorkbenchSession = {
    version: 1,
    workspace: WORKSPACE,
    updatedAt: 0,
  };
  try {
    const raw = window.localStorage.getItem(storageKey());
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<WorkbenchSession>;
    if (parsed.version !== 1) return fallback;
    return { ...fallback, ...parsed, workspace: WORKSPACE };
  } catch {
    return fallback;
  }
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
  return next;
}

export function publishWorkbenchEvent(type: string, detail: Record<string, unknown>): void {
  window.dispatchEvent(new CustomEvent('egoagent:workbench', { detail: { type, ...detail } }));
  postToIde(type, detail);
}
