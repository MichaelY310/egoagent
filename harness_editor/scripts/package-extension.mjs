import { cp, mkdir, rm, stat } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const editorRoot = path.resolve(scriptDir, '..');
const source = path.join(editorRoot, 'dist');
const target = path.resolve(editorRoot, '..', 'void_extension', 'egoagent-dag-chat', 'workbench');

await stat(path.join(source, 'index.html'));
await mkdir(path.dirname(target), { recursive: true });
await rm(target, { recursive: true, force: true });
await cp(source, target, { recursive: true });
console.log(`Packaged Agent Workbench: ${target}`);
