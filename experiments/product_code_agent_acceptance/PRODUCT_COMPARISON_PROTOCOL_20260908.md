# P6 — end-to-end code product comparison protocol

This protocol is frozen before any fresh external-runner episode.

## Purpose

Compare the product entry points on identical redistributable fixtures and
deterministic checkers. This is an end-to-end product comparison, **not** a causal
mechanism ablation: Original Codex uses its configured OpenAI model/runtime, while
EgoAgent lanes use the configured DeepSeek V4 Flash provider and Flow policies.

## Tasks

- `product_compare_small`: verbatim copy of the five-test two-file repair fixture.
- `product_compare_large`: verbatim copy of the 31-file dual-subsystem fixture.

Both run offline inside fresh Task Bench workspaces. The prompts, files, timeout and
checker are identical across lanes. Test files and contracts are immutable inputs.

## Lanes

1. `code_agent_fast`
2. `code_agent_auto`
3. `code_agent_long`
4. `code_agent_team`
5. `product_core_code_agent`
6. `codex_cli` (installed upstream CLI, unmodified; no EgoAgent Flow or Identity)

Each lane retains its real product policy and budget. Therefore a lower internal cap
is part of that product configuration; the comparison does not pretend all harnesses
have identical internals. All lanes share the Task timeout and executable scoring.

## Outcomes

- deterministic task score and test evidence;
- wall time and reported token/tool/model counts (provider accounting is reported
  per runner and not assumed perfectly commensurate);
- autonomous child-Agent use and whether it occurs only on defensible scopes;
- exact EgoAgent Flow version or upstream Codex CLI version;
- replay/trajectory completeness and runner boundary;
- errors, timeouts and policy blocks remain failures; they are never silently rerun
  into the same replicate.

One run per cell is a minimum product smoke comparison. It is sufficient to reveal
broken lanes and gross cost differences, but not to rank model quality statistically.
