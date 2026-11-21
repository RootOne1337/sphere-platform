import { copyFile, mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
const require = createRequire(import.meta.url);
const dest = resolve('public/vendor/elk');
await mkdir(dest, { recursive: true });
const root = dirname(require.resolve('elkjs/package.json'));
await copyFile(resolve(root, 'lib/elk-worker.min.js'), resolve(dest, 'worker-0.12.0.js'));
await copyFile(resolve(root, 'LICENSE.md'), resolve(dest, 'LICENSE.md'));
