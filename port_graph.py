"""Bounded event-driven port graph scheduler used by Subflow nodes.

This is deliberately an internal runtime primitive rather than another visible
DAG component.  A block may emit the same named output more than once.  Dynamic
links create/complete downstream executions in event order, while static links
cache a value and reuse it for every later execution.
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from collections import defaultdict, deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pipeline_schema import validate_json_schema


class PortGraphError(RuntimeError):
    pass


class PortGraphLimitError(PortGraphError):
    pass


@dataclass
class PortBlockResult:
    """A block result with ordered, possibly repeated, named output events."""

    outputs: list[tuple[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


def _block_items(raw_blocks: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(raw_blocks, dict):
        return [(str(block_id), value) for block_id, value in raw_blocks.items()]
    if isinstance(raw_blocks, list):
        items: list[tuple[str, dict[str, Any]]] = []
        for value in raw_blocks:
            if not isinstance(value, dict) or not value.get("id"):
                raise PortGraphError("every port graph block must be an object with a non-empty id")
            items.append((str(value["id"]), value))
        return items
    raise PortGraphError("port_graph.blocks must be a non-empty object or array")


def normalize_port_graph(graph: Any) -> dict[str, Any]:
    if not isinstance(graph, dict):
        raise PortGraphError("port_graph must be an object")
    items = _block_items(graph.get("blocks"))
    if not items:
        raise PortGraphError("port_graph.blocks must not be empty")

    blocks: dict[str, dict[str, Any]] = {}
    for block_id, raw in items:
        if not isinstance(raw, dict):
            raise PortGraphError(f"block {block_id!r} must be an object")
        if not block_id:
            raise PortGraphError("block id must not be empty")
        if block_id in blocks:
            raise PortGraphError(f"duplicate block id: {block_id}")
        block = copy.deepcopy(raw)
        block["id"] = block_id
        input_schema = block.get("input_schema", {})
        if input_schema is not None and not isinstance(input_schema, dict):
            raise PortGraphError(f"block {block_id!r}.input_schema must be an object")
        required = block.get("required_inputs", (input_schema or {}).get("required", []))
        if not isinstance(required, list) or any(not isinstance(name, str) or not name for name in required):
            raise PortGraphError(f"block {block_id!r}.required_inputs must be an array of names")
        defaults = copy.deepcopy(block.get("defaults", {}))
        if not isinstance(defaults, dict):
            raise PortGraphError(f"block {block_id!r}.defaults must be an object")
        for name, schema in (input_schema or {}).get("properties", {}).items():
            if isinstance(schema, dict) and "default" in schema and name not in defaults:
                defaults[name] = copy.deepcopy(schema["default"])
        block["required_inputs"] = list(dict.fromkeys(required))
        block["defaults"] = defaults
        output_schemas = block.get("output_schemas", {})
        if not isinstance(output_schemas, dict):
            raise PortGraphError(f"block {block_id!r}.output_schemas must be an object")
        blocks[block_id] = block

    links: list[dict[str, Any]] = []
    seen_links: set[tuple[str, str, str, str, bool]] = set()
    static_sink_ports: set[tuple[str, str]] = set()
    dynamic_sink_ports: set[tuple[str, str]] = set()
    for index, raw in enumerate(graph.get("links", [])):
        if not isinstance(raw, dict):
            raise PortGraphError(f"port_graph.links[{index}] must be an object")
        link = {
            "source_id": str(raw.get("source_id", "")),
            "source_name": str(raw.get("source_name", "output")),
            "sink_id": str(raw.get("sink_id", "")),
            "sink_name": str(raw.get("sink_name", "input")),
            "is_static": bool(raw.get("is_static", False)),
        }
        if link["source_id"] not in blocks or link["sink_id"] not in blocks:
            raise PortGraphError(
                f"link {index} references a missing block: "
                f"{link['source_id']!r} -> {link['sink_id']!r}"
            )
        if not link["source_name"] or not link["sink_name"]:
            raise PortGraphError(f"link {index} port names must not be empty")
        signature = (
            link["source_id"], link["source_name"], link["sink_id"],
            link["sink_name"], link["is_static"],
        )
        if signature in seen_links:
            raise PortGraphError(f"duplicate port graph link: {signature}")
        seen_links.add(signature)
        sink_port = (link["sink_id"], link["sink_name"])
        (static_sink_ports if link["is_static"] else dynamic_sink_ports).add(sink_port)
        links.append(link)
    ambiguous = static_sink_ports & dynamic_sink_ports
    if ambiguous:
        raise PortGraphError(f"sink ports cannot mix static and dynamic links: {sorted(ambiguous)!r}")

    initial_inputs = copy.deepcopy(graph.get("initial_inputs", {}))
    if not isinstance(initial_inputs, dict):
        raise PortGraphError("port_graph.initial_inputs must be an object")
    unknown_initial = sorted(set(initial_inputs) - set(blocks))
    if unknown_initial:
        raise PortGraphError(f"initial_inputs references missing blocks: {unknown_initial!r}")

    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outgoing: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for link in links:
        incoming[link["sink_id"]].append(link)
        outgoing[(link["source_id"], link["source_name"])].append(link)

    for block_id, block in blocks.items():
        available = set(block["defaults"])
        available.update(link["sink_name"] for link in incoming[block_id])
        raw_initial = initial_inputs.get(block_id, {})
        samples = raw_initial if isinstance(raw_initial, list) else [raw_initial]
        for sample in samples:
            if not isinstance(sample, dict):
                raise PortGraphError(f"initial_inputs.{block_id} must be an object or array of objects")
            available.update(sample)
        impossible = sorted(set(block["required_inputs"]) - available)
        if impossible:
            raise PortGraphError(f"block {block_id!r} has required inputs with no source: {impossible!r}")

    return {
        **copy.deepcopy(graph),
        "blocks": blocks,
        "links": links,
        "initial_inputs": initial_inputs,
        "_incoming": dict(incoming),
        "_outgoing": dict(outgoing),
        "max_workers": max(1, min(int(graph.get("max_workers", 4)), 32)),
        "max_executions": max(1, int(graph.get("max_executions", 500))),
        "max_events": max(1, int(graph.get("max_events", 5000))),
        "fail_fast": bool(graph.get("fail_fast", True)),
    }


def validate_port_graph(graph: Any) -> list[str]:
    try:
        normalize_port_graph(graph)
        return []
    except (PortGraphError, TypeError, ValueError) as error:
        return [str(error)]


def _normalize_outputs(result: Any, block: dict[str, Any]) -> PortBlockResult:
    if isinstance(result, PortBlockResult):
        raw_outputs = result.outputs
        metadata = copy.deepcopy(result.metadata)
    else:
        metadata = {}
        if isinstance(result, dict) and isinstance(result.get("outputs"), list):
            raw_outputs = result["outputs"]
            metadata = copy.deepcopy(result.get("metadata", {}))
        elif isinstance(result, dict):
            raw_outputs = list(result.items())
        else:
            raw_outputs = [(str(block.get("output_port", "output")), result)]

    outputs: list[tuple[str, Any]] = []
    for index, item in enumerate(raw_outputs):
        if isinstance(item, dict):
            name = item.get("name")
            if name is None or "value" not in item:
                raise PortGraphError(f"output event {index} must contain name and value")
            value = item["value"]
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            name, value = item
        else:
            raise PortGraphError(f"output event {index} must be a (name, value) pair")
        name = str(name)
        if not name:
            raise PortGraphError(f"output event {index} has an empty name")
        outputs.append((name, copy.deepcopy(value)))
    return PortBlockResult(outputs=outputs, metadata=metadata)


class PortGraphRunner:
    """Run a normalized graph using AutoGPT-style port event accumulation."""

    def __init__(
        self,
        graph: dict[str, Any],
        execute_block: Callable[[dict[str, Any], dict[str, Any]], Any],
        *,
        review_block: Optional[Callable[[dict[str, Any], dict[str, Any]], Any]] = None,
        is_running: Optional[Callable[[], bool]] = None,
        on_event: Optional[Callable[[str, dict[str, Any]], None]] = None,
        initial_state: Optional[dict[str, Any]] = None,
        on_state: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        self.graph = normalize_port_graph(graph)
        self.execute_block = execute_block
        self.review_block = review_block
        self.is_running = is_running or (lambda: True)
        self.on_event = on_event or (lambda _name, _payload: None)
        self.on_state = on_state
        self.blocks = self.graph["blocks"]
        self.records: list[dict[str, Any]] = []
        self._records_by_id: dict[str, dict[str, Any]] = {}
        self._incomplete: dict[str, deque[str]] = defaultdict(deque)
        self._ready: deque[str] = deque()
        self._static_values: dict[tuple[str, str], Any] = {}
        self.output_events: list[dict[str, Any]] = []
        self.terminal_outputs: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self._next_execution = 1
        self._next_event = 1
        self._halted = False
        self._cancelled = False
        self._limit_error: Optional[str] = None
        self._signature = self._graph_signature()
        self._restored = initial_state is not None
        if initial_state is not None:
            self._restore(initial_state)

    def _graph_signature(self) -> str:
        payload = {"blocks": self.graph["blocks"], "links": self.graph["links"]}
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _snapshot(self) -> dict[str, Any]:
        return {
            "version": 1,
            "graph_signature": self._signature,
            "records": copy.deepcopy(self.records),
            "events": copy.deepcopy(self.output_events),
            "terminal_outputs": copy.deepcopy(self.terminal_outputs),
            "static_values": [
                {"block_id": block_id, "port": port, "value": copy.deepcopy(value)}
                for (block_id, port), value in self._static_values.items()
            ],
            "errors": copy.deepcopy(self.errors),
            "next_execution": self._next_execution,
            "next_event": self._next_event,
        }

    def _save_state(self) -> None:
        if self.on_state is not None:
            self.on_state(self._snapshot())

    def _restore(self, state: Any) -> None:
        if not isinstance(state, dict) or state.get("version") != 1:
            raise PortGraphError("port graph resume state has an unsupported format")
        if state.get("graph_signature") != self._signature:
            raise PortGraphError("port graph resume state does not match the current graph")
        raw_records = state.get("records", [])
        if not isinstance(raw_records, list):
            raise PortGraphError("port graph resume records must be an array")
        for raw in raw_records:
            if not isinstance(raw, dict) or raw.get("block_id") not in self.blocks or not raw.get("id"):
                raise PortGraphError("port graph resume contains an invalid execution record")
            record = copy.deepcopy(raw)
            status = record.get("status")
            if status in {"running", "ready", "cancelled", "skipped", "limit_exceeded"}:
                required = self.blocks[record["block_id"]]["required_inputs"]
                record["status"] = "ready" if all(name in record.get("inputs", {}) for name in required) else "incomplete"
            self.records.append(record)
            self._records_by_id[record["id"]] = record
            if record["status"] == "ready":
                self._ready.append(record["id"])
            elif record["status"] == "incomplete":
                self._incomplete[record["block_id"]].append(record["id"])
        self.output_events = copy.deepcopy(state.get("events", []))
        self.terminal_outputs = copy.deepcopy(state.get("terminal_outputs", []))
        self.errors = copy.deepcopy(state.get("errors", []))
        for item in state.get("static_values", []):
            if isinstance(item, dict) and item.get("block_id") in self.blocks and item.get("port"):
                self._static_values[(str(item["block_id"]), str(item["port"]))] = copy.deepcopy(item.get("value"))
        self._next_execution = max(int(state.get("next_execution", 1)), len(self.records) + 1)
        self._next_event = max(int(state.get("next_event", 1)), len(self.output_events) + 1)

    def _emit(self, name: str, payload: dict[str, Any]) -> None:
        self.on_event(name, copy.deepcopy(payload))

    def _record(self, execution_id: str) -> dict[str, Any]:
        return self._records_by_id[execution_id]

    def _new_execution(
        self,
        block_id: str,
        inputs: Optional[dict[str, Any]] = None,
        *,
        save_state: bool = True,
    ) -> dict[str, Any]:
        if len(self.records) >= self.graph["max_executions"]:
            raise PortGraphLimitError(f"port graph exceeded max_executions ({self.graph['max_executions']})")
        execution_id = f"e{self._next_execution}"
        self._next_execution += 1
        block = self.blocks[block_id]
        values = copy.deepcopy(block["defaults"])
        for (sink_id, sink_name), value in self._static_values.items():
            if sink_id == block_id:
                values[sink_name] = copy.deepcopy(value)
        values.update(copy.deepcopy(inputs or {}))
        record = {
            "id": execution_id,
            "block_id": block_id,
            "status": "incomplete",
            "inputs": values,
            "outputs": [],
            "error": None,
            "metadata": {},
        }
        self.records.append(record)
        self._records_by_id[execution_id] = record
        self._incomplete[block_id].append(execution_id)
        self._emit("port_execution_created", {"execution_id": execution_id, "block_id": block_id, "inputs": values})
        self._queue_if_ready(record)
        if save_state:
            self._save_state()
        return record

    def _queue_if_ready(self, record: dict[str, Any]) -> None:
        if record["status"] != "incomplete":
            return
        block = self.blocks[record["block_id"]]
        if any(name not in record["inputs"] for name in block["required_inputs"]):
            return
        input_schema = block.get("input_schema")
        if input_schema:
            errors = validate_json_schema(record["inputs"], input_schema, path="$inputs")
            if errors:
                self._fail_record(record, PortGraphError("; ".join(errors)))
                return
        record["status"] = "ready"
        try:
            self._incomplete[record["block_id"]].remove(record["id"])
        except ValueError:
            pass
        self._ready.append(record["id"])
        self._emit("port_execution_ready", {"execution_id": record["id"], "block_id": record["block_id"]})

    def _find_or_create_sink(self, block_id: str, port: str) -> dict[str, Any]:
        for execution_id in list(self._incomplete[block_id]):
            record = self._record(execution_id)
            if record["status"] == "incomplete" and port not in record["inputs"]:
                return record
        return self._new_execution(block_id, save_state=False)

    def _set_sink(self, record: dict[str, Any], port: str, value: Any) -> None:
        if record["status"] != "incomplete" or port in record["inputs"]:
            return
        record["inputs"][port] = copy.deepcopy(value)
        self._queue_if_ready(record)

    def _deliver_output(self, record: dict[str, Any], name: str, value: Any) -> None:
        if len(self.output_events) >= self.graph["max_events"]:
            raise PortGraphLimitError(f"port graph exceeded max_events ({self.graph['max_events']})")
        event = {
            "sequence": self._next_event,
            "execution_id": record["id"],
            "block_id": record["block_id"],
            "name": name,
            "value": copy.deepcopy(value),
        }
        self._next_event += 1
        self.output_events.append(event)
        record["outputs"].append(copy.deepcopy(event))
        self._emit("port_output", event)
        links = self.graph["_outgoing"].get((record["block_id"], name), [])
        if not links:
            self.terminal_outputs.append(copy.deepcopy(event))
            return
        for link in links:
            sink_id, sink_name = link["sink_id"], link["sink_name"]
            if link["is_static"]:
                self._static_values[(sink_id, sink_name)] = copy.deepcopy(value)
                candidates = [
                    self._record(execution_id)
                    for execution_id in list(self._incomplete[sink_id])
                    if self._record(execution_id)["status"] == "incomplete"
                    and sink_name not in self._record(execution_id)["inputs"]
                ]
                if not candidates:
                    candidates = [self._new_execution(sink_id, save_state=False)]
                for candidate in candidates:
                    self._set_sink(candidate, sink_name, value)
            else:
                self._set_sink(self._find_or_create_sink(sink_id, sink_name), sink_name, value)
        self._save_state()

    def _fail_record(self, record: dict[str, Any], error: BaseException) -> None:
        record["status"] = "failed"
        record["error"] = {"type": type(error).__name__, "message": str(error)}
        self.errors.append({"execution_id": record["id"], "block_id": record["block_id"], **record["error"]})
        self._emit("port_execution_failed", {"execution_id": record["id"], "block_id": record["block_id"], "error": record["error"]})
        if self.graph["fail_fast"]:
            self._halted = True
            self._save_state()
            return
        error_port = str(self.blocks[record["block_id"]].get("error_port", "error"))
        self._deliver_output(record, error_port, copy.deepcopy(record["error"]))
        self._save_state()

    def _review(self, record: dict[str, Any]) -> bool:
        block = self.blocks[record["block_id"]]
        if not block.get("sensitive") or self.review_block is None:
            return True
        result = self.review_block(copy.deepcopy(block), copy.deepcopy(record["inputs"]))
        approved = False
        data = record["inputs"]
        message = ""
        if isinstance(result, dict):
            approved = bool(result.get("approved", result.get("decision") == "approved"))
            data = result.get("data", data)
            message = str(result.get("message", ""))
        elif isinstance(result, tuple):
            approved = bool(result[0])
            if len(result) > 1 and isinstance(result[1], dict):
                data = result[1]
            if len(result) > 2:
                message = str(result[2])
        else:
            approved = bool(result)
        if approved:
            record["inputs"] = copy.deepcopy(data)
            record["review"] = {"decision": "approved", "message": message}
            return True
        record["status"] = "rejected"
        record["review"] = {"decision": "rejected", "message": message}
        self._emit("port_execution_rejected", {"execution_id": record["id"], "block_id": record["block_id"], "message": message})
        rejection_port = str(block.get("rejection_port", "rejected"))
        self._deliver_output(record, rejection_port, {"inputs": copy.deepcopy(data), "message": message})
        self._save_state()
        return False

    def _submit_ready(self, pool: ThreadPoolExecutor, futures: dict[Future, str]) -> None:
        while self._ready and len(futures) < self.graph["max_workers"] and not self._halted:
            if not self.is_running():
                self._cancelled = True
                return
            execution_id = self._ready.popleft()
            record = self._record(execution_id)
            if record["status"] != "ready" or not self._review(record):
                continue
            record["status"] = "running"
            record["started_at"] = time.monotonic()
            self._emit("port_execution_started", {"execution_id": execution_id, "block_id": record["block_id"]})
            block = copy.deepcopy(self.blocks[record["block_id"]])
            block["_execution_id"] = execution_id
            inputs = copy.deepcopy(record["inputs"])
            futures[pool.submit(self.execute_block, block, inputs)] = execution_id
            self._save_state()

    def _complete_future(self, future: Future, execution_id: str) -> None:
        record = self._record(execution_id)
        try:
            result = _normalize_outputs(future.result(), self.blocks[record["block_id"]])
            delivered = len(record.get("outputs", []))
            for output_index, (name, value) in enumerate(result.outputs):
                if output_index < delivered:
                    previous = record["outputs"][output_index]
                    if previous.get("name") != name or previous.get("value") != value:
                        raise PortGraphError(
                            f"resumed block {record['block_id']!r} changed already-delivered output {output_index}"
                        )
                    continue
                schemas = self.blocks[record["block_id"]].get("output_schemas", {})
                schema = schemas.get(name)
                if schema is None and name == str(self.blocks[record["block_id"]].get("output_port", "output")):
                    schema = self.blocks[record["block_id"]].get("output_schema")
                if schema:
                    errors = validate_json_schema(value, schema, path=f"$outputs.{name}")
                    if errors:
                        raise PortGraphError("; ".join(errors))
                self._deliver_output(record, name, value)
            record["metadata"] = copy.deepcopy(result.metadata)
            record["status"] = "completed"
            record["elapsed_seconds"] = round(time.monotonic() - record["started_at"], 6)
            self._emit("port_execution_completed", {"execution_id": execution_id, "block_id": record["block_id"], "outputs": record["outputs"]})
            self._save_state()
        except PortGraphLimitError as error:
            record["status"] = "limit_exceeded"
            record["error"] = {"type": type(error).__name__, "message": str(error)}
            raise
        except BaseException as error:
            record["elapsed_seconds"] = round(time.monotonic() - record.get("started_at", time.monotonic()), 6)
            self._fail_record(record, error)

    def run(self) -> dict[str, Any]:
        incoming = self.graph["_incoming"]
        explicit = self.graph["initial_inputs"]
        try:
            if not self._restored:
                for block_id in self.blocks:
                    if block_id in explicit:
                        samples = explicit[block_id] if isinstance(explicit[block_id], list) else [explicit[block_id]]
                        for sample in samples:
                            self._new_execution(block_id, sample)
                    elif not incoming.get(block_id):
                        self._new_execution(block_id)

            futures: dict[Future, str] = {}
            with ThreadPoolExecutor(max_workers=self.graph["max_workers"], thread_name_prefix="ego-port") as pool:
                while (self._ready or futures) and not self._cancelled:
                    self._submit_ready(pool, futures)
                    if self._halted and not futures:
                        break
                    if not self.is_running():
                        self._cancelled = True
                        for future in futures:
                            future.cancel()
                        break
                    if not futures:
                        continue
                    done, _ = wait(tuple(futures), timeout=0.05, return_when=FIRST_COMPLETED)
                    for future in done:
                        execution_id = futures.pop(future)
                        self._complete_future(future, execution_id)
                if self._halted:
                    for future in futures:
                        future.cancel()
                    if futures:
                        wait(tuple(futures))
                    for future, execution_id in list(futures.items()):
                        record = self._record(execution_id)
                        if future.cancelled():
                            record["status"] = "skipped"
                        else:
                            self._complete_future(future, execution_id)
        except PortGraphLimitError as error:
            self._limit_error = str(error)
            self.errors.append({"type": type(error).__name__, "message": str(error)})
            self._emit("port_graph_limit", {"message": str(error)})

        for record in self.records:
            if self._cancelled and record["status"] in {"incomplete", "ready", "running"}:
                record["status"] = "cancelled"
            elif (self._halted or self._limit_error) and record["status"] in {"ready", "running"}:
                record["status"] = "skipped"
        self._save_state()

        if self._cancelled:
            status = "cancelled"
        elif self._limit_error:
            status = "limit_exceeded"
        elif self._halted:
            status = "failed"
        elif any(record["status"] == "incomplete" for record in self.records):
            status = "blocked"
        elif self.errors:
            status = "completed_with_errors"
        else:
            status = "completed"
        result = {
            "status": status,
            "executions": copy.deepcopy(self.records),
            "events": copy.deepcopy(self.output_events),
            "terminal_outputs": copy.deepcopy(self.terminal_outputs),
            "static_values": [
                {"block_id": block_id, "port": port, "value": copy.deepcopy(value)}
                for (block_id, port), value in self._static_values.items()
            ],
            "errors": copy.deepcopy(self.errors),
            "counts": {
                "executions": len(self.records),
                "completed": sum(record["status"] == "completed" for record in self.records),
                "rejected": sum(record["status"] == "rejected" for record in self.records),
                "failed": sum(record["status"] == "failed" for record in self.records),
                "events": len(self.output_events),
            },
            "resumed": self._restored,
        }
        self._emit("port_graph_done", {"status": status, "counts": result["counts"]})
        return result
