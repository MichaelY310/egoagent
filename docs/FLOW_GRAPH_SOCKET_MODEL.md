# EgoAgent Flow Graph Socket Model

The Build editor uses a Blender-style socket model while retaining the original runtime format.

- Yellow diamond sockets are control flow. A node event such as `has_tool_calls` connects to another node's `flow` input and is stored in the source node's `edges` list.
- Blue circular sockets are typed data flow. Every declared contract input/output is a separate socket, so a node with two inputs visibly has two independent connection points.
- A data connection is stored in `pipeline.data_links` for visual identity and reroute geometry. The editor also writes `$node.<source>.<output>` into the target node's `inputs` mapping, so existing runtimes execute the graph unchanged.
- One data input accepts one producer by default. Connecting another producer replaces the old link, matching Blender's normal single-input socket behavior. The control `flow` input accepts multiple incoming events.
- Link endpoints cannot be detached from their sockets by route editing. Select a link and add a Reroute socket, then drag the Reroute around obstacles. Double-click no longer mutates links.
- Node moves, node/edge deletion, connection creation, inspector edits, layout and Bezier-knot edits participate in the Build undo/redo history.

## Editable edge spline

`reroutes` are shape-bearing Bezier knots rather than plain polyline points. A knot stores `x`, `y`, tangent `angle`, `in_length`, and `out_length`; edge-level `source_handle` and `target_handle` preserve the constrained socket tangents. Double-click/right-click insertion uses De Casteljau subdivision, so adding a knot does not alter the existing curve. Normal knot and endpoint movement applies proportional falloff and tangent smoothing; holding Shift performs a local edit, while Alt-drag projects a knot along the pre-drag spline.

## Whole-graph auto layout

Build's **自动整理** command is a deterministic two-stage layout, not a fixed grid reset:

1. Strongly connected components are condensed so cyclic Flow graphs can be layered without pretending they are DAGs. Alternating barycentric sweeps and adjacent transposition reduce estimated crossings while preserving stable authoring order for ties.
2. Actual rendered node dimensions are packed without overlap. Each Edge is then routed independently through layer and row corridors. The route cost combines length, bend count, node collision, edge crossing, and collinear overlap; already-routed edges contribute congestion to later routes. Back-edges and same-layer edges prefer outside lanes.

Users can tune three independent objectives: compactness, avoidance strength, and Edge simplicity. A compact/high-simplicity profile produces fewer knots; a high-avoidance profile is allowed to consume more canvas and introduce more knots. Node collision always has a very large penalty. Exact zero crossings cannot be guaranteed for non-planar graphs, so the UI reports before/after geometric estimates instead of making that claim.

The resulting node coordinates are persisted as `editor_position`. Auto-generated spline knots use the same `reroutes` representation as manual editing, so users can refine the result, undo the whole format operation atomically, save it into an immutable Flow version, and replay the exact canvas later.

Legacy `waypoints` and position-only `reroutes` are upgraded in memory with smooth tangent defaults and saved in the richer knot form. Legacy Harnesses without `source_port`, `target_port`, or `data_links` remain loadable.
