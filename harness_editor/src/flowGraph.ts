import { MarkerType, type Node, type Edge } from '@xyflow/react';
import type { HarnessConfig, PipelineNode } from './types';
import { EVENT_PREFIX, FLOW_INPUT_HANDLE, INPUT_PREFIX, OUTPUT_PREFIX } from './graphSockets';

export function layoutFlowNodes(nodes: Node[], edges: Edge[], startId = ''): Node[] {
  const stableOrder = new Map(nodes.map((node, index) => [node.id, index]));
  const ids = new Set(nodes.map((node) => node.id));
  const outgoing = new Map<string, string[]>();
  const incoming = new Map<string, string[]>();
  nodes.forEach((node) => { outgoing.set(node.id, []); incoming.set(node.id, []); });
  edges.forEach((edge) => {
    if (!ids.has(edge.source) || !ids.has(edge.target)) return;
    outgoing.get(edge.source)?.push(edge.target);
    incoming.get(edge.target)?.push(edge.source);
  });

  const ranks = new Map<string, number>();
  const queue: string[] = [];
  const roots = [
    ...(ids.has(startId) ? [startId] : []),
    ...nodes.filter((node) => node.id !== startId && !(incoming.get(node.id)?.length)).map((node) => node.id),
  ];
  const visitFrom = (seed: string, seedRank = 0) => {
    if (!ranks.has(seed)) ranks.set(seed, seedRank);
    queue.push(seed);
    while (queue.length) {
      const source = queue.shift()!;
      const nextRank = (ranks.get(source) || 0) + 1;
      for (const target of outgoing.get(source) || []) {
        // Assign once: back-edges in cyclic flows remain back-edges instead of
        // pushing the same component endlessly to the right.
        if (ranks.has(target)) continue;
        ranks.set(target, nextRank);
        queue.push(target);
      }
    }
  };
  roots.forEach((root) => visitFrom(root, 0));
  nodes.forEach((node) => { if (!ranks.has(node.id)) visitFrom(node.id, 0); });

  const layers = new Map<number, string[]>();
  nodes.forEach((node) => {
    const rank = ranks.get(node.id) || 0;
    const layer = layers.get(rank) || [];
    layer.push(node.id);
    layers.set(rank, layer);
  });
  const rowById = new Map<string, number>();
  [...layers.keys()].sort((a, b) => a - b).forEach((rank) => {
    const layer = layers.get(rank)!;
    layer.sort((left, right) => {
      const parentRow = (id: string) => {
        const rows = (incoming.get(id) || []).map((parent) => rowById.get(parent)).filter((value): value is number => value !== undefined);
        return rows.length ? rows.reduce((sum, value) => sum + value, 0) / rows.length : (stableOrder.get(id) || 0);
      };
      return parentRow(left) - parentRow(right) || (stableOrder.get(left) || 0) - (stableOrder.get(right) || 0);
    });
    layer.forEach((id, row) => rowById.set(id, row));
  });
  return nodes.map((node) => ({
    ...node,
    position: {
      x: 80 + (ranks.get(node.id) || 0) * 300,
      y: 78 + (rowById.get(node.id) || 0) * 250,
    },
  }));
}

export function configToFlow(config: HarnessConfig): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  const nodeEntries = Object.entries(config.pipeline.nodes);

  nodeEntries.forEach(([id, pn]) => {
    const savedPosition = pn.editor_position;
    nodes.push({
      id,
      type: 'pipelineNode',
      position: savedPosition && Number.isFinite(Number(savedPosition.x)) && Number.isFinite(Number(savedPosition.y))
        ? { x: Number(savedPosition.x), y: Number(savedPosition.y) }
        : { x: 0, y: 0 },
      data: { ...pn, id },
    });
  });

  nodeEntries.forEach(([id, pn]) => {
    (pn.edges || []).forEach((e, edgeIndex) => {
      if (!e.to) return;
      const savedReroutes = (Array.isArray(e.reroutes) ? e.reroutes : Array.isArray(e.waypoints) ? e.waypoints : [])
        .map((point: any, index: number) => ({
          id: String(point?.id || `legacy-${edgeIndex}-${index}`),
          x: Number(point?.x),
          y: Number(point?.y),
          ...(Number.isFinite(Number(point?.angle)) ? { angle: Number(point.angle) } : {}),
          ...(Number.isFinite(Number(point?.in_length)) ? { in_length: Number(point.in_length) } : {}),
          ...(Number.isFinite(Number(point?.out_length)) ? { out_length: Number(point.out_length) } : {}),
        }))
        .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
      const savedRoute = e.route === 'straight' ? 'straight' : 'bezier';
      const sourcePort = String(e.source_port || e.condition || 'default');
      const targetPort = String(e.target_port || FLOW_INPUT_HANDLE);
      edges.push({
        id: `${id}->${e.to}#${edgeIndex}`,
        source: id,
        target: e.to,
        sourceHandle: `${EVENT_PREFIX}${sourcePort}`,
        targetHandle: targetPort === FLOW_INPUT_HANDLE ? FLOW_INPUT_HANDLE : `${INPUT_PREFIX}${targetPort}`,
        type: 'conditionEdge',
        markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
        data: {
          condition: e.condition,
          kind: 'control',
          sourcePort,
          targetPort,
          route: savedRoute,
          reroutes: savedReroutes,
          sourceHandle: Number.isFinite(Number(e.source_handle)) ? Number(e.source_handle) : undefined,
          targetHandle: Number.isFinite(Number(e.target_handle)) ? Number(e.target_handle) : undefined,
          channelOffset: 0,
          curvature: Number.isFinite(Number(e.curvature)) ? Number(e.curvature) : 0.72,
          labelOffset: e.label_offset || 0,
          editable: true,
        },
      });
    });
  });

  const savedDataLinks = new Map((config.pipeline.data_links || []).map((link) => [
    `${link.source}:${link.source_port}->${link.target}:${link.target_port}`,
    link,
  ]));
  const seen = new Set<string>();
  nodeEntries.forEach(([targetId, node]) => {
    Object.entries(node.inputs || {}).forEach(([targetPort, value]) => {
      const match = typeof value === 'string' ? value.match(/^\$node\.([^.]+)\.(.+)$/) : null;
      if (!match || !config.pipeline.nodes[match[1]]) return;
      const [, sourceId, sourcePort] = match;
      const key = `${sourceId}:${sourcePort}->${targetId}:${targetPort}`;
      const saved = savedDataLinks.get(key);
      edges.push({
        id: saved?.id || `data:${key}`,
        source: sourceId,
        target: targetId,
        sourceHandle: `${OUTPUT_PREFIX}${sourcePort}`,
        targetHandle: `${INPUT_PREFIX}${targetPort}`,
        type: 'conditionEdge',
        markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
        data: {
          kind: 'data', sourcePort, targetPort, condition: 'data', route: 'bezier',
          reroutes: saved?.reroutes || [],
          sourceHandle: Number.isFinite(Number(saved?.source_handle)) ? Number(saved?.source_handle) : undefined,
          targetHandle: Number.isFinite(Number(saved?.target_handle)) ? Number(saved?.target_handle) : undefined,
          curvature: Number(saved?.curvature ?? 0.72),
          labelOffset: Number(saved?.label_offset || 0), editable: true,
        },
      });
      seen.add(key);
    });
  });
  (config.pipeline.data_links || []).forEach((link, index) => {
    const key = `${link.source}:${link.source_port}->${link.target}:${link.target_port}`;
    if (seen.has(key) || !config.pipeline.nodes[link.source] || !config.pipeline.nodes[link.target]) return;
    edges.push({
      id: link.id || `data:${key}#${index}`,
      source: link.source,
      target: link.target,
      sourceHandle: `${OUTPUT_PREFIX}${link.source_port}`,
      targetHandle: `${INPUT_PREFIX}${link.target_port}`,
      type: 'conditionEdge',
      markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
      data: {
        kind: 'data', sourcePort: link.source_port, targetPort: link.target_port,
        condition: 'data', route: 'bezier', reroutes: link.reroutes || [],
        sourceHandle: Number.isFinite(Number(link.source_handle)) ? Number(link.source_handle) : undefined,
        targetHandle: Number.isFinite(Number(link.target_handle)) ? Number(link.target_handle) : undefined,
        curvature: Number(link.curvature ?? 0.72), labelOffset: Number(link.label_offset || 0), editable: true,
      },
    });
  });

  const everyPositionSaved = nodes.length > 0 && nodes.every((node) => {
    const position = (node.data as unknown as PipelineNode).editor_position;
    return position && Number.isFinite(Number(position.x)) && Number.isFinite(Number(position.y));
  });
  return { nodes: everyPositionSaved ? nodes : layoutFlowNodes(nodes, edges, config.pipeline.start), edges };
}
