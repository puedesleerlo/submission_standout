import { spawn } from 'node:child_process';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { resolve } from 'node:path';

await mkdir('.local', { recursive: true });
const data = await mkdtemp(resolve('.local/e2e-'));
await writeFile(`${data}/access.json`, JSON.stringify({ observer: 'standout-e2e-observer', learner: 'standout-e2e-learner' }), { mode: 0o600 });
const child = spawn('node', ['scripts/dev.mjs'], { stdio: 'inherit', env: {
  ...process.env, STANDOUT_DATA_DIR: data, STANDOUT_API_PORT: '8001', STANDOUT_WEB_PORT: '5174', STANDOUT_ASGI_APP: 'tests.browser_app:app',
} });
child.on('exit', async code => { await rm(data, { recursive: true, force: true }); process.exit(code || 0); });
process.on('SIGINT', () => child.kill('SIGTERM'));
process.on('SIGTERM', () => child.kill('SIGTERM'));
