"""Project EgoAgent verl JSONL interchange rows into official Parquet inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def prepare(source: Path, destination: Path, *, include_unlabelled: bool = False) -> dict:
    if not source.is_file():
        raise FileNotFoundError(source)
    train_path = destination / "train.parquet"
    val_path = destination / "val.parquet"
    if train_path.exists() or val_path.exists():
        raise FileExistsError(
            f"Refusing to replace an existing verl dataset in {destination}; choose a new destination"
        )

    rows = []
    seen_calls = set()
    with source.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            item = json.loads(line)
            prompt = item.get("prompt")
            metadata = item.get("extra_info") if isinstance(item.get("extra_info"), dict) else {}
            call_id = str(metadata.get("model_call_id") or "")
            if not call_id:
                raise ValueError(f"row {line_number} has no model_call_id")
            if call_id in seen_calls:
                raise ValueError(f"duplicate model_call_id {call_id}")
            seen_calls.add(call_id)
            if not isinstance(prompt, list) or not all(isinstance(message, dict) for message in prompt):
                raise ValueError(f"row {line_number} has an invalid chat prompt")
            reward_model = item.get("reward_model") if isinstance(item.get("reward_model"), dict) else {}
            ground_truth = reward_model.get("ground_truth")
            if ground_truth is None and not include_unlabelled:
                continue
            response = item.get("response") if isinstance(item.get("response"), dict) else {}
            rows.append(
                {
                    "data_source": str(item.get("data_source") or "egoagent_trajectory"),
                    "prompt": prompt,
                    "ability": str(item.get("ability") or "agent"),
                    "reward_model": {
                        "style": str(reward_model.get("style") or "external_verifier"),
                        "ground_truth": ground_truth,
                    },
                    "extra_info": {
                        **metadata,
                        "recorded_response": str(response.get("content") or ""),
                        "recorded_reward": item.get("reward"),
                    },
                }
            )
    if not rows:
        raise ValueError("No verl-trainable rows have a trusted ground_truth reward")

    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as error:
        raise RuntimeError("PyArrow is required in the training environment") from error

    destination.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, train_path)
    pq.write_table(table, val_path)
    agents = sorted({str(row["extra_info"].get("agent")) for row in rows})
    runs = sorted({str(row["extra_info"].get("run_id")) for row in rows})
    result = {
        "source": str(source.resolve()),
        "train": str(train_path.resolve()),
        "validation": str(val_path.resolve()),
        "rows": len(rows),
        "agents": agents,
        "runs": runs,
        "model_call_ids": [row["extra_info"]["model_call_id"] for row in rows],
        "excluded_unlabelled": not include_unlabelled,
    }
    (destination / "manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--include-unlabelled", action="store_true")
    args = parser.parse_args()
    result = prepare(
        args.source.resolve(),
        args.destination.resolve(),
        include_unlabelled=args.include_unlabelled,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
