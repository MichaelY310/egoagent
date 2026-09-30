import { copyFile, cp, mkdir, readdir, rm, stat } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const editorRoot = path.resolve(scriptDir, '..');
const source = path.join(editorRoot, 'dist');
const repositoryRoot = path.resolve(editorRoot, '..');
const canonicalExtension = path.join(repositoryRoot, 'void_extension', 'egoagent-dag-chat');
const canonicalWorkbench = path.join(canonicalExtension, 'workbench');
const canonicalMedia = path.join(canonicalExtension, 'media');
const runtimeExtension = path.join(repositoryRoot, 'void-web', 'extensions', 'egoagent-dag-chat');
const runtimeWorkbench = path.join(runtimeExtension, 'workbench');
const runtimeMedia = path.join(runtimeExtension, 'media');

await stat(path.join(source, 'index.html'));

// Copy the new build before pruning obsolete hashed assets.  On Windows the
// running web runtime can briefly hold a static asset open; deleting the whole
// directory first used to leave the extension half-packaged when that happened.
// A locked obsolete file is harmless because index.html no longer references
// it, so pruning is deliberately best-effort.
async function syncDirectory(sourceDir, targetDir) {
  await mkdir(targetDir, { recursive: true });
  await cp(sourceDir, targetDir, { recursive: true, force: true });

  async function prune(currentSource, currentTarget) {
    for (const entry of await readdir(currentTarget, { withFileTypes: true })) {
      const sourceEntry = path.join(currentSource, entry.name);
      const targetEntry = path.join(currentTarget, entry.name);
      let sourceStat = null;
      try {
        sourceStat = await stat(sourceEntry);
      } catch (error) {
        if (error?.code !== 'ENOENT') throw error;
      }
      if (!sourceStat) {
        try {
          await rm(targetEntry, { recursive: true, force: true, maxRetries: 3, retryDelay: 80 });
        } catch (error) {
          if (!['EBUSY', 'EPERM'].includes(error?.code)) throw error;
          console.warn(`Skipped locked obsolete asset: ${targetEntry}`);
        }
      } else if (entry.isDirectory() && sourceStat.isDirectory()) {
        await prune(sourceEntry, targetEntry);
      }
    }
  }

  await prune(sourceDir, targetDir);
}

// Keep the reviewable extension package and the extension directory loaded by
// the local Void web runtime on the exact same build.  Previously only the
// canonical package was updated, so browser testing used the new UI while Void
// continued serving a stale workbench from void-web/extensions.
await mkdir(canonicalExtension, { recursive: true });
await syncDirectory(source, canonicalWorkbench);

await mkdir(runtimeExtension, { recursive: true });
await syncDirectory(source, runtimeWorkbench);
await syncDirectory(canonicalMedia, runtimeMedia);
// connection-runtime.js is generated per installation (and may carry a
// remote credential). Do not replace it with the source stub while packaging.
for (const entry of ['extension-v21.js', 'completion.js', 'remote-workspaces.js', 'package.json', 'README.md']) {
  await copyFile(path.join(canonicalExtension, entry), path.join(runtimeExtension, entry));
}
// Retired interactive tutorial; remove its exact installed entry, not user data.
await rm(path.join(runtimeExtension, 'recording-tutorials.js'), { force: true });

console.log(`Packaged Agent Workbench: ${canonicalWorkbench}`);
console.log(`Synced active Void extension: ${runtimeExtension}`);
