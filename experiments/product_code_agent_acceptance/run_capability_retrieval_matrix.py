"""Run the pre-registered capability retrieval matrix without mutating usage metrics."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
CASES_PATH = Path(__file__).with_name("capability_retrieval_cases.json")
RESULTS_ROOT = Path(__file__).with_name("results")
MODES = ("none", "lexical", "semantic", "hybrid")


def _rank(results: list[dict[str, Any]], expected_names: set[str]) -> int | None:
    for index, item in enumerate(results, 1):
        if str(item.get("name")) in expected_names:
            return index
    return None


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"queries": 0, "hit_at_1": None, "hit_at_3": None, "mrr": None, "median_latency_ms": None}
    ranks = [row.get("rank") for row in rows]
    return {
        "queries": len(rows),
        "hit_at_1": round(sum(rank == 1 for rank in ranks) / len(rows), 4),
        "hit_at_3": round(sum(rank is not None and rank <= 3 for rank in ranks) / len(rows), 4),
        "mrr": round(sum(1.0 / rank if rank else 0.0 for rank in ranks) / len(rows), 4),
        "median_latency_ms": round(statistics.median(float(row["latency_ms"]) for row in rows), 2),
    }


def _workspace_override_probe(registry: Any) -> dict[str, Any]:
    """Prove workspace precedence and cross-workspace isolation with a disposable fixture."""
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="capability-workspace-", dir=RESULTS_ROOT) as temp_value:
        workspace = Path(temp_value).resolve()
        skill = workspace / ".agents" / "skills" / "web_search"
        skill.mkdir(parents=True)
        (skill / "meta.json").write_text(
            json.dumps(
                {
                    "name": "web_search",
                    "description": "Workspace-local private documentation search override used only by the parity probe.",
                    "tags": ["workspace-local", "private-docs", "parity-probe"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        local_registry = type(registry)(REPO_ROOT, workspace=workspace)
        indexed = local_registry.reindex()
        local_result = local_registry.search(
            "web_search",
            kinds=["skill"],
            limit=3,
            record_impressions=False,
            mode="hybrid",
        )
        local_top = (local_result.get("results") or [{}])[0]
        foreign_visible = [
            item
            for item in registry.list(kind="skill", limit=500, _deduplicate=False)
            if item.get("workspace_root") == str(workspace)
        ]
        outcome = {
            "workspace": str(workspace),
            "indexed": indexed,
            "local_top_name": local_top.get("name"),
            "local_top_scope": local_top.get("scope"),
            "local_top_owner": local_top.get("owner"),
            "workspace_precedence_passed": local_top.get("name") == "web_search" and local_top.get("scope") == "workspace",
            "cross_workspace_isolation_passed": not foreign_visible,
        }
    # Reindex the now-empty disposable workspace so its private row is removed
    # from the shared SQLite catalog instead of accumulating benchmark debris.
    type(registry)(REPO_ROOT, workspace=workspace).reindex()
    return outcome


def run(*, cases_path: Path, output_dir: Path | None = None) -> Path:
    from capability_registry import CapabilityRegistry

    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = list(payload.get("cases") or [])
    if not cases:
        raise ValueError("No retrieval cases were declared")
    counts: dict[str, int] = defaultdict(int)
    for case in cases:
        counts[str(case["kind"])] += 1
    required = {"tool", "skill", "knowledge", "identity", "harness"}
    if set(counts) != required or any(counts[kind] < 3 for kind in required):
        raise ValueError(f"Expected at least three cases for every capability kind; got {dict(counts)}")

    registry = CapabilityRegistry(REPO_ROOT, workspace=REPO_ROOT)
    index_result = registry.reindex()
    workspace_override = _workspace_override_probe(registry)
    rows: list[dict[str, Any]] = []
    for mode in MODES:
        for case in cases:
            started = time.perf_counter()
            if mode == "none":
                result: dict[str, Any] = {
                    "results": [],
                    "retrieval": "none",
                    "embedding": {"available": False, "provider": "disabled"},
                    "creation_recommended": True,
                }
            else:
                result = registry.search(
                    str(case["query"]),
                    kinds=[str(case["kind"])],
                    limit=5,
                    record_impressions=False,
                    mode=mode,
                )
            latency_ms = (time.perf_counter() - started) * 1000.0
            returned = list(result.get("results") or [])
            expected_names = {str(name) for name in case["expected_names"]}
            rank = _rank(returned, expected_names)
            embedding = dict(result.get("embedding") or {})
            rows.append(
                {
                    "case_id": case["id"],
                    "kind": case["kind"],
                    "query": case["query"],
                    "expected_names": sorted(expected_names),
                    "mode": mode,
                    "actual_retrieval": result.get("retrieval"),
                    "rank": rank,
                    "hit_at_1": rank == 1,
                    "hit_at_3": rank is not None and rank <= 3,
                    "reciprocal_rank": round(1.0 / rank, 6) if rank else 0.0,
                    "latency_ms": round(latency_ms, 3),
                    "creation_recommended": bool(result.get("creation_recommended")),
                    "embedding_available": bool(embedding.get("available")),
                    "embedding_provider": embedding.get("provider"),
                    "embedding_model": embedding.get("model"),
                    "embedding_fallback_reason": embedding.get("fallback_reason"),
                    "top_results": [
                        {
                            "name": item.get("name"),
                            "kind": item.get("kind"),
                            "scope": item.get("scope"),
                            "score": item.get("score"),
                            "lexical_score": item.get("lexical_score"),
                            "semantic_score": item.get("semantic_score"),
                            "match_reason": item.get("match_reason"),
                        }
                        for item in returned
                    ],
                }
            )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["mode"])].append(row)
    by_mode = {mode: _metrics(grouped[mode]) for mode in MODES}
    by_kind_mode: dict[str, dict[str, Any]] = {}
    for kind in sorted(required):
        by_kind_mode[kind] = {
            mode: _metrics([row for row in rows if row["kind"] == kind and row["mode"] == mode])
            for mode in MODES
        }

    semantic_infra_errors = [
        row
        for row in rows
        if row["mode"] in {"semantic", "hybrid"} and not row["embedding_available"]
    ]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = output_dir or (RESULTS_ROOT / f"{timestamp}_capability_retrieval_matrix_r1")
    output_dir.mkdir(parents=True, exist_ok=False)
    report = {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "cases_file": str(cases_path.relative_to(REPO_ROOT)),
        "catalog": index_result,
        "summary": {
            "by_mode": by_mode,
            "by_kind_and_mode": by_kind_mode,
            "semantic_infrastructure_valid": not semantic_infra_errors,
            "semantic_infrastructure_error_count": len(semantic_infra_errors),
            "workspace_override": workspace_override,
        },
        "rows": rows,
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path), **report["summary"]}, ensure_ascii=False, indent=2))
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    run(cases_path=args.cases.resolve(), output_dir=args.output_dir.resolve() if args.output_dir else None)


if __name__ == "__main__":
    main()
