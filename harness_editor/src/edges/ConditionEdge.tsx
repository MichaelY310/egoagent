import {
  BaseEdge,
  EdgeLabelRenderer,
  Position,
  getStraightPath,
  useReactFlow,
  useViewport,
  type Edge,
  type EdgeProps,
} from '@xyflow/react';
import { useContext, useEffect, useRef, useState } from 'react';
import { GraphInteractionContext } from '../GraphInteractionContext';

type Point = { x: number; y: number };
type Reroute = Point & {
  id: string;
  /** Tangent direction in radians, pointing toward the outgoing handle. */
  angle?: number;
  in_length?: number;
  out_length?: number;
};
type Cubic = { a: Point; b: Point; c1: Point; c2: Point };
type CurveHit = { segmentIndex: number; t: number; point: Point; tangent: Point; distance: number };

const CONDITION_LABELS: Record<string, string> = {
  input: '用户输入',
  has_tool_calls: '有工具调用',
  no_tool_calls: '无工具调用',
  has_text: '有文本',
};

const EPSILON = 0.0001;

function direction(position: Position | undefined, target = false): Point {
  if (target) {
    if (position === Position.Right) return { x: -1, y: 0 };
    if (position === Position.Top) return { x: 0, y: 1 };
    if (position === Position.Bottom) return { x: 0, y: -1 };
    return { x: 1, y: 0 };
  }
  if (position === Position.Left) return { x: -1, y: 0 };
  if (position === Position.Top) return { x: 0, y: -1 };
  if (position === Position.Bottom) return { x: 0, y: 1 };
  return { x: 1, y: 0 };
}

function add(point: Point, tangent: Point, amount: number): Point {
  return { x: point.x + tangent.x * amount, y: point.y + tangent.y * amount };
}

function subtract(a: Point, b: Point): Point {
  return { x: a.x - b.x, y: a.y - b.y };
}

function lerp(a: Point, b: Point, t: number): Point {
  return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
}

function magnitude(point: Point): number {
  return Math.hypot(point.x, point.y);
}

function distance(a: Point, b: Point): number {
  return magnitude(subtract(a, b));
}

function unitFromAngle(angle: number): Point {
  return { x: Math.cos(angle), y: Math.sin(angle) };
}

function angleOf(point: Point, fallback = 0): number {
  return magnitude(point) < EPSILON ? fallback : Math.atan2(point.y, point.x);
}

function finiteNumber(value: unknown, fallback: number): number {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function validReroutes(value: unknown): Reroute[] {
  if (!Array.isArray(value)) return [];
  return value.map((item, index) => ({
    id: String(item?.id || `reroute-${index}`),
    x: Number(item?.x),
    y: Number(item?.y),
    ...(Number.isFinite(Number(item?.angle)) ? { angle: Number(item.angle) } : {}),
    ...(Number.isFinite(Number(item?.in_length)) ? { in_length: Math.max(1, Number(item.in_length)) } : {}),
    ...(Number.isFinite(Number(item?.out_length)) ? { out_length: Math.max(1, Number(item.out_length)) } : {}),
  })).filter((item) => Number.isFinite(item.x) && Number.isFinite(item.y));
}

function blenderHandleLength(a: Point, b: Point, curvature: number): number {
  const dx = b.x - a.x;
  const dy = Math.abs(b.y - a.y);
  const reach = Math.abs(dx) * 0.5 + (dx < 0 ? dy * 0.5 + 34 : 0);
  return Math.max(24, Math.min(220, reach || dy * 0.35)) * curvature;
}

function normaliseKnots(raw: Reroute[], source: Point, target: Point): Reroute[] {
  return raw.map((item, index) => {
    const previous = index === 0 ? source : raw[index - 1];
    const next = index === raw.length - 1 ? target : raw[index + 1];
    const angle = finiteNumber(item.angle, angleOf(subtract(next, previous)));
    return {
      ...item,
      angle,
      in_length: Math.max(1, finiteNumber(item.in_length, clamp(distance(item, previous) * 0.34, 12, 110))),
      out_length: Math.max(1, finiteNumber(item.out_length, clamp(distance(item, next) * 0.34, 12, 110))),
    };
  });
}

function buildCurves(
  source: Point,
  target: Point,
  sourceDirection: Point,
  targetDirection: Point,
  knots: Reroute[],
  curvature: number,
  savedSourceHandle: unknown,
  savedTargetHandle: unknown,
): { curves: Cubic[]; sourceHandle: number; targetHandle: number } {
  const anchors: Point[] = [source, ...knots, target];
  const sourceDefault = blenderHandleLength(anchors[0], anchors[1], curvature);
  const targetDefault = blenderHandleLength(anchors[anchors.length - 2], anchors[anchors.length - 1], curvature);
  const sourceHandle = Math.max(1, finiteNumber(savedSourceHandle, sourceDefault));
  const targetHandle = Math.max(1, finiteNumber(savedTargetHandle, targetDefault));
  const curves = anchors.slice(0, -1).map((a, index) => {
    const b = anchors[index + 1];
    const startHandle = index === 0
      ? add(a, sourceDirection, sourceHandle)
      : add(a, unitFromAngle(finiteNumber(knots[index - 1]?.angle, 0)), finiteNumber(knots[index - 1]?.out_length, 24));
    const endHandle = index === anchors.length - 2
      ? add(b, targetDirection, -targetHandle)
      : add(b, unitFromAngle(finiteNumber(knots[index]?.angle, 0)), -finiteNumber(knots[index]?.in_length, 24));
    return { a, b, c1: startHandle, c2: endHandle };
  });
  return { curves, sourceHandle, targetHandle };
}

function cubicPoint(curve: Cubic, t: number): Point {
  const u = 1 - t;
  return {
    x: u ** 3 * curve.a.x + 3 * u ** 2 * t * curve.c1.x + 3 * u * t ** 2 * curve.c2.x + t ** 3 * curve.b.x,
    y: u ** 3 * curve.a.y + 3 * u ** 2 * t * curve.c1.y + 3 * u * t ** 2 * curve.c2.y + t ** 3 * curve.b.y,
  };
}

function cubicTangent(curve: Cubic, t: number): Point {
  const u = 1 - t;
  return {
    x: 3 * u ** 2 * (curve.c1.x - curve.a.x) + 6 * u * t * (curve.c2.x - curve.c1.x) + 3 * t ** 2 * (curve.b.x - curve.c2.x),
    y: 3 * u ** 2 * (curve.c1.y - curve.a.y) + 6 * u * t * (curve.c2.y - curve.c1.y) + 3 * t ** 2 * (curve.b.y - curve.c2.y),
  };
}

function splitCubic(curve: Cubic, t: number): { point: Point; left: Cubic; right: Cubic } {
  const p01 = lerp(curve.a, curve.c1, t);
  const p12 = lerp(curve.c1, curve.c2, t);
  const p23 = lerp(curve.c2, curve.b, t);
  const p012 = lerp(p01, p12, t);
  const p123 = lerp(p12, p23, t);
  const point = lerp(p012, p123, t);
  return {
    point,
    left: { a: curve.a, c1: p01, c2: p012, b: point },
    right: { a: point, c1: p123, c2: p23, b: curve.b },
  };
}

function closestPointOnCurves(curves: Cubic[], desired: Point): CurveHit {
  let best: CurveHit = {
    segmentIndex: 0,
    t: 0.5,
    point: curves[0] ? cubicPoint(curves[0], 0.5) : desired,
    tangent: curves[0] ? cubicTangent(curves[0], 0.5) : { x: 1, y: 0 },
    distance: Number.POSITIVE_INFINITY,
  };
  curves.forEach((curve, segmentIndex) => {
    let bestT = 0;
    let localDistance = Number.POSITIVE_INFINITY;
    for (let sample = 0; sample <= 32; sample += 1) {
      const t = sample / 32;
      const point = cubicPoint(curve, t);
      const candidate = distance(point, desired);
      if (candidate < localDistance) {
        localDistance = candidate;
        bestT = t;
      }
      if (candidate < best.distance) best = { segmentIndex, t, point, tangent: cubicTangent(curve, t), distance: candidate };
    }
    let low = clamp(bestT - 1 / 32, 0, 1);
    let high = clamp(bestT + 1 / 32, 0, 1);
    for (let round = 0; round < 10; round += 1) {
      const leftT = low + (high - low) / 3;
      const rightT = high - (high - low) / 3;
      if (distance(cubicPoint(curve, leftT), desired) <= distance(cubicPoint(curve, rightT), desired)) high = rightT;
      else low = leftT;
    }
    const t = (low + high) / 2;
    const point = cubicPoint(curve, t);
    const candidate = distance(point, desired);
    if (candidate < best.distance) best = { segmentIndex, t, point, tangent: cubicTangent(curve, t), distance: candidate };
  });
  return best;
}

function smartWeight(candidate: number, selected: number, count: number): number {
  if (candidate === selected) return 1;
  if (candidate < selected) return (candidate + 1) / (selected + 1);
  return (count - candidate) / Math.max(1, count - selected);
}

function smoothKnots(knots: Reroute[], source: Point, target: Point, updateLengths = true): Reroute[] {
  return knots.map((knot, index) => {
    const previous = index === 0 ? source : knots[index - 1];
    const next = index === knots.length - 1 ? target : knots[index + 1];
    return {
      ...knot,
      angle: angleOf(subtract(next, previous), finiteNumber(knot.angle, 0)),
      ...(updateLengths ? {
        in_length: clamp(distance(knot, previous) * 0.34, 10, 130),
        out_length: clamp(distance(knot, next) * 0.34, 10, 130),
      } : {}),
    };
  });
}

function rerouteId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `reroute-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

export default function ConditionEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, selected, markerEnd }: EdgeProps) {
  const { setEdges, screenToFlowPosition } = useReactFlow();
  const { zoom } = useViewport();
  const graphInteraction = useContext(GraphInteractionContext);
  const shiftPressed = useRef(false);
  const [selectedKnotId, setSelectedKnotId] = useState<string | null>(null);
  const route = String((data as any)?.route || 'bezier');
  const curvature = clamp(Number((data as any)?.curvature ?? 0.72), 0.2, 1.3);
  const labelOffset = Number((data as any)?.labelOffset || 0);
  const editable = (data as any)?.editable !== false;
  const kind = String((data as any)?.kind || 'control');
  const source = { x: sourceX, y: sourceY };
  const target = { x: targetX, y: targetY };
  const sourceDirection = direction(sourcePosition, false);
  const targetDirection = direction(targetPosition, true);
  const endpointDistance = distance(source, target);
  const stub = clamp(endpointDistance * 0.1, 13, 26);
  const sourceStub = add(source, sourceDirection, stub);
  const targetStub = add(target, targetDirection, -stub);
  const rawReroutes = validReroutes((data as any)?.reroutes || (data as any)?.waypoints);
  const reroutes = normaliseKnots(rawReroutes, sourceStub, targetStub);
  const built = buildCurves(
    sourceStub,
    targetStub,
    sourceDirection,
    targetDirection,
    reroutes,
    curvature,
    (data as any)?.sourceHandle,
    (data as any)?.targetHandle,
  );
  const curves = built.curves;
  const endpointFrame = useRef({ source: sourceStub, target: targetStub, distance: Math.max(1, endpointDistance) });

  const curvePath = curves.map((curve) => `C ${curve.c1.x} ${curve.c1.y}, ${curve.c2.x} ${curve.c2.y}, ${curve.b.x} ${curve.b.y}`).join(' ');
  let edgePath = `M ${source.x} ${source.y} L ${sourceStub.x} ${sourceStub.y} ${curvePath} L ${target.x} ${target.y}`;
  if (route === 'straight') edgePath = getStraightPath({ sourceX, sourceY, targetX, targetY })[0];

  const middleCurve = curves[Math.floor(curves.length / 2)] || { a: source, b: target, c1: source, c2: target };
  const labelPoint = cubicPoint(middleCurve, 0.5);
  const finalCurve = curves[curves.length - 1] || middleCurve;
  const directionPoint = cubicPoint(finalCurve, 0.78);
  const directionVector = cubicTangent(finalCurve, 0.78);
  const directionAngle = angleOf(directionVector) * 180 / Math.PI;
  const condition = String((data as any)?.condition || 'default');
  const conditionLabel = kind === 'data'
    ? `${String((data as any)?.sourcePort || 'value')} → ${String((data as any)?.targetPort || 'value')}`
    : condition === 'default' ? '' : (CONDITION_LABELS[condition] || condition);

  const selectEdge = (additive = false) => {
    window.setTimeout(() => {
      if (graphInteraction.selectEdge) graphInteraction.selectEdge(id, additive);
      else window.dispatchEvent(new CustomEvent('egoagent-edge-select', { detail: { id, additive } }));
    }, 0);
  };
  const beginHistory = () => window.dispatchEvent(new CustomEvent('egoagent-graph-history-begin'));

  const updateSpline = (next: Reroute[], sourceHandle = built.sourceHandle, targetHandle = built.targetHandle) => {
    setEdges((edges: Edge[]) => edges.map((edge) => edge.id === id
      ? {
          ...edge,
          data: {
            ...edge.data,
            route: 'bezier',
            reroutes: next,
            sourceHandle,
            targetHandle,
            waypoints: undefined,
            channelOffset: 0,
          },
        }
      : edge));
  };

  const resetSpline = (nextRaw: Reroute[]) => {
    const next = smoothKnots(nextRaw, sourceStub, targetStub);
    const reset = buildCurves(sourceStub, targetStub, sourceDirection, targetDirection, next, curvature, undefined, undefined);
    updateSpline(next, reset.sourceHandle, reset.targetHandle);
  };

  const insertAt = (segmentIndex: number, rawT: number) => {
    const curve = curves[segmentIndex];
    if (!curve) return;
    beginHistory();
    const t = clamp(rawT, 0.015, 0.985);
    const split = splitCubic(curve, t);
    const next = reroutes.map((item) => ({ ...item }));
    let sourceHandle = built.sourceHandle;
    let targetHandle = built.targetHandle;
    if (segmentIndex === 0) sourceHandle = distance(split.left.a, split.left.c1);
    else next[segmentIndex - 1].out_length = distance(split.left.a, split.left.c1);
    if (segmentIndex === curves.length - 1) targetHandle = distance(split.right.b, split.right.c2);
    else next[segmentIndex].in_length = distance(split.right.b, split.right.c2);
    const tangent = subtract(split.right.c1, split.left.c2);
    const newKnotId = rerouteId();
    next.splice(segmentIndex, 0, {
      id: newKnotId,
      ...split.point,
      angle: angleOf(tangent, angleOf(cubicTangent(curve, t))),
      in_length: distance(split.point, split.left.c2),
      out_length: distance(split.point, split.right.c1),
    });
    updateSpline(next, sourceHandle, targetHandle);
    setSelectedKnotId(newKnotId);
  };

  const insertAtPointer = (event: React.MouseEvent<SVGPathElement>) => {
    if (!editable || route === 'straight') return;
    event.preventDefault();
    event.stopPropagation();
    selectEdge();
    const flowPoint = screenToFlowPosition({ x: event.clientX, y: event.clientY });
    const hit = closestPointOnCurves(curves, flowPoint);
    insertAt(hit.segmentIndex, hit.t);
  };

  const beginKnotMove = (event: React.PointerEvent<HTMLButtonElement>, index: number) => {
    event.preventDefault();
    event.stopPropagation();
    setSelectedKnotId(reroutes[index]?.id || null);
    beginHistory();
    const startX = event.clientX;
    const startY = event.clientY;
    const initial = reroutes.map((item) => ({ ...item }));
    const initialCurves = curves.map((curve) => ({ ...curve }));
    const move = (moveEvent: PointerEvent) => {
      let delta = {
        x: (moveEvent.clientX - startX) / Math.max(0.1, zoom),
        y: (moveEvent.clientY - startY) / Math.max(0.1, zoom),
      };
      if (moveEvent.altKey) {
        const pointer = screenToFlowPosition({ x: moveEvent.clientX, y: moveEvent.clientY });
        const hit = closestPointOnCurves(initialCurves, pointer);
        delta = subtract(hit.point, initial[index]);
      }
      let next = initial.map((item, candidate) => {
        const weight = moveEvent.shiftKey ? (candidate === index ? 1 : 0) : smartWeight(candidate, index, initial.length);
        return { ...item, x: item.x + delta.x * weight, y: item.y + delta.y * weight };
      });
      if (!moveEvent.shiftKey) next = smoothKnots(next, sourceStub, targetStub);
      updateSpline(next);
    };
    const finish = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', finish);
      window.removeEventListener('pointercancel', finish);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', finish, { once: true });
    window.addEventListener('pointercancel', finish, { once: true });
  };

  const beginKnotRotation = (event: React.PointerEvent<HTMLButtonElement>, index: number) => {
    event.preventDefault();
    event.stopPropagation();
    setSelectedKnotId(reroutes[index]?.id || null);
    beginHistory();
    const initial = reroutes.map((item) => ({ ...item }));
    const originalAngle = finiteNumber(initial[index]?.angle, 0);
    const pointer = screenToFlowPosition({ x: event.clientX, y: event.clientY });
    const pointerAngle = angleOf(subtract(pointer, initial[index]), originalAngle);
    const move = (moveEvent: PointerEvent) => {
      const current = screenToFlowPosition({ x: moveEvent.clientX, y: moveEvent.clientY });
      const delta = angleOf(subtract(current, initial[index]), originalAngle) - pointerAngle;
      const next = initial.map((item, candidate) => {
        const weight = moveEvent.shiftKey ? (candidate === index ? 1 : 0) : smartWeight(candidate, index, initial.length);
        return { ...item, angle: finiteNumber(item.angle, 0) + delta * weight };
      });
      updateSpline(next);
    };
    const finish = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', finish);
      window.removeEventListener('pointercancel', finish);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', finish, { once: true });
    window.addEventListener('pointercancel', finish, { once: true });
  };

  const nudgeKnotRotation = (index: number, delta: number, localOnly: boolean) => {
    beginHistory();
    const next = reroutes.map((item, candidate) => ({
      ...item,
      angle: finiteNumber(item.angle, 0) + delta * (localOnly ? (candidate === index ? 1 : 0) : smartWeight(candidate, index, reroutes.length)),
    }));
    updateSpline(next);
  };

  const nudgeKnotPosition = (index: number, delta: Point, localOnly: boolean) => {
    beginHistory();
    let next = reroutes.map((item, candidate) => {
      const weight = localOnly ? (candidate === index ? 1 : 0) : smartWeight(candidate, index, reroutes.length);
      return { ...item, x: item.x + delta.x * weight, y: item.y + delta.y * weight };
    });
    if (!localOnly) next = smoothKnots(next, sourceStub, targetStub);
    updateSpline(next);
  };

  const removeReroute = (index: number) => {
    beginHistory();
    if (selectedKnotId === reroutes[index]?.id) setSelectedKnotId(null);
    resetSpline(reroutes.filter((_item, candidate) => candidate !== index));
  };

  const selectedKnotIndex = reroutes.findIndex((reroute) => reroute.id === selectedKnotId);

  useEffect(() => {
    // Insertion updates the edge model and local selection in the same event.
    // Do not clear the new id during the intermediate render where edge data
    // still contains the previous reroute list.
    if (!selected) setSelectedKnotId(null);
  }, [selected]);

  useEffect(() => {
    const keyDown = (event: KeyboardEvent) => { if (event.key === 'Shift') shiftPressed.current = true; };
    const keyUp = (event: KeyboardEvent) => { if (event.key === 'Shift') shiftPressed.current = false; };
    const blur = () => { shiftPressed.current = false; };
    window.addEventListener('keydown', keyDown);
    window.addEventListener('keyup', keyUp);
    window.addEventListener('blur', blur);
    return () => {
      window.removeEventListener('keydown', keyDown);
      window.removeEventListener('keyup', keyUp);
      window.removeEventListener('blur', blur);
    };
  }, []);

  useEffect(() => {
    const previous = endpointFrame.current;
    const current = { source: sourceStub, target: targetStub, distance: Math.max(1, endpointDistance) };
    endpointFrame.current = current;
    const sourceDelta = subtract(current.source, previous.source);
    const targetDelta = subtract(current.target, previous.target);
    if ((magnitude(sourceDelta) < EPSILON && magnitude(targetDelta) < EPSILON) || !reroutes.length) return;
    if (shiftPressed.current) return;
    const next = reroutes.map((item, index) => {
      const ratio = (index + 1) / (reroutes.length + 1);
      return {
        ...item,
        x: item.x + sourceDelta.x * (1 - ratio) + targetDelta.x * ratio,
        y: item.y + sourceDelta.y * (1 - ratio) + targetDelta.y * ratio,
      };
    });
    const scale = clamp(current.distance / previous.distance, 0.45, 2.2);
    updateSpline(smoothKnots(next, current.source, current.target), built.sourceHandle * scale, built.targetHandle * scale);
    // Node drag history is already recorded by App; knot deformation belongs
    // to the same atomic undo transaction.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceStub.x, sourceStub.y, targetStub.x, targetStub.y]);

  return <>
    <BaseEdge id={id} path={edgePath} markerEnd={markerEnd} interactionWidth={28} style={{
      stroke: selected ? 'var(--focus)' : kind === 'data' ? 'var(--graph-data-edge, #89b4fa)' : 'var(--graph-edge, #718096)',
      strokeWidth: selected ? 2.4 : kind === 'data' ? 1.8 : 1.55,
      strokeDasharray: kind === 'data' ? '4 3' : undefined,
      strokeLinecap: 'round',
    }} />
    <path
      d={edgePath}
      className="edge-route-hit"
      onPointerDown={(event) => {
        event.preventDefault();
        event.stopPropagation();
        selectEdge(event.shiftKey);
      }}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        selectEdge(event.shiftKey);
      }}
      onDoubleClick={insertAtPointer}
      onContextMenu={insertAtPointer}
    />
    <g className={`edge-terminal-chevron${selected ? ' selected' : ''}`} transform={`translate(${directionPoint.x} ${directionPoint.y}) rotate(${directionAngle})`} aria-hidden="true"><path d="M -4 -4 L 3 0 L -4 4" /></g>
    {selected && editable && route !== 'straight' && reroutes.map((reroute) => {
      const tangent = unitFromAngle(finiteNumber(reroute.angle, 0));
      const visualLength = clamp(Math.max(finiteNumber(reroute.in_length, 24), finiteNumber(reroute.out_length, 24)), 28, 64);
      const negative = add(reroute, tangent, -visualLength);
      const positive = add(reroute, tangent, visualLength);
      return <g key={`tangent-${reroute.id}`} className="edge-knot-tangent" aria-hidden="true">
        <line x1={negative.x} y1={negative.y} x2={positive.x} y2={positive.y} />
      </g>;
    })}
    <EdgeLabelRenderer>
      <button
        type="button"
        className={`edge-select-anchor nodrag nopan${selected ? ' selected' : ''}`}
        aria-label="选择连接边"
        title="单击选择；双击或右键连线可在鼠标位置添加控制点"
        style={{ position: 'absolute', transform: `translate(-50%, -50%) translate(${labelPoint.x}px,${labelPoint.y}px)` }}
        onPointerDown={(event) => {
          event.preventDefault();
          event.stopPropagation();
          selectEdge(false);
        }}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          selectEdge(false);
        }}
        onDoubleClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          selectEdge();
          insertAt(Math.floor(curves.length / 2), 0.5);
        }}
        onContextMenu={(event) => {
          event.preventDefault();
          event.stopPropagation();
          selectEdge();
          insertAt(Math.floor(curves.length / 2), 0.5);
        }}
      />
      {conditionLabel && <div className={`condition-edge-label ${kind}`} style={{ position: 'absolute', transform: `translate(-50%, -50%) translate(${labelPoint.x}px,${labelPoint.y + labelOffset + (selected && reroutes.length ? 24 : 0)}px)`, pointerEvents: 'all' }} onClick={(event) => { event.stopPropagation(); selectEdge(event.shiftKey); }}>{conditionLabel}</div>}
      {selected && editable && route !== 'straight' && reroutes.map((reroute, index) => {
        const tangent = unitFromAngle(finiteNumber(reroute.angle, 0));
        const visualLength = clamp(Math.max(finiteNumber(reroute.in_length, 24), finiteNumber(reroute.out_length, 24)), 28, 64);
        const rotationHandle = add(reroute, tangent, visualLength);
        return <div key={reroute.id}>
          <button
            type="button"
            className={`edge-reroute-socket nodrag nopan${selectedKnotId === reroute.id ? ' selected' : ''}`}
            aria-label={`移动控制点 ${index + 1}`}
            aria-pressed={selectedKnotId === reroute.id}
            title="单击选择；双击或 Delete 删除；拖动智能调整全部控制点；Shift+拖动只移动本点；Alt+拖动沿曲线滑动"
            style={{ position: 'absolute', transform: `translate(-50%, -50%) translate(${reroute.x}px,${reroute.y}px)` }}
            onPointerDown={(event) => beginKnotMove(event, index)}
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              setSelectedKnotId(reroute.id);
            }}
            onDoubleClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              removeReroute(index);
            }}
            onContextMenu={(event) => {
              event.preventDefault();
              event.stopPropagation();
              setSelectedKnotId(reroute.id);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Delete' || event.key === 'Backspace') {
                event.preventDefault();
                event.stopPropagation();
                removeReroute(index);
              } else if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
                event.preventDefault();
                event.stopPropagation();
                nudgeKnotPosition(index, {
                  x: event.key === 'ArrowLeft' ? -6 : event.key === 'ArrowRight' ? 6 : 0,
                  y: event.key === 'ArrowUp' ? -6 : event.key === 'ArrowDown' ? 6 : 0,
                }, event.shiftKey);
              }
            }}
          />
          <button
            type="button"
            className="edge-knot-rotation nodrag nopan"
            aria-label={`旋转控制点 ${index + 1}`}
            title="拖动旋转切线；Shift+拖动只旋转当前控制点；方向键可微调"
            style={{ position: 'absolute', transform: `translate(-50%, -50%) translate(${rotationHandle.x}px,${rotationHandle.y}px)` }}
            onPointerDown={(event) => beginKnotRotation(event, index)}
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              setSelectedKnotId(reroute.id);
            }}
            onKeyDown={(event) => {
              if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
                event.preventDefault();
                event.stopPropagation();
                nudgeKnotRotation(index, (event.key === 'ArrowLeft' ? -1 : 1) * Math.PI / 36, event.shiftKey);
              }
            }}
          />
        </div>;
      })}
      {selected && editable && route !== 'straight' && <div className="edge-route-toolbar nodrag nopan" style={{ position: 'absolute', transform: `translate(-50%, -50%) translate(${labelPoint.x}px,${labelPoint.y + labelOffset - 38}px)` }}>
        <button type="button" onClick={(event) => { event.stopPropagation(); insertAt(Math.floor(curves.length / 2), 0.5); }}>＋ 控制点</button>
        {selectedKnotIndex >= 0 && <button type="button" className="danger" onClick={(event) => { event.stopPropagation(); removeReroute(selectedKnotIndex); }}>删除选中点</button>}
        {reroutes.length > 0 && <button type="button" onClick={(event) => { event.stopPropagation(); beginHistory(); resetSpline([]); }}>清除控制点</button>}
      </div>}
    </EdgeLabelRenderer>
  </>;
}
