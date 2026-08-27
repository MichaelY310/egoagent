import { copyFile, cp, mkdir, rm, stat } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const editorRoot = path.resolve(scriptDir, '..');
const source = path.join(editorRoot, 'dist');
const repositoryRoot = path.resolve(editorRoot, '..');
const canonicalExtension = path.join(repositoryRoot, 'void_extension', 'egoagent-dag-chat');
const canonicalWorkbench = path.join(canonicalExtension, 'workbench');
const runtimeExtension = path.join(repositoryRoot, 'void-web', 'extensions', 'egoagent-dag-chat');
const runtimeWorkbench = path.join(runtimeExtension, 'workbench');

await stat(path.join(source, 'index.html'));

// Keep the reviewable extension package and the extension directory loaded by
// the local Void web runtime on the exact same build.  Previously only the
// canonical package was updated, so browser testing used the new UI while Void
// continued serving a stale workbench from void-web/extensions.
await mkdir(canonicalExtension, { recursive: true });
await rm(canonicalWorkbench, { recursive: true, force: true });
await cp(source, canonicalWorkbench, { recursive: true });

await mkdir(runtimeExtension, { recursive: true });
await rm(runtimeWorkbench, { recursive: true, force: true });
await cp(source, runtimeWorkbench, { recursive: true });
for (const entry of ['extension-v21.js', 'package.json', 'README.md']) {
  await copyFile(path.join(canonicalExtension, entry), path.join(runtimeExtension, entry));
}

console.log(`Packaged Agent Workbench: ${canonicalWorkbench}`);
console.log(`Synced active Void extension: ${runtimeExtension}`);
