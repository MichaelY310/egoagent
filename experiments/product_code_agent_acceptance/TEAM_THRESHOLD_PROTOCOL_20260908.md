# P5 — isolated Team threshold protocol

This file freezes the Team-threshold comparison before the fresh model runs.

## Question

At what scope size does cost-gated, isolated child-Agent execution begin to help
without being invoked as decoration?

## Treatments

- `code_agent_long`: capability search, Memory, passive compaction, tool-result
  pruning and the long-horizon loop; autonomous delegation is disabled.
- `code_agent_team`: the same underlying `product_adaptive_code_agent` component
  and first-turn policies, with cost-gated delegation enabled. Evolution is not due
  on these one-turn tasks, so it cannot distinguish the arms.

Both use `adaptive_deepseek_coder`, DeepSeek V4 Flash, isolated Task Bench
workspaces, the same executable checker and one replicate per cell.

## Frozen size ladder

The source fixtures are copied verbatim into experiment-specific task IDs so the
original product acceptance metadata is not rewritten.

1. `team_threshold_small`: two disjoint single-file implementations, five tests.
2. `team_threshold_medium`: two disjoint packages, each below the deterministic
   child gate unless the model incorrectly inflates the scope.
3. `team_threshold_large`: two disjoint multi-file subsystems; at least one child
   scope is expected to meet `files >= 12 OR bytes >= 12000`.

`generate_team_threshold_assets.py` records exact file and byte counts in each
generated task's `experiment.team_threshold` object.

## Primary outcomes

1. deterministic task score;
2. whether an autonomous child actually ran;
3. provider-reported actual tokens, model calls, tool calls and elapsed time;
4. whether the deterministic gate correctly remains off below threshold;
5. whether the parent consumes child evidence without duplicating the child scope.

## Interpretation guardrails

- Team is useful only if it improves a failed single-Agent cell, prevents overflow,
  or preserves success with a defensible isolation/cost benefit.
- A child launch by itself is not success.
- One run per cell is product acceptance evidence, not a statistically powered
  model-quality claim.
- If both arms pass small/medium and Team costs more, the correct result is that
  Team should remain opt-in below the measured boundary.
