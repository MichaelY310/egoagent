# Low-resource real SWE-bench experiments

This directory complements the external Harness-Bench Fast mechanism pilot
with issues collected from real GitHub repositories.  The first smoke instance
is `pallets__flask-5014` from SWE-bench Verified.

The agent receives the issue statement, repository at the benchmark base
commit, and official reproduction test.  It does **not** receive the gold
solution patch.  The test patch is installed before the episode and the runner
blocks network and confines tools to the isolated repository copy.

Because the host uses Python 3.13 while the issue dates from Flask 2.3, the
local venv pins `pytest==7.4.4` and `Werkzeug==2.3.8`, and the focused test uses
`--override-ini filterwarnings=ignore` to avoid treating host-version
deprecations as product failures.  This is a low-resource smoke, not an
official SWE-bench score.  Official leaderboard evaluation should use the
benchmark Docker image.

Run:

```powershell
python experiments\real_swebench\run_flask_5014.py
```

### Observed V4 Flash result (2026-08-13)

The base commit first failed the official reproduction test with `DID NOT
RAISE ValueError`. Without seeing the gold solution patch, V4 Flash inspected
the test and `Blueprint.__init__`, added a three-line non-empty-name guard, and
passed both the focused official test and all 60 tests in
`tests/test_blueprints.py`. The post-run diff was byte-equivalent in behavior
and message to the benchmark gold patch. Runtime usage was 9 model calls, 11
tool calls, 43,294 actual tokens and about 31 seconds.

The structured evidence is written to
`experiments/real_swebench/_runs/pallets__flask-5014_v4.json` (ignored by Git).
This proves the real-issue execution path works; one easy issue is not evidence
for a general SWE-bench score or for cross-task self-evolution.
