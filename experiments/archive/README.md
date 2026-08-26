# Experiment cold archive

This directory keeps large, reproducible experiment artifacts out of the hot
workspace. The experiment source, small reports, protocols, and result summaries
remain under `experiments/`; only cloned upstream repositories and completed run
workspaces are compressed here.

`MANIFEST.json` records the original path, file count, uncompressed size, archive
name, SHA-256 digest, and archive size. To inspect or restore a bundle on Windows:

```powershell
Expand-Archive -LiteralPath experiments/archive/<bundle>.zip -DestinationPath <target>
```

The ZIP files are intentionally ignored by Git because they include model I/O,
temporary workspaces, binaries, and third-party source. Keep the manifest in Git
and back up the ZIP files with the project data when the experiment evidence must
be retained across machines.

## Hot vs. cold data

- Hot: experiment runners, README files, task protocols, top-level reports, and
  `experiments/results/` summaries.
- Cold: `*/_runs/`, cloned repositories in `experiments/external/`, disposable
  harness E2E workspaces, and downloaded research PDFs. The small
  `harness-bench-fast` fixture may be selectively restored under
  `experiments/external/` for the real-layer test suite; editor watcher rules
  exclude that directory from the hot UI path.
- Regenerated: Python bytecode, empty logs, frontend build caches, and other
  ordinary runtime caches are not archived.
