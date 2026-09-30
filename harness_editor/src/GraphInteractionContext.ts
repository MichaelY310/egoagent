import { createContext } from 'react';

export type GraphInteractionApi = {
  selectEdge?: (edgeId: string, additive?: boolean) => void;
};

/**
 * UI-only graph actions shared with custom XYFlow renderers.
 *
 * Keeping these callbacks in React context avoids serialising functions into
 * the persisted Flow model or its undo snapshots.
 */
export const GraphInteractionContext = createContext<GraphInteractionApi>({});
