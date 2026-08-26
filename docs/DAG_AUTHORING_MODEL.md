# DAG authoring model

EgoAgent uses one canonical contract for both authors:

- A person edits a graph in Studio with forms, variable completion, typed ports and schema builders.
- An Agent reads the same compact contract through Blueprint/EgoIR guides and creates or patches the graph transactionally.
- The runtime validates the saved graph, component manifests, model outputs and SubDAG boundaries.

The canonical catalog lives in `dag_contracts.py` and is available at `GET /api/dag/contracts`. UI-only copies of node contracts are intentionally avoided.

## Data model

Every node reads from the run context and produces a `NodeOutput`. Explicit `inputs` resolve references before execution. Explicit `outputs` copy named output ports back into `$ctx`. This permits old Harnesses that rely on `$last` while making new graphs inspectable and composable.

Supported reference families are:

- `$ctx.name`: durable data for the current run;
- `$node.node_id.port`: a named result from a specific node invocation;
- `$last.port`: the previous node result;
- `$session.messages`, `$session.full_messages`, `$session.state`: live and audit conversation state;
- `$stats`: budget and execution counters.

## SubDAG components

A reusable Harness declares a `component` manifest. Inputs can be required, have defaults and carry JSON Schema. Outputs select a path from the child run and can also carry JSON Schema. Studio edits these contracts as rows rather than raw JSON. A SubDAG node imports the selected component contract, suggests missing ports and maps child outputs to parent `$ctx` paths.

## Human and Agent authoring

Studio keeps common configuration in visual controls and reserves an “Advanced JSON” escape hatch for arbitrary nested values. Agent authors use either:

- Blueprint for simple create/patch operations;
- EgoIR for typed structural editing and round trips;
- the full runtime format only when an advanced field is unavailable in those representations.

Both guides include `ego.dag-contracts.v1`, so an Agent does not need to guess node ports or control events. Writes remain revision-checked and validated before commit.

## Validation boundaries

Validation occurs at four points:

1. graph and component validation when saving;
2. input reference resolution before a node runs;
3. optional `output_schema` validation after a node runs;
4. SubDAG input and output schema validation at the component boundary.

This is intentionally a gradual typing model: a prototype can omit explicit ports, while reusable or control-flow-critical components can be fully typed.
