import type { Edge, Node } from '@xyflow/react';
import type { BezierKnot, PipelineNode } from './types';

export type AutoLayoutOptions = {
  /** 0 = spacious, 100 = compact. */
  compactness: number;
  /** 0 = prefer short routes, 100 = strongly avoid crossings/overlaps. */
  avoidance: number;
  /** 0 = allow more detours, 100 = prefer fewer control points. */
  simplicity: number;
};

export type LayoutMetrics = {
  nodeOverlaps: number;
  edgeCrossings: number;
  edgeNodeOverlaps: number;
  edgeOverlaps: number;
  controlPoints: number;
};

export type AutoLayoutResult = {
  nodes: Node[];
  edges: Edge[];
  before: LayoutMetrics;
  after: LayoutMetrics;
};

type Point = { x: number; y: number };
type Size = { width: number; height: number };
type Rect = { id: string; left: number; right: number; top: number; bottom: number; layer: number };
type Segment = { a: Point; b: Point; edgeId: string };

export const DEFAULT_AUTO_LAYOUT_OPTIONS: AutoLayoutOptions = {
  compactness: 52,
  avoidance: 82,
  simplicity: 58,
};

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));
const mix = (a: number, b: number, t: number) => a + (b - a) * t;
const finite = (value: unknown, fallback: number) => Number.isFinite(Number(value)) ? Number(value) : fallback;

function nodeSize(node: Node): Size {
  const data = node.data as unknown as PipelineNode;
  const inputCount = Object.keys(data.inputs || {}).length;
  const outputCount = Object.keys(data.outputs || {}).length + Math.max(1, data.edges?.length || 0);
  return {
    width: Math.max(188, finite(node.measured?.width ?? node.width, 188)),
    height: Math.max(76, finite(node.measured?.height ?? node.height, 72 + Math.max(inputCount, outputCount) * 17)),
  };
}

function centerOf(node: Node): Point {
  const size = nodeSize(node);
  return { x: node.position.x + size.width / 2, y: node.position.y + size.height / 2 };
}

function rectFor(node: Node, layer = 0, padding = 0): Rect {
  const size = nodeSize(node);
  return {
    id: node.id,
    left: node.position.x - padding,
    right: node.position.x + size.width + padding,
    top: node.position.y - padding,
    bottom: node.position.y + size.height + padding,
    layer,
  };
}

function tarjan(ids: string[], outgoing: Map<string, string[]>): string[][] {
  let nextIndex = 0;
  const index = new Map<string, number>();
  const low = new Map<string, number>();
  const stack: string[] = [];
  const inStack = new Set<string>();
  const components: string[][] = [];

  const visit = (id: string) => {
    index.set(id, nextIndex);
    low.set(id, nextIndex);
    nextIndex += 1;
    stack.push(id);
    inStack.add(id);
    for (const target of outgoing.get(id) || []) {
      if (!index.has(target)) {
        visit(target);
        low.set(id, Math.min(low.get(id)!, low.get(target)!));
      } else if (inStack.has(target)) low.set(id, Math.min(low.get(id)!, index.get(target)!));
    }
    if (low.get(id) !== index.get(id)) return;
    const component: string[] = [];
    while (stack.length) {
      const member = stack.pop()!;
      inStack.delete(member);
      component.push(member);
      if (member === id) break;
    }
    components.push(component);
  };

  ids.forEach((id) => { if (!index.has(id)) visit(id); });
  return components;
}

function rankNodes(nodes: Node[], edges: Edge[], startId: string): Map<string, number> {
  const ids = nodes.map((node) => node.id);
  const idSet = new Set(ids);
  const outgoing = new Map(ids.map((id) => [id, [] as string[]]));
  edges.forEach((edge) => {
    if (idSet.has(edge.source) && idSet.has(edge.target) && !outgoing.get(edge.source)!.includes(edge.target)) {
      outgoing.get(edge.source)!.push(edge.target);
    }
  });
  const components = tarjan(ids, outgoing);
  const componentOf = new Map<string, number>();
  components.forEach((component, componentIndex) => component.forEach((id) => componentOf.set(id, componentIndex)));
  const componentEdges = new Map(components.map((_component, index) => [index, new Set<number>()]));
  const indegree = new Map(components.map((_component, index) => [index, 0]));
  const startComponent = componentOf.get(startId);
  edges.forEach((edge) => {
    const source = componentOf.get(edge.source);
    const target = componentOf.get(edge.target);
    if (source == null || target == null || source === target || target === startComponent || componentEdges.get(source)!.has(target)) return;
    componentEdges.get(source)!.add(target);
    indegree.set(target, (indegree.get(target) || 0) + 1);
  });
  const stableComponentOrder = new Map(components.map((component, index) => [index, Math.min(...component.map((id) => ids.indexOf(id)))]));
  const ready = [...indegree.entries()].filter(([, value]) => value === 0).map(([id]) => id);
  ready.sort((a, b) => (a === startComponent ? -1 : b === startComponent ? 1 : (stableComponentOrder.get(a)! - stableComponentOrder.get(b)!)));
  const rankByComponent = new Map<number, number>();
  if (startComponent != null) rankByComponent.set(startComponent, 0);
  while (ready.length) {
    const source = ready.shift()!;
    if (!rankByComponent.has(source)) rankByComponent.set(source, 0);
    for (const target of componentEdges.get(source) || []) {
      rankByComponent.set(target, Math.max(rankByComponent.get(target) || 0, (rankByComponent.get(source) || 0) + 1));
      indegree.set(target, (indegree.get(target) || 0) - 1);
      if (indegree.get(target) === 0) ready.push(target);
    }
    ready.sort((a, b) => (stableComponentOrder.get(a)! - stableComponentOrder.get(b)!));
  }
  return new Map(ids.map((id) => [id, rankByComponent.get(componentOf.get(id)!) || 0]));
}

function segmentOrientation(a: Point, b: Point, c: Point): number {
  const value = (b.y - a.y) * (c.x - b.x) - (b.x - a.x) * (c.y - b.y);
  return Math.abs(value) < 0.001 ? 0 : value > 0 ? 1 : 2;
}

function pointOnSegment(a: Point, b: Point, p: Point): boolean {
  return p.x <= Math.max(a.x, b.x) + 0.001 && p.x >= Math.min(a.x, b.x) - 0.001 &&
    p.y <= Math.max(a.y, b.y) + 0.001 && p.y >= Math.min(a.y, b.y) - 0.001;
}

function segmentsCross(first: Segment, second: Segment): boolean {
  const { a, b } = first;
  const { a: c, b: d } = second;
  const o1 = segmentOrientation(a, b, c);
  const o2 = segmentOrientation(a, b, d);
  const o3 = segmentOrientation(c, d, a);
  const o4 = segmentOrientation(c, d, b);
  if (o1 !== o2 && o3 !== o4) return true;
  return (o1 === 0 && pointOnSegment(a, b, c)) || (o2 === 0 && pointOnSegment(a, b, d)) ||
    (o3 === 0 && pointOnSegment(c, d, a)) || (o4 === 0 && pointOnSegment(c, d, b));
}

function collinearOverlap(first: Segment, second: Segment): number {
  const horizontal = Math.abs(first.a.y - first.b.y) < 0.01 && Math.abs(second.a.y - second.b.y) < 0.01 && Math.abs(first.a.y - second.a.y) < 0.01;
  const vertical = Math.abs(first.a.x - first.b.x) < 0.01 && Math.abs(second.a.x - second.b.x) < 0.01 && Math.abs(first.a.x - second.a.x) < 0.01;
  if (!horizontal && !vertical) return 0;
  const f0 = horizontal ? Math.min(first.a.x, first.b.x) : Math.min(first.a.y, first.b.y);
  const f1 = horizontal ? Math.max(first.a.x, first.b.x) : Math.max(first.a.y, first.b.y);
  const s0 = horizontal ? Math.min(second.a.x, second.b.x) : Math.min(second.a.y, second.b.y);
  const s1 = horizontal ? Math.max(second.a.x, second.b.x) : Math.max(second.a.y, second.b.y);
  return Math.max(0, Math.min(f1, s1) - Math.max(f0, s0));
}

function lineHitsRect(a: Point, b: Point, rect: Rect): boolean {
  // Liang-Barsky clipping against the rectangle interior. Boundary-only
  // contact is allowed so routes can follow a clearance corridor.
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  let low = 0;
  let high = 1;
  const tests: Array<[number, number]> = [
    [-dx, a.x - rect.left], [dx, rect.right - a.x],
    [-dy, a.y - rect.top], [dy, rect.bottom - a.y],
  ];
  for (const [p, q] of tests) {
    if (Math.abs(p) < 0.0001) {
      if (q < 0) return false;
      continue;
    }
    const ratio = q / p;
    if (p < 0) low = Math.max(low, ratio);
    else high = Math.min(high, ratio);
    if (low > high) return false;
  }
  if (high - low < 0.001) return false;
  const mid = (low + high) / 2;
  const point = { x: a.x + dx * mid, y: a.y + dy * mid };
  return point.x > rect.left + 0.01 && point.x < rect.right - 0.01 && point.y > rect.top + 0.01 && point.y < rect.bottom - 0.01;
}

function polylinesForEdges(nodes: Node[], edges: Edge[]): Map<string, Point[]> {
  const centers = new Map(nodes.map((node) => [node.id, centerOf(node)]));
  return new Map(edges.map((edge) => {
    const source = centers.get(edge.source) || { x: 0, y: 0 };
    const target = centers.get(edge.target) || source;
    const reroutes = Array.isArray((edge.data as any)?.reroutes) ? (edge.data as any).reroutes : [];
    return [edge.id, [source, ...reroutes.map((point: any) => ({ x: finite(point.x, source.x), y: finite(point.y, source.y) })), target]];
  }));
}

function segmentsFor(edgeId: string, points: Point[]): Segment[] {
  return points.slice(1).map((point, index) => ({ a: points[index], b: point, edgeId }));
}

function metricsFor(nodes: Node[], edges: Edge[], routed?: Map<string, Point[]>): LayoutMetrics {
  const rects = nodes.map((node) => rectFor(node));
  let nodeOverlaps = 0;
  rects.forEach((rect, index) => rects.slice(index + 1).forEach((other) => {
    if (rect.left < other.right && rect.right > other.left && rect.top < other.bottom && rect.bottom > other.top) nodeOverlaps += 1;
  }));
  const polylines = routed || polylinesForEdges(nodes, edges);
  const allSegments = edges.flatMap((edge) => segmentsFor(edge.id, polylines.get(edge.id) || []));
  let edgeCrossings = 0;
  let edgeOverlaps = 0;
  allSegments.forEach((segment, index) => allSegments.slice(index + 1).forEach((other) => {
    if (segment.edgeId === other.edgeId) return;
    const first = edges.find((edge) => edge.id === segment.edgeId);
    const second = edges.find((edge) => edge.id === other.edgeId);
    if (first && second && [first.source, first.target].some((id) => id === second.source || id === second.target)) return;
    const overlap = collinearOverlap(segment, other);
    if (overlap > 1) edgeOverlaps += 1;
    else if (segmentsCross(segment, other)) edgeCrossings += 1;
  }));
  let edgeNodeOverlaps = 0;
  edges.forEach((edge) => {
    const segments = segmentsFor(edge.id, polylines.get(edge.id) || []);
    rects.filter((rect) => rect.id !== edge.source && rect.id !== edge.target).forEach((rect) => {
      if (segments.some((segment) => lineHitsRect(segment.a, segment.b, rect))) edgeNodeOverlaps += 1;
    });
  });
  const controlPoints = edges.reduce((total, edge) => total + (Array.isArray((edge.data as any)?.reroutes) ? (edge.data as any).reroutes.length : 0), 0);
  return { nodeOverlaps, edgeCrossings, edgeNodeOverlaps, edgeOverlaps, controlPoints };
}

function abstractCrossings(layers: Map<number, string[]>, edges: Edge[], ranks: Map<string, number>): number {
  const order = new Map<string, number>();
  layers.forEach((ids) => ids.forEach((id, index) => order.set(id, index)));
  let count = 0;
  edges.forEach((first, index) => edges.slice(index + 1).forEach((second) => {
    if ([first.source, first.target].some((id) => id === second.source || id === second.target)) return;
    const a0 = ranks.get(first.source) || 0;
    const a1 = ranks.get(first.target) || 0;
    const b0 = ranks.get(second.source) || 0;
    const b1 = ranks.get(second.target) || 0;
    if (a0 === a1 || b0 === b1) return;
    const left = Math.max(Math.min(a0, a1), Math.min(b0, b1));
    const right = Math.min(Math.max(a0, a1), Math.max(b0, b1));
    if (left >= right) return;
    const interpolate = (edge: Edge, rank: number) => {
      const sourceRank = ranks.get(edge.source) || 0;
      const targetRank = ranks.get(edge.target) || 0;
      const t = (rank - sourceRank) / Math.max(0.001, targetRank - sourceRank);
      return finite(order.get(edge.source), 0) + (finite(order.get(edge.target), 0) - finite(order.get(edge.source), 0)) * t;
    };
    const leftOrder = interpolate(first, left) - interpolate(second, left);
    const rightOrder = interpolate(first, right) - interpolate(second, right);
    if (leftOrder * rightOrder < 0) count += 1;
  }));
  return count;
}

function orderLayers(nodes: Node[], edges: Edge[], ranks: Map<string, number>, avoidance: number): Map<number, string[]> {
  const stableOrder = new Map(nodes.map((node, index) => [node.id, index]));
  const layers = new Map<number, string[]>();
  nodes.forEach((node) => {
    const rank = ranks.get(node.id) || 0;
    layers.set(rank, [...(layers.get(rank) || []), node.id]);
  });
  const incoming = new Map(nodes.map((node) => [node.id, [] as string[]]));
  const outgoing = new Map(nodes.map((node) => [node.id, [] as string[]]));
  edges.forEach((edge) => {
    incoming.get(edge.target)?.push(edge.source);
    outgoing.get(edge.source)?.push(edge.target);
  });
  const sortedRanks = [...layers.keys()].sort((a, b) => a - b);
  const sweeps = 4 + Math.round(clamp(avoidance, 0, 100) / 12);
  const position = () => new Map([...layers.values()].flatMap((ids) => ids.map((id, index) => [id, index] as const)));
  for (let sweep = 0; sweep < sweeps; sweep += 1) {
    const forward = sweep % 2 === 0;
    const ranksToVisit = forward ? sortedRanks : [...sortedRanks].reverse();
    const currentPosition = position();
    ranksToVisit.forEach((rank) => {
      const layer = layers.get(rank)!;
      const neighbors = forward ? incoming : outgoing;
      layer.sort((left, right) => {
        const barycenter = (id: string) => {
          const values = (neighbors.get(id) || []).filter((neighbor) => (ranks.get(neighbor) || 0) !== rank).map((neighbor) => finite(currentPosition.get(neighbor), stableOrder.get(neighbor) || 0));
          return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : finite(currentPosition.get(id), stableOrder.get(id) || 0);
        };
        return barycenter(left) - barycenter(right) || (stableOrder.get(left)! - stableOrder.get(right)!);
      });
    });
  }
  // Adjacent transposition is inexpensive for typical Flow graphs and catches
  // crossings that barycentric sweeps cannot remove on their own.
  const transposePasses = 1 + Math.round(clamp(avoidance, 0, 100) / 25);
  for (let pass = 0; pass < transposePasses; pass += 1) {
    let improved = false;
    sortedRanks.forEach((rank) => {
      const layer = layers.get(rank)!;
      for (let index = 0; index < layer.length - 1; index += 1) {
        const before = abstractCrossings(layers, edges, ranks);
        [layer[index], layer[index + 1]] = [layer[index + 1], layer[index]];
        const after = abstractCrossings(layers, edges, ranks);
        if (after < before) improved = true;
        else [layer[index], layer[index + 1]] = [layer[index + 1], layer[index]];
      }
    });
    if (!improved) break;
  }
  return layers;
}

function positionNodes(nodes: Node[], layers: Map<number, string[]>, options: AutoLayoutOptions): Node[] {
  const compactness = clamp(options.compactness, 0, 100) / 100;
  const avoidance = clamp(options.avoidance, 0, 100) / 100;
  const horizontalGap = mix(340, 130, compactness) + avoidance * 45;
  const verticalGap = mix(150, 34, compactness) + avoidance * 22;
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const sortedRanks = [...layers.keys()].sort((a, b) => a - b);
  const layerWidths = new Map(sortedRanks.map((rank) => [rank, Math.max(...layers.get(rank)!.map((id) => nodeSize(byId.get(id)!).width))]));
  const xByRank = new Map<number, number>();
  let x = 80;
  sortedRanks.forEach((rank) => {
    xByRank.set(rank, x);
    x += layerWidths.get(rank)! + horizontalGap;
  });
  const layerHeights = new Map(sortedRanks.map((rank) => [rank, layers.get(rank)!.reduce((sum, id, index) => sum + nodeSize(byId.get(id)!).height + (index ? verticalGap : 0), 0)]));
  const maximumHeight = Math.max(...layerHeights.values(), 0);
  const positioned = new Map<string, Point>();
  sortedRanks.forEach((rank) => {
    let y = 72 + (maximumHeight - layerHeights.get(rank)!) / 2;
    layers.get(rank)!.forEach((id) => {
      positioned.set(id, { x: xByRank.get(rank)!, y });
      y += nodeSize(byId.get(id)!).height + verticalGap;
    });
  });
  return nodes.map((node) => ({ ...node, position: positioned.get(node.id) || node.position }));
}

function simplifyPolyline(points: Point[]): Point[] {
  const unique = points.filter((point, index) => index === 0 || Math.hypot(point.x - points[index - 1].x, point.y - points[index - 1].y) > 1);
  if (unique.length <= 2) return unique;
  const result = [unique[0]];
  for (let index = 1; index < unique.length - 1; index += 1) {
    const previous = result[result.length - 1];
    const current = unique[index];
    const next = unique[index + 1];
    const cross = (current.x - previous.x) * (next.y - current.y) - (current.y - previous.y) * (next.x - current.x);
    if (Math.abs(cross) > 0.5) result.push(current);
  }
  result.push(unique[unique.length - 1]);
  return result;
}

function routeCost(points: Point[], edgeId: string, obstacles: Rect[], routed: Segment[], options: AutoLayoutOptions): number {
  const segments = segmentsFor(edgeId, points);
  const length = segments.reduce((total, segment) => total + Math.hypot(segment.b.x - segment.a.x, segment.b.y - segment.a.y), 0);
  const bends = Math.max(0, points.length - 2);
  const nodeHits = obstacles.reduce((total, rect) => total + (segments.some((segment) => lineHitsRect(segment.a, segment.b, rect)) ? 1 : 0), 0);
  let crossings = 0;
  let overlap = 0;
  segments.forEach((segment) => routed.forEach((other) => {
    const amount = collinearOverlap(segment, other);
    if (amount > 1) overlap += amount;
    else if (segmentsCross(segment, other)) crossings += 1;
  }));
  const avoidance = clamp(options.avoidance, 0, 100) / 100;
  const simplicity = clamp(options.simplicity, 0, 100) / 100;
  return length + bends * mix(22, 240, simplicity) + nodeHits * (150_000 + avoidance * 350_000) +
    crossings * mix(35, 1200, avoidance) + overlap * mix(0.7, 16, avoidance);
}

function horizontalLanes(rects: Rect[], left: number, right: number, clearance: number): number[] {
  const relevant = rects.filter((rect) => rect.right >= left && rect.left <= right).sort((a, b) => a.top - b.top);
  if (!relevant.length) return [0];
  const top = Math.min(...relevant.map((rect) => rect.top)) - clearance * 1.7;
  const bottom = Math.max(...relevant.map((rect) => rect.bottom)) + clearance * 1.7;
  const intervals = relevant.map((rect) => [rect.top, rect.bottom] as [number, number]).sort((a, b) => a[0] - b[0]);
  const merged: Array<[number, number]> = [];
  intervals.forEach(([start, end]) => {
    const latest = merged[merged.length - 1];
    if (!latest || start > latest[1]) merged.push([start, end]);
    else latest[1] = Math.max(latest[1], end);
  });
  const internal = merged.slice(1).flatMap((interval, index) => {
    const previous = merged[index];
    return interval[0] - previous[1] > clearance * 1.35 ? [(interval[0] + previous[1]) / 2] : [];
  });
  return [top, bottom, ...internal];
}

function buildRouteCandidates(
  edge: Edge,
  source: Rect,
  target: Rect,
  rects: Rect[],
  layerBounds: Map<number, { left: number; right: number }>,
  options: AutoLayoutOptions,
): Point[][] {
  const sourcePoint = { x: source.right, y: (source.top + source.bottom) / 2 };
  const targetPoint = { x: target.left, y: (target.top + target.bottom) / 2 };
  const clearance = mix(24, 54, clamp(options.avoidance, 0, 100) / 100);
  const candidates: Point[][] = [[sourcePoint, targetPoint]];
  const forward = target.layer > source.layer;
  const sourceLead = (layerBounds.get(source.layer)?.right || source.right) + clearance;
  const targetLead = (layerBounds.get(target.layer)?.left || target.left) - clearance;
  if (forward && sourceLead < targetLead) {
    const middle = (sourceLead + targetLead) / 2;
    const separation = mix(8, 34, clamp(options.avoidance, 0, 100) / 100);
    [-1, 0, 1].forEach((offset) => {
      const corridor = clamp(middle + offset * separation, sourceLead, targetLead);
      candidates.push([sourcePoint, { x: corridor, y: sourcePoint.y }, { x: corridor, y: targetPoint.y }, targetPoint]);
    });
  }
  const left = Math.min(sourcePoint.x, targetPoint.x);
  const right = Math.max(sourcePoint.x, targetPoint.x);
  const lanes = horizontalLanes(rects, left, right, clearance);
  lanes.forEach((laneY, laneIndex) => {
    const channelJitter = (laneIndex % 3 - 1) * mix(4, 18, clamp(options.avoidance, 0, 100) / 100);
    // This also handles same-layer and self-loop routes. Leave through the
    // corridor immediately after the source layer, travel above/below the
    // occupied rows, and enter through the corridor before the target layer.
    // It avoids the tempting but unsafe shortcut of crossing later layers on
    // the way to the global graph boundary.
    candidates.push([sourcePoint, { x: sourceLead, y: sourcePoint.y }, { x: sourceLead, y: laneY + channelJitter }, { x: targetLead, y: laneY + channelJitter }, { x: targetLead, y: targetPoint.y }, targetPoint]);
  });
  return candidates.map(simplifyPolyline);
}

function knotsFor(points: Point[], edgeId: string, simplicity: number): { reroutes: BezierKnot[]; sourceHandle?: number; targetHandle?: number } {
  if (points.length <= 2) return { reroutes: [] };
  const radiusFactor = mix(0.34, 0.18, clamp(simplicity, 0, 100) / 100);
  const reroutes = points.slice(1, -1).map((point, index) => {
    const previous = points[index];
    const next = points[index + 2];
    const incoming = Math.hypot(point.x - previous.x, point.y - previous.y);
    const outgoing = Math.hypot(next.x - point.x, next.y - point.y);
    return {
      id: `auto-${edgeId.replace(/[^a-zA-Z0-9_-]/g, '_')}-${index}`,
      x: point.x,
      y: point.y,
      angle: Math.atan2(next.y - previous.y, next.x - previous.x),
      in_length: clamp(incoming * radiusFactor, 10, 90),
      out_length: clamp(outgoing * radiusFactor, 10, 90),
    };
  });
  return {
    reroutes,
    sourceHandle: clamp(Math.hypot(points[1].x - points[0].x, points[1].y - points[0].y) * radiusFactor, 12, 120),
    targetHandle: clamp(Math.hypot(
      points[points.length - 1].x - points[points.length - 2].x,
      points[points.length - 1].y - points[points.length - 2].y,
    ) * radiusFactor, 12, 120),
  };
}

function routeEdges(nodes: Node[], edges: Edge[], ranks: Map<string, number>, options: AutoLayoutOptions): { edges: Edge[]; polylines: Map<string, Point[]> } {
  const padding = mix(15, 30, clamp(options.avoidance, 0, 100) / 100);
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const rects = nodes.map((node) => rectFor(node, ranks.get(node.id) || 0, padding));
  const rectById = new Map(rects.map((rect) => [rect.id, rect]));
  const layerBounds = new Map<number, { left: number; right: number }>();
  rects.forEach((rect) => {
    const bounds = layerBounds.get(rect.layer);
    layerBounds.set(rect.layer, bounds ? { left: Math.min(bounds.left, rect.left), right: Math.max(bounds.right, rect.right) } : { left: rect.left, right: rect.right });
  });
  const routedSegments: Segment[] = [];
  const polylines = new Map<string, Point[]>();
  const edgeOrder = [...edges].sort((left, right) => {
    const span = (edge: Edge) => Math.abs((ranks.get(edge.target) || 0) - (ranks.get(edge.source) || 0));
    return span(right) - span(left) || left.id.localeCompare(right.id);
  });
  const edgeUpdates = new Map<string, Record<string, unknown>>();
  edgeOrder.forEach((edge) => {
    const source = rectById.get(edge.source);
    const target = rectById.get(edge.target);
    if (!source || !target || !nodeById.has(edge.source) || !nodeById.has(edge.target)) return;
    const obstacles = rects.filter((rect) => rect.id !== edge.source && rect.id !== edge.target);
    const candidates = buildRouteCandidates(edge, source, target, rects, layerBounds, options);
    const collisionFree = candidates.filter((candidate) => !obstacles.some((rect) => segmentsFor(edge.id, candidate).some((segment) => lineHitsRect(segment.a, segment.b, rect))));
    const pool = collisionFree.length ? collisionFree : candidates;
    const route = pool.reduce((best, candidate) => routeCost(candidate, edge.id, obstacles, routedSegments, options) < routeCost(best, edge.id, obstacles, routedSegments, options) ? candidate : best, pool[0]);
    polylines.set(edge.id, route);
    routedSegments.push(...segmentsFor(edge.id, route));
    const knots = knotsFor(route, edge.id, options.simplicity);
    edgeUpdates.set(edge.id, {
      route: 'bezier',
      reroutes: knots.reroutes,
      sourceHandle: knots.sourceHandle,
      targetHandle: knots.targetHandle,
      waypoints: undefined,
      channelOffset: 0,
      curvature: 0.72,
      autoRouted: true,
    });
  });
  return {
    edges: edges.map((edge) => ({ ...edge, data: { ...edge.data, ...(edgeUpdates.get(edge.id) || {}) } })),
    polylines,
  };
}

export function autoLayoutFlow(nodes: Node[], edges: Edge[], startId: string, rawOptions: AutoLayoutOptions): AutoLayoutResult {
  const options = {
    compactness: clamp(rawOptions.compactness, 0, 100),
    avoidance: clamp(rawOptions.avoidance, 0, 100),
    simplicity: clamp(rawOptions.simplicity, 0, 100),
  };
  const before = metricsFor(nodes, edges);
  if (!nodes.length) return { nodes, edges, before, after: before };
  const ranks = rankNodes(nodes, edges, startId);
  const layers = orderLayers(nodes, edges, ranks, options.avoidance);
  const positioned = positionNodes(nodes, layers, options);
  const routed = routeEdges(positioned, edges, ranks, options);
  return { nodes: positioned, edges: routed.edges, before, after: metricsFor(positioned, routed.edges, routed.polylines) };
}
