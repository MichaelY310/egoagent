"""Imitation-style reward used only by the tiny verl integration smoke.

This is not the product's default research reward. Production trajectories
must use TaskBench verifiers, environment outcomes or Evolution Certificates.
"""

from __future__ import annotations

from difflib import SequenceMatcher


def compute_score(data_source, solution_str, ground_truth, extra_info=None, **kwargs):
    expected = str(ground_truth or "").strip()
    actual = str(solution_str or "").strip()
    if not expected:
        return 0.0
    if actual == expected:
        return 1.0
    return float(SequenceMatcher(None, actual, expected).ratio())
