import { spawn } from 'node:child_process';

const children = [];
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  children.forEach(child => child.kill('SIGTERM'));
  setTimeout(() => process.exit(code), 300);
}
function start(command, args) {
  const child = spawn(command, args, { stdio: 'inherit' });
  children.push(child);
  child.on('error', error => { console.error(error.message); stop(1); });
  child.on('exit', code => { if (!stopping) stop(code || 0); });
}
start('uv', ['run', 'uvicorn', process.env.STANDOUT_ASGI_APP || 'backend.app:app', '--host', '127.0.0.1', '--port', process.env.STANDOUT_API_PORT || '8000']);
start('pnpm', ['dev:web']);
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());
