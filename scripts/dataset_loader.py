#!/usr/bin/env python3
"""EgoAgent Dataset Loader - unified data loading API for all 6 directions."""

import json
import os
import random
from pathlib import Path
from typing import List, Dict, Tuple

BASE_DIR = Path("/mnt/bn/yangyuan-search-agent-rl-hl/mlx/users/yangyuan.335/data/egoagent_datasets")


def load_jsonl(filepath) -> List[Dict]:
    data = []
    filepath = Path(filepath)
    if not filepath.exists():
        return data
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    data.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return data


class DatasetLoader:
    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir) if base_dir else BASE_DIR
    
    def load_direction(self, direction, max_train=None, max_test=None):
        dir_map = {
            "dir1": "dir1_meta_evolution",
            "dir2": "dir2_identity_persona",
            "dir3": "dir3_evo_benchmark",
            "dir4": "dir4_pipeline_search",
            "dir5": "dir5_lifelong_learning",
            "dir6": "dir6_self_play",
        }
        if direction in dir_map:
            direction = dir_map[direction]
        dir_path = self.base_dir / direction
        train = load_jsonl(dir_path / "train_adapted.jsonl")
        test = load_jsonl(dir_path / "test_adapted.jsonl")
        if max_train and len(train) > max_train:
            train = random.sample(train, max_train)
        if max_test and len(test) > max_test:
            test = random.sample(test, max_test)
        return train, test
    
    def get_tasks_for_evolution(self, direction="dir1", n_tasks=10):
        train, _ = self.load_direction(direction)
        tasks = [item.get("task", item.get("topic", "")) for item in train if item.get("task") or item.get("topic")]
        if len(tasks) > n_tasks:
            tasks = random.sample(tasks, n_tasks)
        return tasks
    
    def summary(self):
        stats = {}
        for d in sorted(self.base_dir.iterdir()):
            if d.is_dir() and d.name.startswith("dir"):
                train = load_jsonl(d / "train_adapted.jsonl")
                test = load_jsonl(d / "test_adapted.jsonl")
                raw_files = [f for f in d.glob("*.jsonl") if "adapted" not in f.name]
                raw_count = sum(sum(1 for _ in open(f)) for f in raw_files)
                stats[d.name] = {"train": len(train), "test": len(test), "raw": raw_count}
        return stats


def get_evolution_tasks(n=20, difficulty=None):
    loader = DatasetLoader()
    train, _ = loader.load_direction("dir1")
    if difficulty:
        train = [t for t in train if t.get("difficulty") == difficulty]
    tasks = [item["task"] for item in train if "task" in item]
    if len(tasks) > n:
        tasks = random.sample(tasks, n)
    return tasks


def get_persona_probes(n=10):
    loader = DatasetLoader()
    train, _ = loader.load_direction("dir2")
    if len(train) > n:
        train = random.sample(train, n)
    return train


def get_benchmark_tasks(suite="mixed", n=20):
    loader = DatasetLoader()
    train, test = loader.load_direction("dir3")
    all_tasks = train + test
    if suite:
        all_tasks = [t for t in all_tasks if t.get("suite") == suite]
    if len(all_tasks) > n:
        all_tasks = random.sample(all_tasks, n)
    return all_tasks


def get_pipeline_eval_tasks(n=20):
    loader = DatasetLoader()
    train, _ = loader.load_direction("dir4")
    if len(train) > n:
        train = random.sample(train, n)
    return train


def get_task_stream(n_streams=5, tasks_per_stream=10):
    loader = DatasetLoader()
    train, _ = loader.load_direction("dir5")
    streams = {}
    for item in train:
        sid = item.get("stream_id", 0)
        if sid not in streams:
            streams[sid] = []
        streams[sid].append(item)
    result = []
    for sid in sorted(streams.keys())[:n_streams]:
        stream = sorted(streams[sid], key=lambda x: x.get("position_in_stream", 0))
        result.append(stream[:tasks_per_stream])
    return result


def get_debate_topics(n=20):
    loader = DatasetLoader()
    train, _ = loader.load_direction("dir6")
    if len(train) > n:
        train = random.sample(train, n)
    return train


if __name__ == "__main__":
    loader = DatasetLoader()
    stats = loader.summary()
    print("EgoAgent Dataset Statistics")
    for name, s in stats.items():
        print(f"  {name}: train={s['train']}, test={s['test']}, raw={s['raw']}")
